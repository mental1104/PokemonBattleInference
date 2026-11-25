import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// HTTP 边界错误；服务错误原始正文可归档，UI 不把错误响应当作任务结果。
public enum ConfigurationJobFailure: Error, Sendable {
    case invalidEndpoint, invalidInput, invalidResponse, responseTooLarge
    case httpStatus(Int, Data)
    /// 返回正式服务的detail字符串/业务message；它只是外部文本，UI不得当作HTML或代码执行。
    public var serverDetail: String? {
        guard case .httpStatus(_, let body) = self else { return nil }
        return (try? JSONDecoder().decode(JobErrorEnvelope.self, from: body))?.detail.message
    }
}

/// 原HTTP错误允许detail为普通字符串或业务code/message对象；其余格式不猜测。
private struct JobErrorEnvelope: Decodable {
    let detail: Detail
    /// 仅建模拥有方已有的两种错误形状，不扩散无类型字典。
    enum Detail: Decodable {
        case text(String), business(Business)
        /// 服务的业务错误正文。
        struct Business: Decodable { let code: String; let message: String }
        /// decoder按正式字符串/对象边界解码，不执行服务文本。
        init(from decoder: Decoder) throws {
            let value = try decoder.singleValueContainer()
            if let text = try? value.decode(String.self) { self = .text(text) }
            else { self = .business(try value.decode(Business.self)) }
        }
        /// 保留服务可读诊断并限制界面长度，完整响应仍在错误Data中。
        var message: String { switch self { case .text(let text): String(text.prefix(1500)); case .business(let item): String("\(item.code): \(item.message)".prefix(1500)) } }
    }
}

