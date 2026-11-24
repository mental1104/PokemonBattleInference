import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 同步协议 v1 的不可变请求；知识/引擎版本随编辑快照发送，不从更新后的知识库推测。
public struct SyncOperation: Codable, Sendable {
    public let schemaVersion: Int
    public let operationId: UUID
    public let entityId: UUID
    public let baseRevision: Int64
    public let localSequence: Int64
    public let kind: ConfigurationChangeKind
    public let configuration: BattleConfiguration
    public let knowledgeVersion: String
    public let engineVersion: String
    /// change 为 SQLite 中已冻结的离线快照，转换不改变 operationId 或 revision。
    public init(change: PendingConfigurationChange) {
        schemaVersion = 1; operationId = change.operationId; entityId = change.entityId; baseRevision = change.baseRevision
        localSequence = change.localSequence; kind = change.kind; configuration = change.configuration
        knowledgeVersion = change.knowledgeVersion; engineVersion = change.engineVersion
    }
}

/// 完整服务端快照；删除仍保留原配置，revision 为用户范围的单调递增提交游标。
public struct SyncSnapshot: Codable, Sendable {
    public let entityId: UUID
    public let revision: Int64
    public let deleted: Bool
    public let configuration: BattleConfiguration
    public let knowledgeVersion: String
    public let engineVersion: String
}

/// 操作回执；status 仅允许 accepted/conflict，冲突 current 可空表示服务端没有此 ID。
public struct SyncResult: Codable, Sendable {
    public let operationId: UUID
    public let status: String
    public let current: SyncSnapshot?
}

/// 已提交变更页，nextCursor 只推进到本页最后一项；客户端同事务应用后才保存。
public struct SyncPage: Codable, Sendable {
    public let changes: [SyncSnapshot]
    public let nextCursor: Int64
    public let hasMore: Bool
}

/// 未决冲突保留本地完整输入与远端完整快照；UI 必须请求用户明确选择。
public struct SyncConflict: Identifiable, Sendable {
    public var id: UUID { entityId }
    public let entityId: UUID
    public let local: StoredConfiguration
    public let remote: SyncSnapshot?
}

/// 人工恢复选择；keepLocal 生成新幂等操作，keepRemote 归档本地冲突副本并采用远端。
public enum SyncConflictResolution: Sendable { case keepLocal, keepRemote }

/// 一次同步实际完成的统计；conflicts 是结束时仍待处理的数量。
public struct SyncSummary: Sendable {
    public let accepted: Int
    public let received: Int
    public let conflicts: Int
}

/// 传输层仅处理协议 I/O；scopeIdentifier 唯一区分服务端和用户，防止混用增量游标或用户库。
public protocol SyncTransport: Sendable {
    var scopeIdentifier: String { get }
    /// operation 是首次发送前已持久化冻结的请求；失败必须抛错，让下一次复用同一请求。
    func push(_ operation: SyncOperation) async throws -> SyncResult
    /// after 为已持久化游标，返回有序增量；分页大小由实现约束为最多 200。
    func pull(after: Int64) async throws -> SyncPage
}

/// 网络/状态错误不包含用户载荷或凭据；HTTP 状态只用于诊断，离线失败保留全部队列。
public enum SyncFailure: Error, Sendable {
    case invalidEndpoint, httpStatus(Int), invalidResponse, alreadyRunning, scopeMismatch, cycleLimit
}

