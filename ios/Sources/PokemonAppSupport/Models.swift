import Foundation

/// 应用存储/数据合同错误；诊断保持 ASCII，界面按 case 给出中文说明。
public enum StorageFailure: Error, Sendable {
    case database(String)
    case invalidData(String)
    case checksumMismatch
    case unsupportedSchema
    case missingResource
    case fileOperation(String)
}

/// 六项能力的固定字段，数值由 Core 计算；此类型只保存数据。
public struct StatValues: Codable, Hashable, Sendable {
    public var hp: Int
    public var attack: Int
    public var defense: Int
    public var specialAttack: Int
    public var specialDefense: Int
    public var speed: Int

    /// 六参数分别为 HP/攻击/防御/特攻/特防/速度，完整保存，不应用公式。
    public init(hp: Int, attack: Int, defense: Int, specialAttack: Int, specialDefense: Int, speed: Int) {
        self.hp = hp; self.attack = attack; self.defense = defense
        self.specialAttack = specialAttack; self.specialDefense = specialDefense; self.speed = speed
    }
    /// - Parameter value: 六项均使用的明确常数，例如 IV=31、EV=0。
    public init(repeating value: Int) { self.init(hp: value, attack: value, defense: value, specialAttack: value, specialDefense: value, speed: value) }
}

/// 查询列表中的宝可梦/形态，保留原 identifier 以区分同物种名称的形态。
public struct PokemonSummary: Identifiable, Codable, Hashable, Sendable {
    public let id: Int64
    public let speciesId: Int64
    public let identifier: String
    public let name: String
}

/// 属性知识，只作查询展示与 Core 快照输入。
public struct PokemonType: Identifiable, Codable, Hashable, Sendable {
    public let id: Int64
    public let identifier: String
    public let name: String
}

/// 特性知识；名称存在不表示计算引擎已实现其所有机制。
public struct PokemonAbility: Identifiable, Codable, Hashable, Sendable {
    public let id: Int64
    public let identifier: String
    public let name: String
    public let hidden: Bool
}

/// 完整查询详情；尺寸使用 PokeAPI 原单位，展示层负责单位格式。
public struct PokemonDetails: Sendable {
    public let summary: PokemonSummary
    public let baseStats: StatValues
    public let types: [PokemonType]
    public let abilities: [PokemonAbility]
    public let height: Int
    public let weight: Int
    public let canEvolve: Bool
}

/// 招式分类的知识值与 Core 采用同一固定语义。
public enum MoveCategory: String, Codable, Sendable { case status, physical, special }

/// 招式查询结果，空威力/命中率保留为空，交给 Core 明确判断支持范围。
public struct MoveDetails: Identifiable, Codable, Hashable, Sendable {
    public let id: Int64
    public let identifier: String
    public let name: String
    public let typeId: Int64
    public let power: Int?
    public let pp: Int?
    public let accuracy: Int?
    public let priority: Int
    public let category: MoveCategory
    public let generationId: Int
}

/// 性格改变的能力 ID，由原 CSV 注入 Core，不在 Swift 决定倍率。
public struct NatureDetails: Identifiable, Codable, Hashable, Sendable {
    public let id: Int64
    public let name: String
    public let decreasedStatId: Int
    public let increasedStatId: Int
}

/// 百分制属性相克数据，直接编码为 Core 的知识快照。
public struct TypeEfficacy: Codable, Hashable, Sendable {
    public let attacking: Int64
    public let defending: Int64
    public let percent: Int
}

/// 首装/更新包的全部表行数，匹配 Python manifest 固定 schema。
public struct KnowledgeCounts: Codable, Equatable, Sendable {
    public let pokemon: Int
    public let pokemonStats: Int
    public let pokemonTypes: Int
    public let pokemonAbilities: Int
    public let moves: Int
    public let types: Int
    public let natures: Int
    public let abilities: Int
    public let typeEfficacy: Int
}

/// 构建源摘要，不包含开发机路径或运行凭据。
public struct SourceDigest: Codable, Equatable, Sendable { public let file: String; public let sha256: String }

/// 数据包版本、校验及来源。用户数据库独立，不属于此 manifest。
public struct KnowledgeManifest: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let dataVersion: String
    public let sourceRevision: String
    public let inputSha256: String
    public let sqliteSha256: String
    public let byteSize: Int64
    public let counts: KnowledgeCounts
    public let sources: [SourceDigest]
}

/// 一个待验证的知识包位置，两个 URL 只读借用文件，不取得外部目录的清理权。
public struct KnowledgePack: Sendable {
    public let database: URL
    public let manifest: URL
    /// database/manifest 为调用者准备的完整候选文件，安装时再验证摘要和内容。
    public init(database: URL, manifest: URL) { self.database = database; self.manifest = manifest }
    /// 返回随 App/Swift Package 一起交付的真实首装资源；缺失即失败，不创建空库。
    public static func bundled() throws -> KnowledgePack {
        guard let database = Bundle.module.url(forResource: "knowledge", withExtension: "sqlite"),
              let manifest = Bundle.module.url(forResource: "manifest", withExtension: "json") else { throw StorageFailure.missingResource }
        return KnowledgePack(database: database, manifest: manifest)
    }
}

/// 固定蛇形 JSON 编解码入口，仅转换字段名，不做业务计算或宽松字段回退。
enum ContractJSON {
    /// 创建独立 decoder，无共享可变状态。
    static func decoder() -> JSONDecoder { let value = JSONDecoder(); value.keyDecodingStrategy = .convertFromSnakeCase; return value }
    /// 创建独立 encoder，稳定排序有助于保存输入和对比计算结果。
    static func encoder() -> JSONEncoder { let value = JSONEncoder(); value.keyEncodingStrategy = .convertToSnakeCase; value.outputFormatting = [.sortedKeys]; return value }
}
