import Foundation

/// 与旧结果解释分离的实际运行来源；版本可同时未知，输入摘要始终来自最终子进程请求字节。
public struct ConfigurationJobExecutionMetadata: Decodable, Sendable, Equatable {
    public let schemaVersion: Int
    public let engineVersion: String?
    public let rulesVersion: String?
    public let inputSha256: String
    public let inputSchemaVersion: Int
    public let operation: String
    public let observer: String
}

/// 独立 GET 接口信封；显式 null 代表该 case 无旧溯源，缺字段或未知 schema 不是合法旧记录。
struct ConfigurationJobMetadataEnvelope: Decodable, Sendable {
    let schemaVersion: Int
    let metadata: ConfigurationJobExecutionMetadata?
    /// 键使用 ContractJSON 的 snake_case 转换结果；不将缩写 SHA256 误映射为丢失字段。
    private enum CodingKeys: String, CodingKey { case schemaVersion, metadata }
    /// decoder 为正式 HTTP JSON 解码器；返回已验证信封，不接受部分版本或无效输入摘要。
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try values.decode(Int.self, forKey: .schemaVersion)
        guard schemaVersion == 1, values.contains(.metadata) else { throw ConfigurationJobFailure.invalidResponse }
        metadata = try values.decodeIfPresent(ConfigurationJobExecutionMetadata.self, forKey: .metadata)
        if let metadata {
            guard metadata.schemaVersion == 1, metadata.inputSchemaVersion == 1,
                  metadata.inputSha256.utf8.count == 64,
                  metadata.inputSha256.utf8.allSatisfy({ (48...57).contains($0) || (97...102).contains($0) }),
                  !metadata.operation.isEmpty, metadata.operation == metadata.operation.trimmingCharacters(in: .whitespacesAndNewlines),
                  ["attacker", "defender"].contains(metadata.observer),
                  (metadata.engineVersion == nil) == (metadata.rulesVersion == nil) else { throw ConfigurationJobFailure.invalidResponse }
            for version in [metadata.engineVersion, metadata.rulesVersion].compactMap({ $0 }) {
                guard !version.isEmpty, version == version.trimmingCharacters(in: .whitespacesAndNewlines) else { throw ConfigurationJobFailure.invalidResponse }
            }
        }
    }
}
