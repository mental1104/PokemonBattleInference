/// 一次计算所需的完整不可变知识投影；所有字段和 manifest 来自同一已安装 SQLite 版本。
/// 调用方拥有这些值，后续知识包切换不会改变已开始计算的输入或归档版本。
public struct CalculationKnowledgeSnapshot: Sendable {
    public let attacker: PokemonDetails
    public let defender: PokemonDetails
    public let move: MoveDetails
    public let natures: [NatureDetails]
    public let typeChart: [TypeEfficacy]
    public let version: KnowledgeManifest
}
