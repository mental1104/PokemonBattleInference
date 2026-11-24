import Foundation
import XCTest
@testable import PokemonAppSupport

/// 使用真实随包 SQLite 和独立临时目录验证查询、重启及失败更新，不依赖数据库服务或网络。
// 每个测试仅持有独占 UUID 目录，无共享可变成员，可由 XCTest 并发调度。
final class KnowledgeStoreTests: XCTestCase, @unchecked Sendable {
    /// 返回本测试独占目录；调用方 defer 仅移除此 UUID 目录。
    private func temporaryDirectory() throws -> URL {
        let value = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-knowledge-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: value, withIntermediateDirectories: true)
        return value
    }

    /// 首装包必须含真实完整数据；中文搜索、明确招式字段和六项种族值均从 SQLite 读取。
    func testBundledLookupAndRestart() async throws {
        let directory = try temporaryDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let store = try KnowledgeStore(directory: directory, initial: KnowledgePack.bundled())
        let version = await store.version()
        XCTAssertEqual(version.counts.pokemon, 1350); XCTAssertEqual(version.counts.moves, 937)
        let results = try await store.searchPokemon("巨钳螳螂")
        XCTAssertTrue(results.contains { $0.id == 212 })
        let pokemon = try await store.pokemon(212)
        XCTAssertEqual(pokemon.summary.name, "巨钳螳螂")
        XCTAssertEqual(pokemon.baseStats, StatValues(hp: 70, attack: 130, defense: 100, specialAttack: 55, specialDefense: 80, speed: 65))
        XCTAssertEqual(pokemon.types.map(\.id), [7, 9])
        let move = try await store.move(418)
        XCTAssertEqual(move.name, "子弹拳"); XCTAssertEqual(move.power, 40); XCTAssertEqual(move.priority, 1)
        let natureCount = try await store.natures().count; XCTAssertEqual(natureCount, 25)
        let chartCount = try await store.typeChart().count; XCTAssertEqual(chartCount, 324)
        let injected = try await store.searchPokemon("'; DROP TABLE pokemon; --"); XCTAssertTrue(injected.isEmpty)
        let missing = directory.appendingPathComponent("unavailable-bundle")
        let reopened = try KnowledgeStore(directory: directory, initial: KnowledgePack(database: missing, manifest: missing))
        let restarted = try await reopened.pokemon(212); XCTAssertEqual(restarted.baseStats, pokemon.baseStats)
    }

    /// 真实损坏/不支持包必须失败，原 manifest、连接和查询结果仍完整保留。
    func testFailedUpdatePreservesInstalledVersion() async throws {
        let directory = try temporaryDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let bundle = try KnowledgePack.bundled()
        let store = try KnowledgeStore(directory: directory.appendingPathComponent("installed"), initial: bundle)
        let initial = await store.version()
        let pointer = directory.appendingPathComponent("installed/current.json")
        let previousPointer = try Data(contentsOf: pointer)
        let broken = directory.appendingPathComponent("broken.sqlite")
        var bytes = try Data(contentsOf: bundle.database); bytes[100] ^= 0xff; try bytes.write(to: broken)
        do { try await store.install(KnowledgePack(database: broken, manifest: bundle.manifest)); XCTFail("corrupt package was accepted") }
        catch StorageFailure.checksumMismatch { }
        let after = await store.version(); XCTAssertEqual(after, initial)
        XCTAssertEqual(try Data(contentsOf: pointer), previousPointer)
        let pokemon = try await store.pokemon(700); XCTAssertEqual(pokemon.summary.name, "仙子伊布")
        let unsupported = KnowledgeManifest(schemaVersion: 2, dataVersion: initial.dataVersion, sourceRevision: initial.sourceRevision,
            inputSha256: initial.inputSha256, sqliteSha256: initial.sqliteSha256, byteSize: initial.byteSize, counts: initial.counts, sources: initial.sources)
        let manifest = directory.appendingPathComponent("future.json"); try ContractJSON.encoder().encode(unsupported).write(to: manifest)
        do { try await store.install(KnowledgePack(database: bundle.database, manifest: manifest)); XCTFail("unsupported schema was accepted") }
        catch StorageFailure.unsupportedSchema { }
        XCTAssertEqual(try Data(contentsOf: pointer), previousPointer)
    }

    /// 同一包重复安装幂等；另一个完整版本原子切换后重启可用，旧版本文件仍保留。
    func testValidUpdateIsAtomicAndKeepsOldVersion() async throws {
        let directory = try temporaryDirectory(); defer { try? FileManager.default.removeItem(at: directory) }
        let bundle = try KnowledgePack.bundled()
        let installed = directory.appendingPathComponent("installed")
        let store = try KnowledgeStore(directory: installed, initial: bundle)
        let original = await store.version()
        try await store.install(bundle)
        let same = await store.version(); XCTAssertEqual(same, original)
        let next = directory.appendingPathComponent("next.sqlite"); try FileManager.default.copyItem(at: bundle.database, to: next)
        do { let connection = try SQLiteConnection(url: next, readOnly: false); try connection.execute("UPDATE metadata SET value=? WHERE key='data_version'", [.text("test-update-v2")]) }
        let checksum = try FileChecksum.sha256(next)
        let size = try FileManager.default.attributesOfItem(atPath: next.path)[.size] as! NSNumber
        let manifest = KnowledgeManifest(schemaVersion: 1, dataVersion: "test-update-v2", sourceRevision: original.sourceRevision,
            inputSha256: original.inputSha256, sqliteSha256: checksum, byteSize: size.int64Value, counts: original.counts, sources: original.sources)
        let manifestURL = directory.appendingPathComponent("next.json"); try ContractJSON.encoder().encode(manifest).write(to: manifestURL)
        try await store.install(KnowledgePack(database: next, manifest: manifestURL))
        let updated = await store.version(); XCTAssertEqual(updated.dataVersion, "test-update-v2")
        XCTAssertTrue(FileManager.default.fileExists(atPath: installed.appendingPathComponent("knowledge-\(original.sqliteSha256).sqlite").path))
        let reopened = try KnowledgeStore(directory: installed, initial: bundle)
        let current = await reopened.version(); XCTAssertEqual(current.sqliteSha256, checksum)
        let pokemon = try await reopened.pokemon(212); XCTAssertEqual(pokemon.summary.identifier, "scizor")
    }
}
