import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 更新边界错误；取消保留为 CancellationError，现有知识版本在提交前不会被改变。
public enum KnowledgeUpdateFailure: Error, Sendable {
    case invalidEndpoint, invalidManifest, invalidResponse, responseTooLarge, updateInProgress
    case httpStatus(Int)
}

/// 更新状态只报告实际网络字节和已进入的安装阶段，不生成定时器进度。
public enum KnowledgeUpdateProgress: Sendable {
    case fetchingManifest
    case downloading(received: Int64, total: Int64)
    case validating
    case installing
}

/// 一个流式 HTTP 请求；串行 delegate queue 独占文件/响应/continuation，锁只协调跨线程取消与 task 注册。
private final class KnowledgeTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let destination: URL
    private let limit: Int64
    private let expectedSize: Int64?
    private let progress: @Sendable (Int64) -> Void
    private let lock = NSLock()
    private var cancelled = false
    private var task: URLSessionDataTask?
    private var continuation: CheckedContinuation<Void, Error>?
    private var file: FileHandle?
    private var received: Int64
    private var failure: Error?

    /// destination 是此客户端拥有的暂存文件，offset 是其完整落盘长度；limit 限制实际写入总量。
    /// expectedSize 只对 SQLite 设置，progress 在串行 delegate queue 报告真实已存字节。
    init(destination: URL, offset: Int64, limit: Int64, expectedSize: Int64?, progress: @escaping @Sendable (Int64) -> Void) {
        self.destination = destination; received = offset; self.limit = limit; self.expectedSize = expectedSize; self.progress = progress
    }

    /// request 是已校验的 HTTP 请求；失败或取消保留已收到的文件供下一次 Range 重试。
    func run(_ request: URLRequest) async throws {
        try await withTaskCancellationHandler {
            try Task.checkCancellation()
            try await withCheckedThrowingContinuation { (value: CheckedContinuation<Void, Error>) in
                do {
                    if !FileManager.default.fileExists(atPath: destination.path) {
                        guard FileManager.default.createFile(atPath: destination.path, contents: nil) else { throw StorageFailure.fileOperation("cannot create download staging file") }
                    }
                    file = try FileHandle(forWritingTo: destination); try file?.seekToEnd()
                    continuation = value
                    let queue = OperationQueue(); queue.maxConcurrentOperationCount = 1
                    let configuration = URLSessionConfiguration.ephemeral
                    configuration.timeoutIntervalForRequest = 30; configuration.timeoutIntervalForResource = 300
                    let session = URLSession(configuration: configuration, delegate: self, delegateQueue: queue)
                    let next = session.dataTask(with: request)
                    // 即使取消早于 task 创建也要在注册后取消，避免丢失取消信号。
                    lock.lock(); task = next; let shouldCancel = cancelled; lock.unlock()
                    next.resume(); if shouldCancel { next.cancel() }
                } catch { try? file?.close(); file = nil; value.resume(throwing: error) }
            }
        } onCancel: { self.cancel() }
    }

    /// 取消可从任意线程进入；文件和 continuation 仍由 delegate 的唯一完成回调收尾。
    private func cancel() { lock.lock(); cancelled = true; let current = task; lock.unlock(); current?.cancel() }

    /// 拒绝重定向，保证知识和清单都来自用户明确选择的目录，不隐式访问另一主机。
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) { completionHandler(nil) }

    /// 验证 HTTP 和长度再允许接收正文；不支持 Range 的服务器返回200时安全地从头写入。
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void) {
        do {
            guard let response = response as? HTTPURLResponse else { throw KnowledgeUpdateFailure.invalidResponse }
            guard response.statusCode == 200 || response.statusCode == 206 else { throw KnowledgeUpdateFailure.httpStatus(response.statusCode) }
            if response.statusCode == 206 {
                guard received > 0, let expectedSize,
                      response.value(forHTTPHeaderField: "Content-Range") == "bytes \(received)-\(expectedSize - 1)/\(expectedSize)" else { throw KnowledgeUpdateFailure.invalidResponse }
            } else if received > 0 { try file?.truncate(atOffset: 0); try file?.seek(toOffset: 0); received = 0 }
            let advertised = response.expectedContentLength
            guard advertised < 0 || advertised <= limit - received else { throw KnowledgeUpdateFailure.responseTooLarge }
            if let expectedSize, advertised >= 0, advertised != expectedSize - received { throw KnowledgeUpdateFailure.invalidResponse }
            progress(received); completionHandler(.allow)
        } catch { failure = error; completionHandler(.cancel) }
    }

    /// data 是当前真实正文片段；先检查总量再落盘，不信任缺失或伪造的 Content-Length。
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        do {
            guard Int64(data.count) <= limit - received else { throw KnowledgeUpdateFailure.responseTooLarge }
            try file?.write(contentsOf: data); received += Int64(data.count); progress(received)
        } catch { failure = error; dataTask.cancel() }
    }

    /// 网络结束时仅恢复一次 continuation；同步文件后才交给后续 SHA/安装阶段。
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        do { try file?.synchronize(); try file?.close() } catch { if failure == nil { failure = error } }
        file = nil
        lock.lock(); let wasCancelled = cancelled; self.task = nil; lock.unlock()
        let result: Error? = wasCancelled ? CancellationError() : (failure ?? error)
        if let result { continuation?.resume(throwing: result) } else { continuation?.resume() }
        continuation = nil; session.finishTasksAndInvalidate()
    }
}

