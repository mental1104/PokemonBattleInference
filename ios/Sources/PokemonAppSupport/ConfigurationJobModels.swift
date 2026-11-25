import Foundation

/// 原 configuration-jobs 的固定八维合同；Swift 只编码命令，不枚举配置或执行准入算法。
public struct JobDimensions: Encodable, Equatable, Sendable {
    public let pokemon = "fixed"
    public let form = "fixed"
    public let level = "fixed"
    public let stats = "fixed"
    public let ability = "fixed"
    public let item = "fixed"
    public let moves = "candidate_pool"
    public let specialMechanics = "disabled"
    /// 只能构造原 v1 固定维度，不能通过 UI 宣称实现未支持维度。
    public init() { }
}

/// 一侧原 HTTP 固定配置；statProfileId 引用原公开 preset，不能替换成离线编辑器的任意 IV/EV。
public struct JobFixedPokemon: Encodable, Equatable, Sendable {
    public var pokemonId: Int64
    public var formId: Int64?
    public var level: Int
    public var statProfileId: String
    public var abilityIdentifier: String
    public var itemIdentifier: String?
    /// pokemonId/formId 为知识编号，level 为1…100，statProfileId 是服务公开配置键。
    /// abilityIdentifier/itemIdentifier 使用原 PokeAPI hyphen 标识，nil 道具/形态显式编码为 null。
    public init(pokemonId: Int64, formId: Int64? = nil, level: Int = 50, statProfileId: String,
                abilityIdentifier: String, itemIdentifier: String? = nil) {
        self.pokemonId = pokemonId; self.formId = formId; self.level = level; self.statProfileId = statProfileId
        self.abilityIdentifier = abilityIdentifier; self.itemIdentifier = itemIdentifier
    }
    private enum CodingKeys: String, CodingKey { case pokemonId, formId, level, statProfileId, abilityIdentifier, itemIdentifier }
    /// encoder 接收完整 HTTP 对象；保留 null 不会把缺失值改写成字符串 none。
    public func encode(to encoder: Encoder) throws {
        var value = encoder.container(keyedBy: CodingKeys.self)
        try value.encode(pokemonId, forKey: .pokemonId); try value.encode(formId, forKey: .formId)
        try value.encode(level, forKey: .level); try value.encode(statProfileId, forKey: .statProfileId)
        try value.encode(abilityIdentifier, forKey: .abilityIdentifier); try value.encode(itemIdentifier, forKey: .itemIdentifier)
    }
}

/// 固定配置与候选招式输入，排序/去重/预算/版本准入完全由正式服务和 Core 执行。
public struct JobMovePool: Encodable, Equatable, Sendable {
    public var fixed: JobFixedPokemon
    public var candidateMoveIds: [Int64]
    /// fixed 为完整一侧配置；candidateMoveIds 为原合同1…10项候选知识ID，保持用户原输入。
    public init(fixed: JobFixedPokemon, candidateMoveIds: [Int64]) { self.fixed = fixed; self.candidateMoveIds = candidateMoveIds }
}

/// 原 HTTP 明确动作策略，不在 Swift 选择行动或实现策略概率。
public enum JobActionPolicy: String, Codable, CaseIterable, Sendable { case firstLegalAction = "first-legal-action", uniformRandom = "uniform-random" }

