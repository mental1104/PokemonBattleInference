import Foundation
import XCTest
@testable import PokemonAppSupport

/// 真实不同 SQLite 版本在更新和计算读取间竞争，manifest 与整组知识必须始终一致。
final class CalculationSnapshotTests: XCTestCase, @unchecked Sendable {
    /// root 为本测试独占输出目录，bundle 为只读原包；返回修改多个计算字段且校验合法的候选版本。
    private func changedPack(root: URL, bundle: KnowledgePack) throws -> KnowledgePack {
        let original = try ContractJSON.decoder().decode(KnowledgeManifest.self, from: Data(contentsOf: bundle.manifest))
        let database = root.appendingPathComponent("changed.sqlite")
        try FileManager.default.copyItem(at: bundle.database, to: database)
        do {
            let connection = try SQLiteConnection(url: database, readOnly: false)
            try connection.transaction {
                try connection.execute("UPDATE metadata SET value='snapshot-v2' WHERE key='data_version'")
                try connection.execute("UPDATE pokemon_stats SET base_stat=200 WHERE pokemon_id=212 AND stat_id=2")
                try connection.execute("UPDATE pokemon_stats SET base_stat=240 WHERE pokemon_id=700 AND stat_id=3")
                try connection.execute("UPDATE moves SET power=120 WHERE id=418")
                try connection.execute("UPDATE natures SET decreased_stat_id=3,increased_stat_id=4 WHERE id=1")
                try connection.execute("UPDATE type_efficacy SET percent=300 WHERE attacking=9 AND defending=18")
            }
        }
        let manifest = KnowledgeManifest(schemaVersion: 1, dataVersion: "snapshot-v2", sourceRevision: original.sourceRevision,
            inputSha256: original.inputSha256, sqliteSha256: try FileChecksum.sha256(database),
            byteSize: Int64(try Data(contentsOf: database).count), counts: original.counts, sources: original.sources)
        let descriptor = root.appendingPathComponent("changed.json")
        try ContractJSON.encoder().encode(manifest).write(to: descriptor)
        return KnowledgePack(database: database, manifest: descriptor)
    }

    /// snapshot 为一次实际读取结果；oldVersion 唯一标识原包，全部能力/招式/性格/属性值必须属于该完整版本。
    private func verify(_ snapshot: CalculationKnowledgeSnapshot, oldVersion: KnowledgeManifest) throws {
        let updated = snapshot.version.dataVersion == "snapshot-v2"
        if !updated { XCTAssertEqual(snapshot.version, oldVersion) }
        XCTAssertEqual(snapshot.attacker.baseStats.attack, updated ? 200 : 130)
        XCTAssertEqual(snapshot.defender.baseStats.defense, updated ? 240 : 65)
        XCTAssertEqual(snapshot.move.power, updated ? 120 : 40)
        let nature = try XCTUnwrap(snapshot.natures.first { $0.id == 1 })
        XCTAssertEqual(nature.decreasedStatId, updated ? 3 : 2)
        XCTAssertEqual(nature.increasedStatId, updated ? 4 : 2)
        let efficacy = try XCTUnwrap(snapshot.typeChart.first { $0.attacking == 9 && $0.defending == 18 })
        XCTAssertEqual(efficacy.percent, updated ? 300 : 200)
    }

    /// 并发切换两版真实数据并读取 64 组输入；任何跨版本混用都无法同时满足多字段与版本断言。
    func testConcurrentInstallKeepsCalculationInputsInOneVersion() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-snapshot-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let bundle = try KnowledgePack.bundled()
        let changed = try changedPack(root: root, bundle: bundle)
        let store = try KnowledgeStore(directory: root.appendingPathComponent("installed"), initial: bundle)
        let original = await store.version()
        let retained = try await store.calculationSnapshot(attackerId: 212, defenderId: 700, moveId: 418)
        try await withThrowingTaskGroup(of: Void.self) { group in
            // 更新任务每次进入 actor 独立安装；读取任务只能拿到完整旧版或新版。
            group.addTask {
                for _ in 0..<8 { try await store.install(changed); try await store.install(bundle) }
            }
            group.addTask {
                for _ in 0..<64 {
                    let snapshot = try await store.calculationSnapshot(attackerId: 212, defenderId: 700, moveId: 418)
                    try self.verify(snapshot, oldVersion: original)
                }
            }
            try await group.waitForAll()
        }
        try await store.install(changed)
        let next = try await store.calculationSnapshot(attackerId: 212, defenderId: 700, moveId: 418)
        XCTAssertEqual(next.version.dataVersion, "snapshot-v2")
        try verify(next, oldVersion: original)
        // 已经取得的拥有值在安装完成后仍是原版，不能把新 manifest 贴到旧输入上。
        try verify(retained, oldVersion: original)
        XCTAssertEqual(retained.version, original)
    }
}
