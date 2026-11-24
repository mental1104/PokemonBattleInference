import Foundation

/// 已明确支持的直接伤害特性标识，未提供的完整机制不伪装为 none。
public enum AbilityRule: String, Codable, CaseIterable, Sendable { case none, technician, adaptability, thickFat = "thick_fat", filter, solidRock = "solid_rock", sniper }
/// 直接伤害携带道具合同。
public enum ItemRule: String, Codable, CaseIterable, Sendable { case none, lifeOrb = "life_orb", choiceBand = "choice_band", choiceSpecs = "choice_specs", expertBelt = "expert_belt", eviolite }
/// 天气只保存明确选择，效果由 Core 执行。
public enum WeatherRule: String, Codable, CaseIterable, Sendable { case none, harshSunlight = "harsh_sunlight", rain, sandstorm, hail, snow }
/// 场地只保存明确选择，接地规则由 Core 执行。
public enum TerrainRule: String, Codable, CaseIterable, Sendable { case none, electric = "electric_terrain", psychic = "psychic_terrain", grassy = "grassy_terrain", misty = "misty_terrain" }

/// 单只宝可梦的用户配置；无种族值或规则公式副本，知识由当前离线库提供。
public struct PokemonConfiguration: Codable, Hashable, Sendable {
    public var pokemonId: Int64
    public var level: Int
    public var ivs: StatValues
    public var evs: StatValues
    public var natureId: Int64
    public var ability: AbilityRule
    public var item: ItemRule
    public var paralyzed: Bool
    /// pokemonId 为知识 ID，其余均为用户明确设置的参数；不在构造中计算能力。
    public init(pokemonId: Int64, level: Int = 50, ivs: StatValues = StatValues(repeating: 31), evs: StatValues = StatValues(repeating: 0),
                natureId: Int64 = 1, ability: AbilityRule = .none, item: ItemRule = .none, paralyzed: Bool = false) {
        self.pokemonId = pokemonId; self.level = level; self.ivs = ivs; self.evs = evs; self.natureId = natureId
        self.ability = ability; self.item = item; self.paralyzed = paralyzed
    }
}

/// 可保存与同步的稳定 ID 配置；删除使用同一 ID 的 tombstone，不创建影子记录。
public struct BattleConfiguration: Identifiable, Codable, Hashable, Sendable {
    public var id: UUID
    public var name: String
    public var attacker: PokemonConfiguration
    public var defender: PokemonConfiguration
    public var moveId: Int64
    public var generationId: Int
    public var weather: WeatherRule
    public var terrain: TerrainRule
    public var critical: Bool
    /// 保存完整用户输入，所有战斗规则计算由调用 Core 的服务承担。
    public init(id: UUID = UUID(), name: String, attacker: PokemonConfiguration, defender: PokemonConfiguration, moveId: Int64,
                generationId: Int = 9, weather: WeatherRule = .none, terrain: TerrainRule = .none, critical: Bool = false) {
        self.id = id; self.name = name; self.attacker = attacker; self.defender = defender; self.moveId = moveId
        self.generationId = generationId; self.weather = weather; self.terrain = terrain; self.critical = critical
    }
    /// 首装即能计算的固定示例，与共享 99…117 / 123/128 向量一致，不把预期值写入计算结果。
    public static func example() -> BattleConfiguration {
        BattleConfiguration(name: "巨钳螳螂 · 子弹拳",
            attacker: PokemonConfiguration(pokemonId: 212, evs: StatValues(hp: 252, attack: 252, defense: 0, specialAttack: 0, specialDefense: 0, speed: 0)),
            defender: PokemonConfiguration(pokemonId: 700, evs: StatValues(hp: 252, attack: 0, defense: 0, specialAttack: 252, specialDefense: 0, speed: 0)), moveId: 418)
    }
}

