import Foundation
#if canImport(CryptoKit)
import CryptoKit
#endif
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// Apple 使用 SDK CryptoKit，Linux 验证工具环境使用既有 sha256sum；两端执行同样真实文件测试。
enum FileChecksum {
    /// - Parameter url: 只读文件位置，流式计算，不修改源文件。
    /// - Returns: 小写 SHA-256；读文件/平台工具失败明确抛错。
    static func sha256(_ url: URL) throws -> String {
        #if canImport(CryptoKit)
        let input = try FileHandle(forReadingFrom: url)
        defer { try? input.close() }
        var hash = SHA256()
        while let block = try input.read(upToCount: 1_048_576), !block.isEmpty { hash.update(data: block) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
        #else
        // Linux 没有 Apple CryptoKit；进程参数直接传递，不经过 shell 或拼接命令。
        let task = Process(); task.executableURL = URL(fileURLWithPath: "/usr/bin/sha256sum"); task.arguments = [url.path]
        let output = Pipe(); task.standardOutput = output; task.standardError = Pipe()
        try task.run()
        let data = output.fileHandleForReading.readDataToEndOfFile(); task.waitUntilExit()
        guard task.terminationStatus == 0, let line = String(data: data, encoding: .utf8), line.count >= 64 else { throw StorageFailure.fileOperation("SHA-256 tool failed") }
        return String(line.prefix(64))
        #endif
    }
}

/// 一个已验证且打开的不可变版本文件；连接仅由 KnowledgeStore actor 操作。
private struct InstalledKnowledge: Sendable {
    let manifest: KnowledgeManifest
    let connection: SQLiteConnection
}

/// 无外部服务的知识数据 actor；只读连接、版本文件和单一原子 manifest 指针。
/// 用户配置库完全独立；失败更新保留旧指针/旧文件/旧连接，不清理其他版本或目录。
public actor KnowledgeStore {
    private let directory: URL
    private var installed: InstalledKnowledge

    /// directory 为本 App 的知识运行目录，initial 为随包首装资源；既有版本先按其 manifest 验证。
    public init(directory: URL, initial: KnowledgePack) throws {
        self.directory = directory
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let descriptor = directory.appendingPathComponent("current.json")
        if FileManager.default.fileExists(atPath: descriptor.path) {
            let manifest = try ContractJSON.decoder().decode(KnowledgeManifest.self, from: Data(contentsOf: descriptor))
            installed = try Self.validate(database: Self.versionFile(directory, manifest), manifest: manifest)
        } else { installed = try Self.install(initial, directory: directory) }
    }

    /// 返回当前实际打开的版本，不使用远端推荐版本冒充已经安装。
    public func version() -> KnowledgeManifest { installed.manifest }

    /// candidate 为完整候选包；成功原子切换，任何验证/复制失败均保留当前版本和独立用户库。
    public func install(_ candidate: KnowledgePack) throws {
        let next = try Self.install(candidate, directory: directory)
        installed = next
    }

    /// text 为用户搜索，limit/offset 是有界分页；所有值经绑定，不拼接用户输入。
    public func searchPokemon(_ text: String = "", limit: Int = 100, offset: Int = 0) throws -> [PokemonSummary] {
        try Self.validatePage(limit, offset)
        let search = "%" + text + "%"
        return try installed.connection.rows("SELECT id,species_id,identifier,name FROM pokemon WHERE name LIKE ? OR identifier LIKE ? ORDER BY id LIMIT ? OFFSET ?",
            [.text(search), .text(search), .integer(Int64(limit)), .integer(Int64(offset))]) {
            PokemonSummary(id: try $0.integer(0), speciesId: try $0.integer(1), identifier: try $0.text(2), name: try $0.text(3))
        }
    }

    /// id 为明确宝可梦/形态；返回完整本地知识，缺失/损坏数据直接失败，不替换成另一物种。
    public func pokemon(_ id: Int64) throws -> PokemonDetails {
        let database = installed.connection
        let rows = try database.rows("SELECT id,species_id,identifier,name,height,weight,can_evolve FROM pokemon WHERE id=?", [.integer(id)]) { row in
            (PokemonSummary(id: try row.integer(0), speciesId: try row.integer(1), identifier: try row.text(2), name: try row.text(3)),
             Int(try row.integer(4)), Int(try row.integer(5)), try row.integer(6) == 1)
        }
        guard let value = rows.first else { throw StorageFailure.invalidData("pokemon id is missing from the knowledge pack") }
        let stats = try database.rows("SELECT stat_id,base_stat FROM pokemon_stats WHERE pokemon_id=? ORDER BY stat_id", [.integer(id)]) { (try $0.integer(0), Int(try $0.integer(1))) }
        guard stats.map({ $0.0 }) == [1, 2, 3, 4, 5, 6] else { throw StorageFailure.invalidData("pokemon base stats are incomplete") }
        let types = try database.rows("SELECT t.id,t.identifier,t.name FROM pokemon_types p JOIN types t ON t.id=p.type_id WHERE p.pokemon_id=? ORDER BY p.slot", [.integer(id)]) {
            PokemonType(id: try $0.integer(0), identifier: try $0.text(1), name: try $0.text(2))
        }
        let abilities = try database.rows("SELECT a.id,a.identifier,a.name,p.is_hidden FROM pokemon_abilities p JOIN abilities a ON a.id=p.ability_id WHERE p.pokemon_id=? ORDER BY p.slot", [.integer(id)]) {
            PokemonAbility(id: try $0.integer(0), identifier: try $0.text(1), name: try $0.text(2), hidden: try $0.integer(3) == 1)
        }
        return PokemonDetails(summary: value.0, baseStats: StatValues(hp: stats[0].1, attack: stats[1].1, defense: stats[2].1,
            specialAttack: stats[3].1, specialDefense: stats[4].1, speed: stats[5].1), types: types, abilities: abilities,
            height: value.1, weight: value.2, canEvolve: value.3)
    }

    /// text/limit/offset 为绑定分页参数；空威力等原始字段保持可空。
    public func searchMoves(_ text: String = "", limit: Int = 100, offset: Int = 0) throws -> [MoveDetails] {
        try Self.validatePage(limit, offset)
        let search = "%" + text + "%"
        return try installed.connection.rows(Self.moveSelect + " WHERE name LIKE ? OR identifier LIKE ? ORDER BY id LIMIT ? OFFSET ?",
            [.text(search), .text(search), .integer(Int64(limit)), .integer(Int64(offset))], decode: Self.decodeMove)
    }
    /// id 为固定招式 ID；查询失败不使用默认招式代替。
    public func move(_ id: Int64) throws -> MoveDetails {
        guard let value = try installed.connection.rows(Self.moveSelect + " WHERE id=?", [.integer(id)], decode: Self.decodeMove).first else { throw StorageFailure.invalidData("move id is missing from the knowledge pack") }
        return value
    }
    /// 返回全部 25 性格的原能力轴，不在 Swift 计算性格倍率。
    public func natures() throws -> [NatureDetails] {
        try installed.connection.rows("SELECT id,name,decreased_stat_id,increased_stat_id FROM natures ORDER BY id") {
            NatureDetails(id: try $0.integer(0), name: try $0.text(1), decreasedStatId: Int(try $0.integer(2)), increasedStatId: Int(try $0.integer(3)))
        }
    }
    /// 返回注入 Core 的完整现代属性表；未知计算机制仍由 Core 明确拒绝。
    public func typeChart() throws -> [TypeEfficacy] {
        try installed.connection.rows("SELECT attacking,defending,percent FROM type_efficacy ORDER BY attacking,defending") {
            TypeEfficacy(attacking: try $0.integer(0), defending: try $0.integer(1), percent: Int(try $0.integer(2)))
        }
    }
    /// 返回全部属性名称，仅用于查询和展示。
    public func types() throws -> [PokemonType] {
        try installed.connection.rows("SELECT id,identifier,name FROM types ORDER BY id") { PokemonType(id: try $0.integer(0), identifier: try $0.text(1), name: try $0.text(2)) }
    }

    private static let moveSelect = "SELECT id,identifier,name,type_id,power,pp,accuracy,priority,damage_class_id,generation_id FROM moves"
    /// row 为当前 statement 的只读行；返回完整招式值，分类编号非法时明确失败。
    private static func decodeMove(_ row: SQLiteStatement) throws -> MoveDetails {
        let category: MoveCategory
        switch try row.integer(8) { case 1: category = .status; case 2: category = .physical; case 3: category = .special; default: throw StorageFailure.invalidData("invalid move category") }
        return MoveDetails(id: try row.integer(0), identifier: try row.text(1), name: try row.text(2), typeId: try row.integer(3),
            power: try row.optionalInteger(4).map(Int.init), pp: try row.optionalInteger(5).map(Int.init), accuracy: try row.optionalInteger(6).map(Int.init),
            priority: Int(try row.integer(7)), category: category, generationId: Int(try row.integer(9)))
    }
    /// limit/offset 必须符合查询边界；不影响包内完整数据量。
    private static func validatePage(_ limit: Int, _ offset: Int) throws {
        guard (1...500).contains(limit), offset >= 0 else { throw StorageFailure.invalidData("invalid knowledge query page") }
    }
    /// directory 为自有知识目录，manifest 的 SHA 在 validate 中检查；文件名不接受外部路径片段。
    private static func versionFile(_ directory: URL, _ manifest: KnowledgeManifest) -> URL {
        directory.appendingPathComponent("knowledge-\(manifest.sqliteSha256).sqlite")
    }
    /// database 为完整候选文件，manifest 为预期校验；返回真正打开且验证过的只读连接。
    private static func validate(database: URL, manifest: KnowledgeManifest) throws -> InstalledKnowledge {
        guard manifest.schemaVersion == 1 else { throw StorageFailure.unsupportedSchema }
        guard manifest.sqliteSha256.count == 64, manifest.sqliteSha256.allSatisfy({ "0123456789abcdef".contains($0) }) else { throw StorageFailure.invalidData("invalid knowledge SHA-256") }
        let size = try FileManager.default.attributesOfItem(atPath: database.path)[.size] as? NSNumber
        guard size?.int64Value == manifest.byteSize, try FileChecksum.sha256(database) == manifest.sqliteSha256 else { throw StorageFailure.checksumMismatch }
        let connection = try SQLiteConnection(url: database, readOnly: true)
        guard try connection.rows("PRAGMA user_version", decode: { try $0.integer(0) }) == [1],
              try connection.rows("PRAGMA quick_check", decode: { try $0.text(0) }) == ["ok"],
              try connection.rows("SELECT value FROM metadata WHERE key='data_version'", decode: { try $0.text(0) }) == [manifest.dataVersion] else { throw StorageFailure.invalidData("knowledge schema or metadata is invalid") }
        let expected = manifest.counts
        let counts = [("pokemon", expected.pokemon), ("pokemon_stats", expected.pokemonStats), ("pokemon_types", expected.pokemonTypes),
            ("pokemon_abilities", expected.pokemonAbilities), ("moves", expected.moves), ("types", expected.types), ("natures", expected.natures),
            ("abilities", expected.abilities), ("type_efficacy", expected.typeEfficacy)]
        for (table, count) in counts {
            guard try connection.rows("SELECT count(*) FROM \(table)", decode: { try $0.integer(0) }) == [Int64(count)] else { throw StorageFailure.invalidData("knowledge row counts differ from manifest") }
        }
        return InstalledKnowledge(manifest: manifest, connection: connection)
    }
    /// candidate 为只读交付文件，directory 为自有目录；先准备完整版本，最后原子提交一个指针文件。
    private static func install(_ candidate: KnowledgePack, directory: URL) throws -> InstalledKnowledge {
        let manifest = try ContractJSON.decoder().decode(KnowledgeManifest.self, from: Data(contentsOf: candidate.manifest))
        _ = try validate(database: candidate.database, manifest: manifest)
        let version = versionFile(directory, manifest)
        if !FileManager.default.fileExists(atPath: version.path) {
            let staging = directory.appendingPathComponent("staging-\(UUID().uuidString).sqlite")
            defer { try? FileManager.default.removeItem(at: staging) }
            try FileManager.default.copyItem(at: candidate.database, to: staging)
            let file = try FileHandle(forUpdating: staging); defer { try? file.close() }; try file.synchronize()
            guard try FileChecksum.sha256(staging) == manifest.sqliteSha256 else { throw StorageFailure.checksumMismatch }
            try atomicRename(staging, version)
        }
        let ready = try validate(database: version, manifest: manifest)
        let temporary = directory.appendingPathComponent("pointer-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: temporary) }
        try ContractJSON.encoder().encode(manifest).write(to: temporary)
        let file = try FileHandle(forUpdating: temporary); defer { try? file.close() }; try file.synchronize()
        try atomicRename(temporary, directory.appendingPathComponent("current.json"))
        return ready
    }
    /// source/target 必须在同一自有文件系统目录；POSIX rename 原子替换单一已验证指针。
    private static func atomicRename(_ source: URL, _ target: URL) throws {
        let status = source.path.withCString { from in target.path.withCString { to in
            #if canImport(Darwin)
            Darwin.rename(from, to)
            #else
            Glibc.rename(from, to)
            #endif
        } }
        guard status == 0 else { throw StorageFailure.fileOperation("atomic knowledge replacement failed") }
    }
}
