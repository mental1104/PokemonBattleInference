import Foundation
import PokemonCore
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// 计算传输/版本错误；原生规则错误仍保留 NativeFailure，不用默认结果伪装成功。
public enum CalculationFailure: Error, Sendable { case invalidKnowledge, invalidResponse, engineVersionMismatch, httpStatus(Int) }

/// 概率的原生精确表示，展示不反向参与计算。
public struct ExactProbability: Codable, Hashable, Sendable {
    public let numerator: String
    public let denominator: String
    /// 保留任意长度整数的分数显示，不转成 Double 后再作为输入。
    public var text: String { denominator == "1" ? numerator : "\(numerator)/\(denominator)" }
}
/// 原生完整修正轨迹，保留阶段、来源与随机倍率空值。
public struct AppliedModifier: Codable, Hashable, Sendable {
    public let key: String
    public let stage: String
    public let source: String
    public let reason: String
    public let multiplier: Double?
    public let minMultiplier: Double?
    public let maxMultiplier: Double?
}
/// 直接伤害结果完全来自 Core；min/max 仅用于展示已有档位，不生成新的伤害规则。
public struct DamageCalculation: Codable, Hashable, Sendable {
    public let kind: String
    public let damageRulesetId: String
    public let rolls: [Int64]
    public let defenderHp: Int64
    public let baseDamage: Int64
    public let trace: [AppliedModifier]
    public let ohko: ExactProbability
    public let twoHit: ExactProbability
    public let guaranteedOhko: Bool
    public let guaranteedTwoHit: Bool
}
/// 一次已完成计算的全部版本/能力/速度与可重放输入输出，不存成不带版本的浮点摘要。
public struct CalculationResult: Sendable {
    public let attackerStats: StatValues
    public let defenderStats: StatValues
    public let attackerSpeed: Int64
    public let defenderSpeed: Int64
    public let damage: DamageCalculation
    public let engineVersion: String
    public let rulesVersion: String
    public let knowledgeVersion: String
    public let request: Data
    public let response: Data
}

/// 计算只编排知识快照与 C ABI；在线/离线发送相同操作，Swift 不实现能力/伤害/概率公式。
public actor CalculationService {
    private let knowledge: KnowledgeStore
    /// knowledge 为独立只读知识 actor，不取得用户数据库或生产服务的修改权。
    public init(knowledge: KnowledgeStore) { self.knowledge = knowledge }

    /// configuration 为完整用户输入；server 为 null 使用本机 Core，否则调用用户指定服务。
    /// 返回全部实际结果；重计算通过 Engine.calculateAsync 离开主线程，任务取消自然传播。
    public func calculate(_ configuration: BattleConfiguration, server: URL? = nil) async throws -> CalculationResult {
        // 一次 actor 调用取得全部输入；等待远端 profile 时即使更新知识包，也不能混用不同版本。
        let snapshot = try await knowledge.calculationSnapshot(attackerId: configuration.attacker.pokemonId,
            defenderId: configuration.defender.pokemonId, moveId: configuration.moveId)
        let first = snapshot.attacker, second = snapshot.defender, move = snapshot.move
        let profiles = try [Self.profile(configuration.attacker, pokemon: first, natures: snapshot.natures), Self.profile(configuration.defender, pokemon: second, natures: snapshot.natures)]
        let profileRequest = try ContractJSON.encoder().encode(Batch(operations: profiles))
        let profileData = try await call(profileRequest, server: server)
        let profileReply = try ContractJSON.decoder().decode(Reply<ProfileResult>.self, from: profileData)
        try validate(profileReply.schemaVersion, profileReply.engineVersion)
        guard profileReply.results.count == 2, profileReply.results.allSatisfy({ $0.kind == "profile" }) else { throw CalculationFailure.invalidResponse }
        let firstStats = profileReply.results[0].stats, secondStats = profileReply.results[1].stats
        let input = DamageInput(generationId: configuration.generationId,
            attacker: PokemonInput(configuration: configuration.attacker, pokemon: first, stats: firstStats),
            defender: PokemonInput(configuration: configuration.defender, pokemon: second, stats: secondStats),
            move: MoveInput(type: move.typeId, category: move.category, power: move.power ?? 0), typeChart: snapshot.typeChart,
            weather: configuration.weather, terrain: configuration.terrain, critical: configuration.critical)
        let finalRequest = try ContractJSON.encoder().encode(Batch(operations: [FinalOperation.damage(input),
            .status(StatusInput(configuration: configuration.attacker, stats: firstStats, generation: configuration.generationId)),
            .status(StatusInput(configuration: configuration.defender, stats: secondStats, generation: configuration.generationId))]))
        let finalData = try await call(finalRequest, server: server)
        let result = try ContractJSON.decoder().decode(Reply<FinalResult>.self, from: finalData)
        try validate(result.schemaVersion, result.engineVersion)
        guard result.rulesVersion == profileReply.rulesVersion, result.results.count == 3,
              case .damage(let damage) = result.results[0], case .status(let firstSpeed) = result.results[1], case .status(let secondSpeed) = result.results[2] else { throw CalculationFailure.invalidResponse }
        let version = snapshot.version
        let archive = ArchivedInput(configuration: configuration, knowledgeVersion: version.dataVersion, profileRequest: profileRequest, finalRequest: finalRequest)
        return CalculationResult(attackerStats: firstStats, defenderStats: secondStats, attackerSpeed: firstSpeed.speed, defenderSpeed: secondSpeed.speed,
            damage: damage, engineVersion: result.engineVersion, rulesVersion: result.rulesVersion, knowledgeVersion: version.dataVersion,
            request: try ContractJSON.encoder().encode(archive), response: finalData)
    }

    /// request 为完整 ABI Data；server 可空，网络错误/取消不回退成另一个计算来源。
    private func call(_ request: Data, server: URL?) async throws -> Data {
        guard let server else { return try await Engine.calculateAsync(request) }
        var message = URLRequest(url: server.appendingPathComponent("v1/core/calculate"))
        message.httpMethod = "POST"; message.httpBody = request; message.timeoutInterval = 60
        message.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await URLSession.shared.data(for: message)
        guard let response = response as? HTTPURLResponse else { throw CalculationFailure.invalidResponse }
        guard response.statusCode == 200 else { throw CalculationFailure.httpStatus(response.statusCode) }
        return data
    }
    /// schema/engine 来自实际响应，未知版本拒绝而不是继续展示成当前引擎结果。
    private func validate(_ schema: Int, _ engine: String) throws {
        guard schema == 1 else { throw CalculationFailure.invalidResponse }
        guard engine == Engine.version else { throw CalculationFailure.engineVersionMismatch }
    }
    /// 配置/知识/性格仅转换成原生 profile 输入，不在 Swift 选择性格倍率。
    private static func profile(_ configuration: PokemonConfiguration, pokemon: PokemonDetails, natures: [NatureDetails]) throws -> ProfileInput {
        guard let nature = natures.first(where: { $0.id == configuration.natureId }) else { throw CalculationFailure.invalidKnowledge }
        return ProfileInput(base: pokemon.baseStats, ivs: configuration.ivs, evs: configuration.evs, level: configuration.level,
            decreasedStatId: nature.decreasedStatId, increasedStatId: nature.increasedStatId)
    }
}

