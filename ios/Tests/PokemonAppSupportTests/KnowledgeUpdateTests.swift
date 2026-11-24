import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import PokemonAppSupport

/// 观察真实 delegate 传来的字节，用于在明确收到正文后触发取消，不依赖猜测下载时长。
private actor DownloadObserver {
    private var received: Int64 = 0
    /// state 是当前传输事件，返回值不用于推进下载。
    func record(_ state: KnowledgeUpdateProgress) { if case .downloading(let value, _) = state { received = max(received, value) } }
    /// 返回实际观察过的最大前缀；跨线程投递的回调顺序不会把已经观察到的字节倒退为零。
    func bytes() -> Int64 { received }
}

/// 真实 HTTP + SHA + SQLite 更新验收；fixture 只提供网络故障，客户端仍执行完整生产下载/安装。
final class KnowledgeUpdateTests: XCTestCase, @unchecked Sendable {
    /// 每个场景只拥有其 UUID 根目录和 Python 子进程；退出时清理自己的输入并归档协议证据。
    private struct Fixture {
        let root: URL
        let server: URL
        let process: Process
        let initial: KnowledgeManifest
        let candidate: KnowledgeManifest
        let store: KnowledgeStore
        let users: ConfigurationStore
        let configuration: BattleConfiguration
        var downloads: URL { root.appendingPathComponent("downloads") }
        var pointer: URL { root.appendingPathComponent("installed/current.json") }
        /// scenario 是 fixture 的固定路由；返回真实回环 HTTP 清单地址。
        func manifest(_ scenario: String) -> URL { server.appendingPathComponent("\(scenario)/manifest.json") }
        /// 创建新客户端复用持久暂存，模拟进程重启后没有内存传输状态的情况。
        func client() -> KnowledgeUpdateClient { KnowledgeUpdateClient(store: store, directory: downloads) }
        /// 客户端已看到真实正文后，经独立 HTTP 控制请求切断首次下载；不修改客户端或暂存文件。
        func interruptDownload() async throws {
            var request = URLRequest(url: server.appendingPathComponent("drop/interrupt"))
            request.httpMethod = "POST"
            let (_, response) = try await URLSession.shared.data(for: request)
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 204)
        }
        /// name 为当前测试证据目录名；停止子进程后仅归档此测试的输入/响应/指针和用户配置。
        func finish(_ name: String) {
            process.terminate(); process.waitUntilExit()
            if let report = ProcessInfo.processInfo.environment["PBI_KNOWLEDGE_HTTP_REPORT_DIRECTORY"] {
                let target = URL(fileURLWithPath: report).appendingPathComponent(name).appendingPathComponent(root.lastPathComponent)
                try? FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
                for path in ["ready.txt", "fixture-startup.txt", "http.jsonl", "fixture.stderr.log", "manifest.json", "installed/current.json", "users.sqlite"] {
                    try? FileManager.default.copyItem(at: root.appendingPathComponent(path), to: target.appendingPathComponent(path.replacingOccurrences(of: "/", with: "-")))
                }
            }
            try? FileManager.default.removeItem(at: root)
        }
    }

    /// 准备真实第二版 SQLite、独立用户库与回环 HTTP 服务；不访问任何现有运行目录。
    private func fixture() async throws -> Fixture {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-http-update-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let bundle = try KnowledgePack.bundled()
        let store = try KnowledgeStore(directory: root.appendingPathComponent("installed"), initial: bundle)
        let initial = await store.version()
        let database = root.appendingPathComponent("knowledge.sqlite")
        try FileManager.default.copyItem(at: bundle.database, to: database)
        do { let connection = try SQLiteConnection(url: database, readOnly: false); try connection.execute("UPDATE metadata SET value='http-update-v2' WHERE key='data_version'") }
        let attributes = try FileManager.default.attributesOfItem(atPath: database.path)
        let candidate = KnowledgeManifest(schemaVersion: 1, dataVersion: "http-update-v2", sourceRevision: initial.sourceRevision,
            inputSha256: initial.inputSha256, sqliteSha256: try FileChecksum.sha256(database), byteSize: (attributes[.size] as! NSNumber).int64Value, counts: initial.counts, sources: initial.sources)
        try ContractJSON.encoder().encode(candidate).write(to: root.appendingPathComponent("manifest.json"))
        let users = try ConfigurationStore(url: root.appendingPathComponent("users.sqlite"))
        let configuration = BattleConfiguration.example()
        try await users.save(configuration, knowledgeVersion: initial.dataVersion, engineVersion: "0.5.0")
        let process = Process()
        let python = ProcessInfo.processInfo.environment["PBI_KNOWLEDGE_TEST_PYTHON"]
        process.executableURL = URL(fileURLWithPath: python ?? "/usr/bin/env")
        let source = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let ready = root.appendingPathComponent("ready.txt")
        process.arguments = (python == nil ? ["python3", "-u"] : ["-u"]) + [source.appendingPathComponent("tests/fixtures/knowledge_http_server.py").path,
            "--directory", root.path, "--ready-file", ready.path, "--audit", root.appendingPathComponent("http.jsonl").path]
        let errorLog = root.appendingPathComponent("fixture.stderr.log")
        guard FileManager.default.createFile(atPath: errorLog.path, contents: nil) else { throw StorageFailure.fileOperation("cannot create HTTP fixture log") }
        let errors = try FileHandle(forWritingTo: errorLog)
        process.standardOutput = FileHandle.nullDevice; process.standardError = errors
        try process.run()
        try errors.close()
        for _ in 0..<200 {
            // URL(string: "") 可创建相对 URL；只有完整回环 HTTP 地址才代表服务已就绪。
            if let address = try? String(contentsOf: ready, encoding: .utf8), let server = URL(string: address),
               server.scheme == "http", server.host == "127.0.0.1", server.port != nil, server.path.isEmpty {
                return Fixture(root: root, server: server, process: process, initial: initial, candidate: candidate, store: store, users: users, configuration: configuration)
            }
            if !process.isRunning { break }
            try await Task.sleep(for: .milliseconds(25))
        }
        // 超时先记录实际启动身份/状态；诊断不包含环境变量或连接凭据。
        let startup = "executable=\(process.executableURL?.path ?? "")\npid=\(process.processIdentifier)\nrunning=\(process.isRunning)\n"
        try? startup.write(to: root.appendingPathComponent("fixture-startup.txt"), atomically: true, encoding: .utf8)
        if process.isRunning { process.terminate(); process.waitUntilExit() }
        let diagnostic = String((try? String(contentsOf: errorLog, encoding: .utf8))?.prefix(8192) ?? "")
        if let report = ProcessInfo.processInfo.environment["PBI_KNOWLEDGE_HTTP_REPORT_DIRECTORY"] {
            let target = URL(fileURLWithPath: report).appendingPathComponent("fixture-startup-failure").appendingPathComponent(root.lastPathComponent)
            try? FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
            for path in ["ready.txt", "fixture-startup.txt", "fixture.stderr.log"] {
                try? FileManager.default.copyItem(at: root.appendingPathComponent(path), to: target.appendingPathComponent(path))
            }
        }
        try? FileManager.default.removeItem(at: root)
        throw StorageFailure.fileOperation("HTTP fixture did not become ready: \(diagnostic)")
    }

    /// 截断响应必须失败且旧知识/配置不变；新建客户端从真实文件长度续传206，原子切换并保留旧文件。
    func testInterruptedHTTPResumesFromDiskAndPreservesUserStore() async throws {
        let value = try await fixture(); defer { value.finish("interrupted-resume") }
        let previous = try Data(contentsOf: value.pointer), source = value.manifest("drop")
        try await value.users.setKnowledgeManifestURL(source)
        let observer = DownloadObserver(), client = value.client()
        let transfer = Task { try await client.update(from: source) { state in Task { await observer.record(state) } } }
        for _ in 0..<200 { if await observer.bytes() >= 8192 { break }; try await Task.sleep(for: .milliseconds(10)) }
        let observed = await observer.bytes(); XCTAssertGreaterThanOrEqual(observed, 8192)
        try await value.interruptDownload()
        do { _ = try await transfer.value; XCTFail("truncated HTTP response was accepted") } catch { }
        XCTAssertEqual(try Data(contentsOf: value.pointer), previous)
        let old = await value.store.version(); XCTAssertEqual(old, value.initial)
        let partial = value.downloads.appendingPathComponent("download-\(value.candidate.sqliteSha256).partial")
        let bytes = (try FileManager.default.attributesOfItem(atPath: partial.path)[.size] as! NSNumber).int64Value
        XCTAssertGreaterThan(bytes, 0); XCTAssertLessThan(bytes, value.candidate.byteSize)
        let installed = try await value.client().update(from: source)
        XCTAssertEqual(installed, value.candidate)
        let audit = try String(contentsOf: value.root.appendingPathComponent("http.jsonl"), encoding: .utf8)
        XCTAssertTrue(audit.contains("bytes=\(bytes)-")); XCTAssertTrue(audit.contains("\"status\": 206"))
        let reopened = try KnowledgeStore(directory: value.root.appendingPathComponent("installed"), initial: KnowledgePack.bundled())
        let restarted = await reopened.version(); XCTAssertEqual(restarted, value.candidate)
        XCTAssertTrue(FileManager.default.fileExists(atPath: value.root.appendingPathComponent("installed/knowledge-\(value.initial.sqliteSha256).sqlite").path))
        let reopenedUsers = try ConfigurationStore(url: value.root.appendingPathComponent("users.sqlite"))
        let saved = try await reopenedUsers.all(); XCTAssertEqual(saved.map(\.configuration), [value.configuration])
        let savedSource = try await reopenedUsers.knowledgeManifestURL(); XCTAssertEqual(savedSource, source)
        let pending = try await reopenedUsers.pendingChanges(); XCTAssertEqual(pending.count, 1)
        let pokemon = try await reopened.pokemon(212); XCTAssertEqual(pokemon.summary.name, "巨钳螳螂")
    }

    /// 实际正文到达后取消必须停止传输；同一 actor 拒绝并发更新，下一客户端从保留前缀恢复。
    func testCancelRealHTTPThenRetry() async throws {
        let value = try await fixture(); defer { value.finish("cancel-retry") }
        let previous = try Data(contentsOf: value.pointer), observer = DownloadObserver(), client = value.client()
        let transfer = Task { try await client.update(from: value.manifest("slow")) { state in Task { await observer.record(state) } } }
        for _ in 0..<200 { if await observer.bytes() >= 8192 { break }; try await Task.sleep(for: .milliseconds(10)) }
        let observed = await observer.bytes(); XCTAssertGreaterThanOrEqual(observed, 8192)
        do { _ = try await client.update(from: value.manifest("good")); XCTFail("concurrent update was accepted") }
        catch KnowledgeUpdateFailure.updateInProgress { }
        transfer.cancel()
        do { _ = try await transfer.value; XCTFail("cancelled transfer was accepted") } catch is CancellationError { }
        XCTAssertEqual(try Data(contentsOf: value.pointer), previous)
        let before = try await value.users.all(); XCTAssertEqual(before.map(\.configuration), [value.configuration])
        // 服务器忽略 Range 返回完整200时必须丢弃旧前缀重下，不能把完整文件追加到部分文件后。
        let installed = try await value.client().update(from: value.manifest("no-range")); XCTAssertEqual(installed, value.candidate)
        let audit = try String(contentsOf: value.root.appendingPathComponent("http.jsonl"), encoding: .utf8)
        XCTAssertTrue(audit.contains("/no-range/knowledge.sqlite")); XCTAssertTrue(audit.contains("\"range\": \"bytes="))
    }

    /// 校验损坏、404、超大清单及重定向都必须明确失败，旧指针和用户队列保持完全可用。
    func testHTTPBoundaryFailuresKeepOldKnowledgeAndConfigurations() async throws {
        let value = try await fixture(); defer { value.finish("rejected-responses") }
        let previous = try Data(contentsOf: value.pointer)
        do { _ = try await value.client().update(from: value.manifest("corrupt")); XCTFail("corrupt bytes were installed") }
        catch StorageFailure.checksumMismatch { }
        do { _ = try await value.client().update(from: value.manifest("missing")); XCTFail("HTTP 404 was accepted") }
        catch KnowledgeUpdateFailure.httpStatus(let status) { XCTAssertEqual(status, 404) }
        do { _ = try await value.client().update(from: value.manifest("oversize")); XCTFail("oversized manifest was accepted") }
        catch KnowledgeUpdateFailure.responseTooLarge { }
        do { _ = try await value.client().update(from: value.manifest("redirect")); XCTFail("HTTP redirect was followed") }
        catch KnowledgeUpdateFailure.httpStatus(let status) { XCTAssertEqual(status, 302) }
        XCTAssertEqual(try Data(contentsOf: value.pointer), previous)
        let old = await value.store.version(); XCTAssertEqual(old, value.initial)
        let saved = try await value.users.all(); XCTAssertEqual(saved.map(\.configuration), [value.configuration])
        let pending = try await value.users.pendingChanges(); XCTAssertEqual(pending.count, 1)
        let pokemon = try await value.store.pokemon(212); XCTAssertEqual(pokemon.baseStats.attack, 130)
        for endpoint in ["file:///manifest.json", "https://example.invalid/manifest.json?secret=x", "https://example.invalid/folder/"] {
            do { _ = try KnowledgeUpdateClient.validateManifestURL(URL(string: endpoint)!); XCTFail("invalid manifest endpoint was accepted") }
            catch KnowledgeUpdateFailure.invalidEndpoint { }
        }
    }
}