/// 原 configuration-jobs 的独立强类型客户端；没有 CoreJSON 演示提交，也不自动重试非幂等创建。
public actor ConfigurationJobClient {
    private let endpoint: URL
    private let session = URLSession(configuration: .ephemeral)

    /// serverURL 为用户明确保存的 HTTP(S) 根地址，不接受凭据/query/fragment；不默认连接生产服务。
    public init(serverURL: URL) throws {
        guard ["http", "https"].contains(serverURL.scheme?.lowercased() ?? ""), let host = serverURL.host, !host.isEmpty,
              serverURL.user == nil, serverURL.password == nil, serverURL.query == nil, serverURL.fragment == nil else { throw ConfigurationJobFailure.invalidEndpoint }
        endpoint = serverURL.appendingPathComponent("v1/inference/configuration-jobs")
    }
    /// 客户端结束后只释放自己的 HTTP session，不操作服务端任务。
    deinit { session.invalidateAndCancel() }

    /// command 是原技能池命令；idempotencyKey 为调用者保存的稳定键/null，不生成伪 job ID。
    /// HTTP202只返回确认；超时不自动重复创建，调用者重试必须复用同一个 key。
    public func submit(_ command: ConfigurationJobCommand, idempotencyKey: String? = nil) async throws -> ConfigurationJobCreated {
        if let key = idempotencyKey {
            guard !key.isEmpty, key.count <= 200, !key.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { throw ConfigurationJobFailure.invalidInput }
        }
        var request = URLRequest(url: endpoint); request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key")
        request.httpBody = try ContractJSON.encoder().encode(command)
        let result: ConfigurationJobCreated = try await perform(request, status: 202)
        guard result.status == "pending", result.submittedConfigurationPairs > 0 else { throw ConfigurationJobFailure.invalidResponse }
        _ = try jobURL(result.jobId)
        return result
    }

    /// jobId 为原服务返回的稳定任务ID；返回服务器实际生命周期/计数/资源及冻结规则版本。
    public func status(_ jobId: String) async throws -> ConfigurationJobStatus {
        let value: ConfigurationJobStatus = try await perform(URLRequest(url: jobURL(jobId)))
        guard value.jobId == jobId else { throw ConfigurationJobFailure.invalidResponse }; return value
    }

    /// jobId 为真实任务，offset/limit 是原0起点分页；status=null读取所有case，失败条目不被过滤掉。
    public func results(_ jobId: String, offset: Int = 0, limit: Int = 100, status: ConfigurationCasePhase? = nil) async throws -> ConfigurationJobPage {
        guard (0...Int(Int32.max)).contains(offset), (1...500).contains(limit) else { throw ConfigurationJobFailure.invalidInput }
        var query = [URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: String(limit))]
        if let status { query.append(URLQueryItem(name: "status", value: status.rawValue)) }
        let value: ConfigurationJobPage = try await perform(URLRequest(url: queryURL(try jobURL(jobId).appendingPathComponent("results"), query)))
        guard value.jobId == jobId, value.offset == offset, value.limit == limit else { throw ConfigurationJobFailure.invalidResponse }; return value
    }

    /// jobId 为冻结任务身份，configurationId 为结果的完整 canonical ID（可含 JSON/斜线），不重新生成配置身份。
    /// 返回真实来源；nil 只表示服务显式记录 metadata:null。404/传输/校验失败抛错，不伪装成未知旧版本。
    public func executionMetadata(_ jobId: String, configurationId: String) async throws -> ConfigurationJobExecutionMetadata? {
        guard !configurationId.isEmpty, configurationId != ".", configurationId != "..",
              !configurationId.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { throw ConfigurationJobFailure.invalidInput }
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/%?#\\")
        guard let encoded = configurationId.addingPercentEncoding(withAllowedCharacters: allowed),
              var parts = URLComponents(url: try jobURL(jobId).appendingPathComponent("results"), resolvingAgainstBaseURL: false) else { throw ConfigurationJobFailure.invalidInput }
        // 整个 canonical ID 只能占一个路径段，避免 snapshot 内斜线改变 Go ServeMux 的路由。
        parts.percentEncodedPath += "/\(encoded)/metadata"
        guard let url = parts.url else { throw ConfigurationJobFailure.invalidInput }
        let value: ConfigurationJobMetadataEnvelope = try await perform(URLRequest(url: url))
        return value.metadata
    }

    /// cursor 是服务的 opaque nextCursor/null，status 可选 failed/truncated，errorCode 由原 HTTP 合同验证。
    public func issues(_ jobId: String, cursor: String? = nil, limit: Int = 100, status: ConfigurationCasePhase? = nil, errorCode: String? = nil) async throws -> ConfigurationJobPage {
        guard (1...500).contains(limit), status == nil || status == .failed || status == .truncated else { throw ConfigurationJobFailure.invalidInput }
        var query = [URLQueryItem(name: "limit", value: String(limit))]
        if let cursor { query.append(URLQueryItem(name: "cursor", value: cursor)) }
        if let status { query.append(URLQueryItem(name: "status", value: status.rawValue)) }
        if let errorCode { query.append(URLQueryItem(name: "error_code", value: errorCode)) }
        let value: ConfigurationJobPage = try await perform(URLRequest(url: queryURL(try jobURL(jobId).appendingPathComponent("issues"), query)))
        guard value.jobId == jobId, value.limit == limit else { throw ConfigurationJobFailure.invalidResponse }; return value
    }

    /// 持久化取消真实任务；不把 cancellationRequested 当作已取消，网络失败也不删除 jobId。
    public func cancel(_ jobId: String) async throws -> ConfigurationJobCancellation {
        var request = URLRequest(url: try jobURL(jobId).appendingPathComponent("cancel")); request.httpMethod = "POST"
        let value: ConfigurationJobCancellation = try await perform(request)
        guard value.jobId == jobId else { throw ConfigurationJobFailure.invalidResponse }; return value
    }

    /// id 必须是单个不含控制符/路径跳转的 ID；不猜测 UUID 格式或改变服务返回的身份。
    private func jobURL(_ id: String) throws -> URL {
        guard !id.isEmpty, id == id.trimmingCharacters(in: .whitespacesAndNewlines), id != ".", id != "..", !id.contains("/"), !id.contains("\\"),
              !id.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }) else { throw ConfigurationJobFailure.invalidInput }
        return endpoint.appendingPathComponent(id)
    }

    /// url 是固定服务路径，query 为单一值分页条件；只使用URLComponents编码，不拼接用户参数。
    private func queryURL(_ url: URL, _ query: [URLQueryItem]) throws -> URL {
        guard var parts = URLComponents(url: url, resolvingAgainstBaseURL: false) else { throw ConfigurationJobFailure.invalidEndpoint }
        parts.queryItems = query; guard let value = parts.url else { throw ConfigurationJobFailure.invalidEndpoint }; return value
    }

    /// request 为完整HTTP消息，status为该路由唯一成功码；取消/传输错误自然传播，错误正文保留供复查。
    private func perform<Response: Decodable & Sendable>(_ request: URLRequest, status: Int = 200) async throws -> Response {
        try Task.checkCancellation()
        var message = request; message.timeoutInterval = 30; message.cachePolicy = .reloadIgnoringLocalCacheData
        let (data, response) = try await session.data(for: message)
        guard let response = response as? HTTPURLResponse else { throw ConfigurationJobFailure.invalidResponse }
        guard data.count <= 8 * 1024 * 1024 else { throw ConfigurationJobFailure.responseTooLarge }
        guard response.statusCode == status else { throw ConfigurationJobFailure.httpStatus(response.statusCode, data) }
        do { return try ContractJSON.decoder().decode(Response.self, from: data) }
        catch { throw ConfigurationJobFailure.invalidResponse }
    }
}