/// 服务冻结的进程/队列/单case图预算；maxTurns=nil 明确表示不限回合。
public struct JobExecutionBudget: Encodable, Equatable, Sendable {
    public var processCount: Int
    public var queueDepth: Int
    public var maxNodesPerPair: Int
    public var maxEdgesPerPair: Int
    public var maxTurns: Int?
    /// 参数分别为进程1…8、队列1…32、图节点/边上限与回合1…10000/null；最终准入由服务执行。
    public init(processCount: Int = 2, queueDepth: Int = 4, maxNodesPerPair: Int = 20_000, maxEdgesPerPair: Int = 80_000, maxTurns: Int? = 100) {
        self.processCount = processCount; self.queueDepth = queueDepth; self.maxNodesPerPair = maxNodesPerPair
        self.maxEdgesPerPair = maxEdgesPerPair; self.maxTurns = maxTurns
    }
    private enum CodingKeys: String, CodingKey { case processCount, queueDepth, maxNodesPerPair, maxEdgesPerPair, maxTurns }
    /// encoder 保存所有冻结预算字段，nil maxTurns 保留为 JSON null。
    public func encode(to encoder: Encoder) throws {
        var value = encoder.container(keyedBy: CodingKeys.self)
        try value.encode(processCount, forKey: .processCount); try value.encode(queueDepth, forKey: .queueDepth)
        try value.encode(maxNodesPerPair, forKey: .maxNodesPerPair); try value.encode(maxEdgesPerPair, forKey: .maxEdgesPerPair)
        try value.encode(maxTurns, forKey: .maxTurns)
    }
}

/// 原 POST configuration-jobs 命令，无 Core operations/JSON 演示接口或 Swift 战斗公式。
public struct ConfigurationJobCommand: Encodable, Equatable, Sendable {
    public let contractVersion = "one-on-one-move-pool.v1"
    public let dimensions = JobDimensions()
    public let weightAssumption = "uniform_configuration_pair"
    public let mechanismAdmission = "supported_only"
    public var rulesetId: String
    public var versionGroupId: Int
    public var calculationRevision: String
    public var attackerPolicy: JobActionPolicy
    public var defenderPolicy: JobActionPolicy
    public var attacker: JobMovePool
    public var defender: JobMovePool
    public var execution: JobExecutionBudget
    /// attacker/defender 是完整候选池；规则集/版本组/修订与策略/预算原样发送，不替换成当前本机引擎版本。
    public init(attacker: JobMovePool, defender: JobMovePool, rulesetId: String = "pokemon-champion", versionGroupId: Int = 25,
                calculationRevision: String = "battle-inference.summary-exploration.v2", attackerPolicy: JobActionPolicy = .firstLegalAction,
                defenderPolicy: JobActionPolicy = .firstLegalAction, execution: JobExecutionBudget = JobExecutionBudget()) {
        self.attacker = attacker; self.defender = defender; self.rulesetId = rulesetId; self.versionGroupId = versionGroupId
        self.calculationRevision = calculationRevision; self.attackerPolicy = attackerPolicy; self.defenderPolicy = defenderPolicy; self.execution = execution
    }
}

/// 创建响应只承认 pending 确认，不把 HTTP202 当作完成计算。
public struct ConfigurationJobCreated: Decodable, Sendable {
    public let jobId: String
    public let status: String
    public let submittedConfigurationPairs: Int
    public let createdAt: String
}

/// 原轮询 API 的粗粒度状态；与通用 jobs 的 pending/preparing/succeeded 等细状态不同。
public enum ConfigurationJobPhase: String, Decodable, Sendable {
    case queued, running, completed, partial, cancelled, failed
    /// 终态只由服务报告，取消请求已发送不等于已经终止。
    public var terminal: Bool { switch self { case .queued, .running: false; default: true } }
}

/// 实际持久化计数桶，没有根据时间模拟进度。
public struct ConfigurationJobCounts: Decodable, Sendable {
    public let total: Int
    public let completed: Int
    public let succeeded: Int
    public let failed: Int
    public let truncated: Int
    public let running: Int
    public let pending: Int
    public let cancelled: Int
}

/// 服务实际记录的资源数及冻结上限。
public struct ConfigurationJobResource: Decodable, Sendable { public let used: Int64; public let limit: Int64 }

/// 原完整任务状态，保留规则轴、时间与 nullable 诊断，不猜测服务端时区或修订。
public struct ConfigurationJobStatus: Decodable, Sendable {
    public let jobId: String
    public let status: ConfigurationJobPhase
    public let cancellationRequested: Bool
    public let counts: ConfigurationJobCounts
    public let stateNodes: ConfigurationJobResource
    public let stateEdges: ConfigurationJobResource
    public let rulesetId: String
    public let versionGroupId: Int
    public let calculationRevision: String
    public let weightAssumption: String
    public let attackerPolicy: JobActionPolicy
    public let defenderPolicy: JobActionPolicy
    public let lastFailureCode: String?
    public let lastFailureDiagnostic: String?
    public let createdAt: String
    public let updatedAt: String
    public let completedAt: String?
}