/// 使用 URLSession 的真实 HTTP 传输。X-Pokeop-User 延续当前可信入口约定，不构成互联网身份认证。
public struct HTTPSyncTransport: SyncTransport {
    private let endpoint: URL
    private let userId: String
    public let scopeIdentifier: String
    /// serverURL 为 HTTP(S) 根地址，userId 为可信服务入口分配的用户；拒绝 URL 内嵌凭据和空身份。
    public init(serverURL: URL, userId: String) throws {
        guard ["http", "https"].contains(serverURL.scheme?.lowercased() ?? ""), serverURL.host != nil,
              serverURL.user == nil, serverURL.password == nil, serverURL.query == nil, serverURL.fragment == nil,
              !userId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, userId.utf8.count <= 256,
              !userId.contains("\r"), !userId.contains("\n") else { throw SyncFailure.invalidEndpoint }
        endpoint = serverURL.appendingPathComponent("v1/sync"); self.userId = userId
        scopeIdentifier = endpoint.absoluteString + "|" + userId
    }
    /// operation 按 snake_case JSON 发出；重试使用持久化原请求，不生成新的 operationId。
    public func push(_ operation: SyncOperation) async throws -> SyncResult {
        var request = URLRequest(url: endpoint); request.httpMethod = "POST"
        // UUID 的默认编码为大写；服务端要求 canonical lowercase，使用定制协议编码保持跨语言一致。
        request.httpBody = try Self.encoder().encode(operation)
        return try await send(request, as: SyncResult.self)
    }
    /// after 是本设备已应用的 revision；空页不自行提升游标。
    public func pull(after: Int64) async throws -> SyncPage {
        guard after >= 0, var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else { throw SyncFailure.invalidEndpoint }
        components.queryItems = [URLQueryItem(name: "after", value: String(after)), URLQueryItem(name: "limit", value: "10")]
        guard let url = components.url else { throw SyncFailure.invalidEndpoint }
        return try await send(URLRequest(url: url), as: SyncPage.self)
    }
    /// request 为已选定 URL 的请求；type 保留具体返回类型，取消沿 URLSession 传播，非 200 不解析为成功。
    private func send<Value: Decodable & Sendable>(_ request: URLRequest, as type: Value.Type) async throws -> Value {
        var request = request; request.timeoutInterval = 30
        request.setValue(userId, forHTTPHeaderField: "X-Pokeop-User"); request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw SyncFailure.invalidResponse }
        guard http.statusCode == 200 else { throw SyncFailure.httpStatus(http.statusCode) }
        guard data.count <= 16 * 1024 * 1024 else { throw SyncFailure.invalidResponse }
        return try ContractJSON.decoder().decode(type, from: data)
    }
    /// 返回协议专用编码器；UUID 小写由 SyncOperation 的显式编码完成，配置 UUID 保持可解码原值。
    private static func encoder() -> JSONEncoder { ContractJSON.encoder() }
}

/// 每次调用完成离线队列发送和所有增量页；actor 防止同实例重入造成有序队列并行发送。
public actor SyncClient {
    private let store: ConfigurationStore
    private let transport: any SyncTransport
    private var running = false
    /// store 为实际用户 SQLite，transport 为对应服务端/身份；初始化不联网或删除任何内容。
    public init(store: ConfigurationStore, transport: any SyncTransport) { self.store = store; self.transport = transport }
    /// 顺序发送已冻结操作，然后拉取增量；任何网络失败保留未确认请求，下次调用自动重试。
    public func synchronize() async throws -> SyncSummary {
        guard !running else { throw SyncFailure.alreadyRunning }; running = true; defer { running = false }
        try await store.bindSyncScope(transport.scopeIdentifier)
        var accepted = 0, received = 0, cycles = 0
        while let operation = try await store.prepareSyncOperation() {
            try Task.checkCancellation(); cycles += 1; guard cycles <= 10000 else { throw SyncFailure.cycleLimit }
            let result = try await transport.push(operation)
            try await store.acknowledge(operation, result: result)
            if result.status == "accepted" { accepted += 1 }
        }
        while true {
            try Task.checkCancellation(); cycles += 1; guard cycles <= 10000 else { throw SyncFailure.cycleLimit }
            let cursor = try await store.syncCursor(), page = try await transport.pull(after: cursor)
            guard !page.hasMore || page.nextCursor > cursor else { throw SyncFailure.invalidResponse }
            try await store.applySyncPage(page); received += page.changes.count
            if !page.hasMore { break }
        }
        return SyncSummary(accepted: accepted, received: received, conflicts: try await store.syncConflicts().count)
    }
}

extension SyncOperation {
    /// 将协议身份字段编码成 canonical lowercase UUID；encoder 由传输层提供 snake_case 规则。
    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(schemaVersion, forKey: .schemaVersion); try container.encode(operationId.uuidString.lowercased(), forKey: .operationId)
        try container.encode(entityId.uuidString.lowercased(), forKey: .entityId); try container.encode(baseRevision, forKey: .baseRevision)
        try container.encode(localSequence, forKey: .localSequence); try container.encode(kind, forKey: .kind)
        try container.encode(configuration, forKey: .configuration); try container.encode(knowledgeVersion, forKey: .knowledgeVersion)
        try container.encode(engineVersion, forKey: .engineVersion)
    }
}