/// 已持久化记录，服务端 revision 与本地编辑序号独立；时间戳不参与冲突判断。
public struct StoredConfiguration: Identifiable, Codable, Sendable {
    public var id: UUID { configuration.id }
    public let configuration: BattleConfiguration
    public let serverRevision: Int64
    public let localSequence: Int64
    public let deleted: Bool
    public let knowledgeVersion: String
    public let engineVersion: String
}
/// 明确的离线变更种类，后续同步按 operationId 幂等提交。
public enum ConfigurationChangeKind: String, Codable, Sendable { case upsert, delete }
/// 与配置写入同事务保存的完整变更；operationId 与首次发送后冻结的内容一起重试。
public struct PendingConfigurationChange: Identifiable, Codable, Sendable {
    public var id: UUID { operationId }
    public let operationId: UUID
    public let entityId: UUID
    public let baseRevision: Int64
    public let localSequence: Int64
    public let kind: ConfigurationChangeKind
    public let configuration: BattleConfiguration
    public let knowledgeVersion: String
    public let engineVersion: String
}

/// 独立的用户 SQLite actor；知识包安装/切换永远不打开或覆盖本库。
public actor ConfigurationStore {
    private let connection: SQLiteConnection
    /// url 为本 App 用户库文件；未知新 schema 明确失败，禁止自动 reset。
    public init(url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let database = try SQLiteConnection(url: url, readOnly: false)
        let versions = try database.rows("PRAGMA user_version", decode: { try $0.integer(0) })
        guard let version = versions.first, (0...2).contains(version) else { throw StorageFailure.unsupportedSchema }
        if version == 0 {
            try database.transaction {
                try database.execute("CREATE TABLE configurations (id TEXT PRIMARY KEY,name TEXT NOT NULL,payload BLOB NOT NULL,server_revision INTEGER NOT NULL,local_sequence INTEGER NOT NULL,deleted INTEGER NOT NULL,knowledge_version TEXT NOT NULL,engine_version TEXT NOT NULL,updated_at INTEGER NOT NULL)")
                try database.execute("CREATE TABLE pending_changes (operation_id TEXT PRIMARY KEY,entity_id TEXT NOT NULL REFERENCES configurations(id),base_revision INTEGER NOT NULL,local_sequence INTEGER NOT NULL,kind TEXT NOT NULL,payload BLOB NOT NULL)")
                try database.execute("CREATE TABLE settings (key TEXT PRIMARY KEY,value BLOB NOT NULL)")
                try database.execute("CREATE TABLE calculations (id TEXT PRIMARY KEY,configuration_id TEXT NOT NULL,request BLOB NOT NULL,response BLOB NOT NULL,engine_version TEXT NOT NULL,rules_version TEXT NOT NULL,knowledge_version TEXT NOT NULL,created_at INTEGER NOT NULL)")
                try database.execute("PRAGMA user_version=1")
            }
        }
        if version < 2 {
            // 老队列尚未发送，安全回填当时可取得的元信息；不丢弃已有配置、计算或变更。
            try database.transaction {
                try database.execute("ALTER TABLE pending_changes ADD COLUMN knowledge_version TEXT NOT NULL DEFAULT ''")
                try database.execute("ALTER TABLE pending_changes ADD COLUMN engine_version TEXT NOT NULL DEFAULT ''")
                try database.execute("ALTER TABLE pending_changes ADD COLUMN sent INTEGER NOT NULL DEFAULT 0")
                try database.execute("UPDATE pending_changes SET knowledge_version=(SELECT knowledge_version FROM configurations WHERE configurations.id=entity_id),engine_version=(SELECT engine_version FROM configurations WHERE configurations.id=entity_id)")
                try database.execute("CREATE TABLE sync_conflicts (id TEXT PRIMARY KEY,entity_id TEXT NOT NULL,local BLOB NOT NULL,remote BLOB NOT NULL,resolved INTEGER NOT NULL DEFAULT 0)")
                try database.execute("CREATE UNIQUE INDEX sync_active_conflict ON sync_conflicts(entity_id) WHERE resolved=0")
                try database.execute("PRAGMA user_version=2")
            }
        }
        connection = database
    }
    /// 返回未删除的完整配置；本地 tombstone 和待同步队列保留在库内。
    public func all() throws -> [StoredConfiguration] {
        try connection.rows(Self.select + " WHERE deleted=0 ORDER BY updated_at DESC,id", decode: Self.decode)
    }
    /// configuration 为完整编辑值；与队列追加同事务，重复保存相同值不增加 revision/重复变更。
    @discardableResult public func save(_ configuration: BattleConfiguration, knowledgeVersion: String, engineVersion: String) throws -> StoredConfiguration {
        guard !configuration.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw StorageFailure.invalidData("configuration name must not be empty") }
        return try connection.transaction {
            let current = try self.find(configuration.id)
            if let current, !current.deleted, current.configuration == configuration, current.knowledgeVersion == knowledgeVersion, current.engineVersion == engineVersion { return current }
            guard (current?.localSequence ?? 0) < Int64.max else { throw StorageFailure.invalidData("local sequence exceeds int64 range") }
            let record = StoredConfiguration(configuration: configuration, serverRevision: current?.serverRevision ?? 0,
                localSequence: (current?.localSequence ?? 0) + 1, deleted: false, knowledgeVersion: knowledgeVersion, engineVersion: engineVersion)
            try self.write(record, kind: .upsert)
            return record
        }
    }
    /// id 为已保存稳定 ID；重复删除幂等，第一次删除保留完整原内容和 tombstone 队列。
    public func delete(_ id: UUID) throws {
        try connection.transaction {
            guard let current = try self.find(id), !current.deleted else { return }
            guard current.localSequence < Int64.max else { throw StorageFailure.invalidData("local sequence exceeds int64 range") }
            try self.write(StoredConfiguration(configuration: current.configuration, serverRevision: current.serverRevision,
                localSequence: current.localSequence + 1, deleted: true, knowledgeVersion: current.knowledgeVersion, engineVersion: current.engineVersion), kind: .delete)
        }
    }
    /// 返回持久化待同步变更，按实际插入顺序；不把未发送记录误标为已同步。
    public func pendingChanges() throws -> [PendingConfigurationChange] {
        try connection.rows("SELECT operation_id,entity_id,base_revision,local_sequence,kind,payload,knowledge_version,engine_version FROM pending_changes ORDER BY rowid") { row in
            guard let operation = UUID(uuidString: try row.text(0)), let entity = UUID(uuidString: try row.text(1)), let kind = ConfigurationChangeKind(rawValue: try row.text(4)) else { throw StorageFailure.invalidData("invalid pending change identity") }
            return PendingConfigurationChange(operationId: operation, entityId: entity, baseRevision: try row.integer(2), localSequence: try row.integer(3), kind: kind,
                configuration: try ContractJSON.decoder().decode(BattleConfiguration.self, from: row.data(5)), knowledgeVersion: try row.text(6), engineVersion: try row.text(7))
        }
    }
    /// url 为用户选定的 HTTP(S) 服务根地址/null；凭据不嵌入 URL 保存。
    public func setServerURL(_ url: URL?) throws {
        if let url { guard ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil, url.user == nil, url.password == nil else { throw StorageFailure.invalidData("invalid server URL") } }
        try connection.execute("INSERT INTO settings VALUES ('server_url',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [.blob(try ContractJSON.encoder().encode(url))])
    }
    /// 返回用户实际保存的服务地址；未配置时为 null，不猜测生产域名。
    public func serverURL() throws -> URL? {
        guard let data = try connection.rows("SELECT value FROM settings WHERE key='server_url'", decode: { try $0.data(0) }).first else { return nil }
        return try ContractJSON.decoder().decode(URL?.self, from: data)
    }
    /// 保存实际计算输入/输出和全部版本；不使用展示小数重建计算输入。
    public func saveCalculation(configurationId: UUID, request: Data, response: Data, engineVersion: String, rulesVersion: String, knowledgeVersion: String) throws {
        try connection.execute("INSERT INTO calculations VALUES (?,?,?,?,?,?,?,?)", [.text(UUID().uuidString.lowercased()), .text(configurationId.uuidString.lowercased()),
            .blob(request), .blob(response), .text(engineVersion), .text(rulesVersion), .text(knowledgeVersion), .integer(Int64(Date().timeIntervalSince1970 * 1000))])
    }
    private static let select = "SELECT payload,server_revision,local_sequence,deleted,knowledge_version,engine_version FROM configurations"
    /// row 为当前固定 SELECT 的只读结果；返回独立完整记录。
    private static func decode(_ row: SQLiteStatement) throws -> StoredConfiguration {
        StoredConfiguration(configuration: try ContractJSON.decoder().decode(BattleConfiguration.self, from: row.data(0)),
            serverRevision: try row.integer(1), localSequence: try row.integer(2), deleted: try row.integer(3) == 1,
            knowledgeVersion: try row.text(4), engineVersion: try row.text(5))
    }
    /// id 为明确稳定 ID；在当前事务连接内查找，包含 tombstone。
    private func find(_ id: UUID) throws -> StoredConfiguration? { try connection.rows(Self.select + " WHERE id=?", [.text(id.uuidString.lowercased())], decode: Self.decode).first }
    /// record/kind 为新完整快照；调用者必须已经开启事务，配置和变更同时提交。
    private func write(_ record: StoredConfiguration, kind: ConfigurationChangeKind) throws {
        let payload = try ContractJSON.encoder().encode(record.configuration)
        let id = record.id.uuidString.lowercased()
        try connection.execute("INSERT INTO configurations VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload,server_revision=excluded.server_revision,local_sequence=excluded.local_sequence,deleted=excluded.deleted,knowledge_version=excluded.knowledge_version,engine_version=excluded.engine_version,updated_at=excluded.updated_at",
            [.text(id), .text(record.configuration.name), .blob(payload), .integer(record.serverRevision), .integer(record.localSequence), .integer(record.deleted ? 1 : 0),
             .text(record.knowledgeVersion), .text(record.engineVersion), .integer(Int64(Date().timeIntervalSince1970 * 1000))])
        try connection.execute("INSERT INTO pending_changes(operation_id,entity_id,base_revision,local_sequence,kind,payload,knowledge_version,engine_version) VALUES (?,?,?,?,?,?,?,?)", [.text(UUID().uuidString.lowercased()), .text(id), .integer(record.serverRevision),
            .integer(record.localSequence), .text(kind.rawValue), .blob(payload), .text(record.knowledgeVersion), .text(record.engineVersion)])
    }

    /// 返回可发送的首条完整请求并在事务内冻结；重启/超时重试时 operationId 和内容不变。
    public func prepareSyncOperation() throws -> SyncOperation? {
        try connection.transaction {
            let blocked = Set(try connection.rows("SELECT entity_id FROM sync_conflicts WHERE resolved=0", decode: { try $0.text(0) }))
            guard let change = try pendingChanges().first(where: { !blocked.contains($0.entityId.uuidString.lowercased()) }) else { return nil }
            try connection.execute("UPDATE pending_changes SET sent=1 WHERE operation_id=?", [.text(change.operationId.uuidString.lowercased())])
            return SyncOperation(change: change)
        }
    }
    /// operation 为本次发送的冻结请求，result 为服务端回执；只确认对应序号，较新的离线编辑继续排队。
    public func acknowledge(_ operation: SyncOperation, result: SyncResult) throws {
        guard result.operationId == operation.operationId, ["accepted", "conflict"].contains(result.status) else { throw StorageFailure.invalidData("invalid sync acknowledgement") }
        try connection.transaction {
            guard try pendingChanges().contains(where: { $0.operationId == operation.operationId }) else { return }
            if result.status == "conflict" { try recordConflict(entityId: operation.entityId, remote: result.current); return }
            guard let remote = result.current, remote.entityId == operation.entityId, remote.revision > operation.baseRevision,
                  remote.configuration == operation.configuration, remote.deleted == (operation.kind == .delete),
                  remote.knowledgeVersion == operation.knowledgeVersion, remote.engineVersion == operation.engineVersion else { throw StorageFailure.invalidData("invalid accepted snapshot") }
            let id = operation.entityId.uuidString.lowercased()
            guard let current = try find(operation.entityId) else { throw StorageFailure.invalidData("missing local configuration") }
            try connection.execute("DELETE FROM pending_changes WHERE operation_id=?", [.text(operation.operationId.uuidString.lowercased())])
            // 旧请求的 ack 只提升服务器基线，绝不写回旧 payload；尚未发送的后续本地编辑沿用该基线。
            try connection.execute("UPDATE configurations SET server_revision=? WHERE id=?", [.integer(max(current.serverRevision, remote.revision)), .text(id)])
            try connection.execute("UPDATE pending_changes SET base_revision=? WHERE entity_id=? AND sent=0", [.integer(remote.revision), .text(id)])
        }
    }
    /// 返回已落地的增量游标；与拉取页应用同事务更新，崩溃后可重复读取整页。
    public func syncCursor() throws -> Int64 {
        guard let data = try connection.rows("SELECT value FROM settings WHERE key='sync_cursor'", decode: { try $0.data(0) }).first else { return 0 }
        return try ContractJSON.decoder().decode(Int64.self, from: data)
    }
    /// scope 为服务端和身份的稳定组合；首次绑定保留，以后不同作用域必须使用独立用户库而非复用旧 revision。
    public func bindSyncScope(_ scope: String) throws {
        guard !scope.isEmpty else { throw SyncFailure.scopeMismatch }
        try connection.transaction {
            if let data = try connection.rows("SELECT value FROM settings WHERE key='sync_scope'", decode: { try $0.data(0) }).first {
                guard try ContractJSON.decoder().decode(String.self, from: data) == scope else { throw SyncFailure.scopeMismatch }
            } else { try connection.execute("INSERT INTO settings VALUES ('sync_scope',?)", [.blob(try ContractJSON.encoder().encode(scope))]) }
        }
    }
    /// page 为按 revision 递增的完整远端快照；本地脏记录产生冲突副本，tombstone 不转成新记录。
    public func applySyncPage(_ page: SyncPage) throws {
        try connection.transaction {
            let previous = try syncCursor()
            var cursor = previous
            for remote in page.changes {
                guard remote.revision > cursor, remote.configuration.id == remote.entityId else { throw StorageFailure.invalidData("invalid sync page ordering") }
                cursor = remote.revision
                let current = try find(remote.entityId)
                if remote.revision <= (current?.serverRevision ?? 0) { continue }
                if try pendingChanges().contains(where: { $0.entityId == remote.entityId }) {
                    try recordConflict(entityId: remote.entityId, remote: remote)
                } else { try putRemote(remote, localSequence: current?.localSequence ?? 0) }
            }
            guard page.nextCursor == cursor else { throw StorageFailure.invalidData("invalid next sync cursor") }
            try connection.execute("INSERT INTO settings VALUES ('sync_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [.blob(try ContractJSON.encoder().encode(cursor))])
        }
    }
    /// 返回尚未人工处理的冲突；local 是当前编辑完整值，remote 保留服务端删除或完整快照。
    public func syncConflicts() throws -> [SyncConflict] {
        try connection.rows("SELECT entity_id,local,remote FROM sync_conflicts WHERE resolved=0 ORDER BY rowid") { row in
            guard let id = UUID(uuidString: try row.text(0)) else { throw StorageFailure.invalidData("invalid conflict identity") }
            return SyncConflict(entityId: id, local: try find(id) ?? ContractJSON.decoder().decode(StoredConfiguration.self, from: row.data(1)),
                remote: try ContractJSON.decoder().decode(SyncSnapshot?.self, from: row.data(2)))
        }
    }
    /// entityId 为活跃冲突；resolution 明确选择本地或远端。保留冲突历史，生成新操作而非修改已发送幂等请求。
    public func resolveConflict(entityId: UUID, resolution: SyncConflictResolution) throws {
        try connection.transaction {
            guard let conflict = try syncConflicts().first(where: { $0.entityId == entityId }) else { return }
            let id = entityId.uuidString.lowercased(), local = conflict.local
            try connection.execute("UPDATE sync_conflicts SET local=?,resolved=1 WHERE entity_id=? AND resolved=0", [.blob(try ContractJSON.encoder().encode(local)), .text(id)])
            try connection.execute("DELETE FROM pending_changes WHERE entity_id=?", [.text(id)])
            switch resolution {
            case .keepLocal:
                guard local.localSequence < Int64.max else { throw StorageFailure.invalidData("local sequence exceeds int64 range") }
                try write(StoredConfiguration(configuration: local.configuration, serverRevision: conflict.remote?.revision ?? 0,
                    localSequence: local.localSequence + 1, deleted: local.deleted, knowledgeVersion: local.knowledgeVersion, engineVersion: local.engineVersion), kind: local.deleted ? .delete : .upsert)
            case .keepRemote:
                if let remote = conflict.remote { try putRemote(remote, localSequence: local.localSequence) }
                else { try connection.execute("UPDATE configurations SET deleted=1,server_revision=0 WHERE id=?", [.text(id)]) }
            }
        }
    }
    /// entityId 对应本地脏记录；remote 可空（服务端尚无此 ID）。调用者持有事务，冲突按最新 revision 合并且不覆盖本地。
    private func recordConflict(entityId: UUID, remote: SyncSnapshot?) throws {
        guard remote == nil || remote?.entityId == entityId, let local = try find(entityId) else { throw StorageFailure.invalidData("invalid conflict snapshot") }
        let id = entityId.uuidString.lowercased()
        let existing = try connection.rows("SELECT remote FROM sync_conflicts WHERE entity_id=? AND resolved=0", [.text(id)], decode: { try ContractJSON.decoder().decode(SyncSnapshot?.self, from: $0.data(0)) })
        if let first = existing.first, (first?.revision ?? 0) >= (remote?.revision ?? 0) { return }
        try connection.execute("INSERT INTO sync_conflicts(id,entity_id,local,remote) VALUES (?,?,?,?) ON CONFLICT(entity_id) WHERE resolved=0 DO UPDATE SET local=excluded.local,remote=excluded.remote",
            [.text(UUID().uuidString.lowercased()), .text(id), .blob(try ContractJSON.encoder().encode(local)), .blob(try ContractJSON.encoder().encode(remote))])
    }
    /// remote 为已验证远端快照，localSequence 保留本设备序号；直接落库，不生成回传操作避免同步回声。
    private func putRemote(_ remote: SyncSnapshot, localSequence: Int64) throws {
        guard remote.entityId == remote.configuration.id, remote.revision > 0 else { throw StorageFailure.invalidData("invalid remote snapshot") }
        try connection.execute("INSERT INTO configurations VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,payload=excluded.payload,server_revision=excluded.server_revision,local_sequence=excluded.local_sequence,deleted=excluded.deleted,knowledge_version=excluded.knowledge_version,engine_version=excluded.engine_version,updated_at=excluded.updated_at",
            [.text(remote.entityId.uuidString.lowercased()), .text(remote.configuration.name), .blob(try ContractJSON.encoder().encode(remote.configuration)), .integer(remote.revision), .integer(localSequence), .integer(remote.deleted ? 1 : 0),
             .text(remote.knowledgeVersion), .text(remote.engineVersion), .integer(Int64(Date().timeIntervalSince1970 * 1000))])
    }
}