/// 原case生命周期；失败/截断/取消不能伪装成概率为零的成功结果。
public enum ConfigurationCasePhase: String, Decodable, Sendable { case pending, running, succeeded, failed, truncated, cancelled }
/// 原期望回合种类，保留有限/无限/不可用三种语义。
public enum JobExpectedTurnsKind: String, Decodable, Sendable { case finite, infinite, unavailable }

/// 精确分子分母保持任意长度字符串；decimal 只供展示，不反向进入计算。
public struct JobProbability: Decodable, Sendable {
    public let numerator: String
    public let denominator: String
    public let decimal: Double
    /// 返回原生精确分数，不能经 Double 重建分子或分母。
    public var text: String { denominator == "1" ? numerator : "\(numerator)/\(denominator)" }
}

/// 原 explanation 明确允许任意 JSON 对象；只有这一边界字段使用递归 JSON 值，业务字段始终强类型。
public enum JobExplanationValue: Codable, Equatable, Sendable {
    case object([String: JobExplanationValue]), array([JobExplanationValue]), string(String), number(Decimal), bool(Bool), null
    /// decoder 读取一个外部 explanation 值；不将它当作命令或动态业务对象执行。
    public init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer()
        if value.decodeNil() { self = .null }
        else if let item = try? value.decode(Bool.self) { self = .bool(item) }
        else if let item = try? value.decode(String.self) { self = .string(item) }
        else if let item = try? value.decode(Decimal.self) { self = .number(item) }
        else if let item = try? value.decode([String: JobExplanationValue].self) { self = .object(item) }
        else { self = .array(try value.decode([JobExplanationValue].self)) }
    }
    /// encoder 仅用于原样展示/归档 explanation，不推导业务概率。
    public func encode(to encoder: Encoder) throws {
        var value = encoder.singleValueContainer()
        switch self {
        case .object(let item): try value.encode(item)
        case .array(let item): try value.encode(item)
        case .string(let item): try value.encode(item)
        case .number(let item): try value.encode(item)
        case .bool(let item): try value.encode(item)
        case .null: try value.encodeNil()
        }
    }
}

/// 单个配置对的完整摘要；configurationId/招式/精确结果全部来自服务，Swift 不重建 canonical 身份。
public struct ConfigurationJobCase: Decodable, Identifiable, Sendable {
    public var id: String { configurationId }
    public let configurationId: String
    public let sequenceNo: Int
    public let status: ConfigurationCasePhase
    public let attackerPokemonId: Int64
    public let defenderPokemonId: Int64
    public let attackerMoveIds: [Int64]
    public let defenderMoveIds: [Int64]
    public let attackerWinProbability: JobProbability?
    public let defenderWinProbability: JobProbability?
    public let drawProbability: JobProbability?
    public let expectedTurnsKind: JobExpectedTurnsKind?
    public let expectedTurns: String?
    public let nodeCount: Int64
    public let edgeCount: Int64
    public let explanation: [String: JobExplanationValue]?
    public let failureCode: String?
    public let diagnostic: String?
    public let attemptCount: Int
}

/// 稳定序号分页；nullable nextCursor 原样保留，不把失败条目丢出结果列表。
public struct ConfigurationJobPage: Decodable, Sendable {
    public let jobId: String
    public let offset: Int
    public let limit: Int
    public let total: Int
    public let nextCursor: String?
    public let items: [ConfigurationJobCase]
}

/// 取消确认只说明服务接受请求，必须继续轮询 actual status 才能确认终态。
public struct ConfigurationJobCancellation: Decodable, Sendable {
    public let jobId: String
    public let cancellationRequested: Bool
    public let status: ConfigurationJobPhase
}