/// 以下固定协议模型只在应用边界编码/解码，不进入 UI 也不计算规则。
private struct Batch<Operation: Encodable>: Encodable { let schemaVersion = 1; let operations: [Operation] }
private struct Reply<Result: Decodable>: Decodable { let schemaVersion: Int; let engineVersion: String; let rulesVersion: String; let results: [Result] }
private struct ProfileInput: Encodable { let kind = "profile"; let base: StatValues; let ivs: StatValues; let evs: StatValues; let level: Int; let decreasedStatId: Int; let increasedStatId: Int }
private struct ProfileResult: Decodable { let kind: String; let stats: StatValues }
private struct MoveInput: Encodable { let type: Int64; let category: MoveCategory; let power: Int }
private struct PokemonInput: Encodable {
    let level: Int; let types: [Int64]; let stats: StatValues; let ability: AbilityRule; let item: ItemRule; let canEvolve: Bool
    /// 参数均为已选择的知识/配置值，只进行字段投影。
    init(configuration: PokemonConfiguration, pokemon: PokemonDetails, stats: StatValues) {
        level = configuration.level; types = pokemon.types.map(\.id); self.stats = stats; ability = configuration.ability; item = configuration.item; canEvolve = pokemon.canEvolve
    }
}
private struct DamageInput: Encodable {
    let kind = "damage"
    // 离线编辑器没有动态战斗状态；明确使用原静态上下文，在线与离线发送同一个请求。
    let context = "reference_static"
    let generationId: Int; let attacker: PokemonInput; let defender: PokemonInput; let move: MoveInput
    let typeChart: [TypeEfficacy]; let weather: WeatherRule; let terrain: TerrainRule; let critical: Bool
}
private struct MajorStatusInput: Encodable { let kind = "paralysis" }
private struct StatusSnapshotInput: Encodable {
    let major: MajorStatusInput?
    let volatile: [String] = []
    enum CodingKeys: String, CodingKey { case major, volatile }
    /// 必须显式编码 null major；空数组永远不携带未实现的临时状态。
    func encode(to encoder: Encoder) throws { var value = encoder.container(keyedBy: CodingKeys.self); try value.encode(major, forKey: .major); try value.encode(volatile, forKey: .volatile) }
}
private struct StatusInput: Encodable {
    let kind = "status_modifiers"; let status: StatusSnapshotInput; let speed: Int; let generationId: Int
    let category = "physical"; let baseMultiplier = FractionInput(numerator: "1", denominator: "1"); let burnMultiplier = FractionInput(numerator: "1", denominator: "2")
    /// 麻痹只由显式配置输入决定，速度变化由 Core 根据 generation 执行。
    init(configuration: PokemonConfiguration, stats: StatValues, generation: Int) { status = StatusSnapshotInput(major: configuration.paralyzed ? MajorStatusInput() : nil); speed = stats.speed; generationId = generation }
}
private struct FractionInput: Encodable { let numerator: String; let denominator: String }
private enum FinalOperation: Encodable {
    case damage(DamageInput), status(StatusInput)
    /// 将具体固定对象编码到同一 operations 数组，不构造无类型 JSON 字典。
    func encode(to encoder: Encoder) throws { switch self { case .damage(let value): try value.encode(to: encoder); case .status(let value): try value.encode(to: encoder) } }
}
private struct SpeedResult: Decodable { let speed: Int64 }
private enum FinalResult: Decodable {
    case damage(DamageCalculation), status(SpeedResult)
    enum CodingKeys: String, CodingKey { case kind }
    /// 按实际 kind 解码为已知固定结果，未知类型明确失败。
    init(from decoder: Decoder) throws {
        let value = try decoder.container(keyedBy: CodingKeys.self)
        switch try value.decode(String.self, forKey: .kind) {
        case "damage": self = .damage(try DamageCalculation(from: decoder))
        case "status_modifiers": self = .status(try SpeedResult(from: decoder))
        default: throw CalculationFailure.invalidResponse
        }
    }
}
private struct ArchivedInput: Encodable { let configuration: BattleConfiguration; let knowledgeVersion: String; let profileRequest: Data; let finalRequest: Data }