/// 显式网络更新入口；以 SHA 命名持久暂存文件，重启后仍能从同一完整前缀重试。
/// 不拥有用户配置库；安装校验与原子切换唯一复用 KnowledgeStore.install。
public actor KnowledgeUpdateClient {
    private let store: KnowledgeStore
    private let directory: URL
    private var active = false
    public static let maximumDatabaseBytes: Int64 = 64 * 1024 * 1024
    private static let maximumManifestBytes: Int64 = 1024 * 1024

    /// store 是目标知识 actor；directory 为 App 专属持久下载目录，不清理其他版本或用户数据。
    public init(store: KnowledgeStore, directory: URL) { self.store = store; self.directory = directory }

    /// value 必须是无凭据、无查询/fragment 的 HTTP(S) 清单文件地址；返回规范化原 URL。
    /// 不猜测服务域名，下载的数据库固定为该清单所在目录的 knowledge.sqlite。
    public static func validateManifestURL(_ value: URL) throws -> URL {
        guard ["http", "https"].contains(value.scheme?.lowercased() ?? ""), let host = value.host, !host.isEmpty,
              value.user == nil, value.password == nil, value.query == nil, value.fragment == nil,
              !value.path.isEmpty, !value.hasDirectoryPath, !value.path.hasSuffix("/") else { throw KnowledgeUpdateFailure.invalidEndpoint }
        return value
    }

    /// manifestURL 为用户已保存的明确地址；progress 可跨线程调用，只包含真实状态/字节。
    /// 返回实际安装版本；网络失败/取消保留部分 SQLite，校验失败移除坏暂存以便干净重试。
    public func update(from manifestURL: URL, progress: @escaping @Sendable (KnowledgeUpdateProgress) -> Void = { _ in }) async throws -> KnowledgeManifest {
        let endpoint = try Self.validateManifestURL(manifestURL)
        guard !active else { throw KnowledgeUpdateFailure.updateInProgress }
        active = true; defer { active = false }
        try Task.checkCancellation()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let manifestFile = directory.appendingPathComponent("manifest.download.json")
        // 清单每次重新获取；数据库暂存按 SHA 区分，不将旧 manifest 的部分内容接到新内容上。
        try Data().write(to: manifestFile); progress(.fetchingManifest)
        let manifestTransfer = KnowledgeTransfer(destination: manifestFile, offset: 0, limit: Self.maximumManifestBytes, expectedSize: nil, progress: { _ in })
        try await manifestTransfer.run(Self.request(endpoint))
        let manifest: KnowledgeManifest
        do { manifest = try ContractJSON.decoder().decode(KnowledgeManifest.self, from: Data(contentsOf: manifestFile)) }
        catch { throw KnowledgeUpdateFailure.invalidManifest }
        guard manifest.schemaVersion == 1 else { throw StorageFailure.unsupportedSchema }
        guard !manifest.dataVersion.isEmpty, manifest.byteSize > 0, manifest.byteSize <= Self.maximumDatabaseBytes,
              manifest.sqliteSha256.count == 64, manifest.sqliteSha256.allSatisfy({ "0123456789abcdef".contains($0) }) else { throw KnowledgeUpdateFailure.invalidManifest }
        let partial = directory.appendingPathComponent("download-\(manifest.sqliteSha256).partial")
        var offset = try Self.size(partial)
        if offset > manifest.byteSize { try FileManager.default.removeItem(at: partial); offset = 0 }
        progress(.downloading(received: offset, total: manifest.byteSize))
        if offset < manifest.byteSize {
            var request = Self.request(endpoint.deletingLastPathComponent().appendingPathComponent("knowledge.sqlite"))
            if offset > 0 { request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range") }
            let transfer = KnowledgeTransfer(destination: partial, offset: offset, limit: manifest.byteSize, expectedSize: manifest.byteSize,
                progress: { progress(.downloading(received: $0, total: manifest.byteSize)) })
            try await transfer.run(request)
        }
        try Task.checkCancellation(); progress(.validating)
        guard try Self.size(partial) == manifest.byteSize, try FileChecksum.sha256(partial) == manifest.sqliteSha256 else {
            try? FileManager.default.removeItem(at: partial); throw StorageFailure.checksumMismatch
        }
        try Task.checkCancellation(); progress(.installing)
        // 此提交点之后不检查取消：一旦 install 成功就返回真实新版本，不能误报成未安装。
        try await store.install(KnowledgePack(database: partial, manifest: manifestFile))
        try? FileManager.default.removeItem(at: partial)
        return await store.version()
    }

    /// url 为已校验的清单或同目录数据库地址；禁止缓存/压缩改变 Range 的字节语义。
    private static func request(_ url: URL) -> URLRequest {
        var value = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        value.setValue("identity", forHTTPHeaderField: "Accept-Encoding"); return value
    }
    /// url 为自有暂存文件，不存在表示零字节；其他读取错误正常抛出。
    private static func size(_ url: URL) throws -> Int64 {
        guard FileManager.default.fileExists(atPath: url.path) else { return 0 }
        guard let value = try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber else { throw StorageFailure.fileOperation("cannot inspect download size") }
        return value.int64Value
    }
}
