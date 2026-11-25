import Foundation
import XCTest
@testable import PokemonAppSupport

/// 真实 SQLite/原生库测试；每个用例独占目录，无共享可变成员。
final class ApplicationTests: XCTestCase, @unchecked Sendable {
    /// 返回本次测试唯一目录，调用方只清理此 UUID 目录。
    private func directory() throws -> URL {
        let value = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-app-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: value, withIntermediateDirectories: true); return value
    }
    /// 从随包真实知识计算六项能力、完整伤害和精确 KO；没有服务端或 Swift 公式。
    func testOfflineCalculationUsesRealKnowledgeAndCore() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let knowledge = try KnowledgeStore(directory: root.appendingPathComponent("knowledge"), initial: KnowledgePack.bundled())
        let calculator = CalculationService(knowledge: knowledge)
        var configuration = BattleConfiguration.example()
        let result = try await calculator.calculate(configuration)
        XCTAssertEqual(result.attackerStats.attack, 182); XCTAssertEqual(result.defenderStats.hp, 202)
        XCTAssertEqual(result.damage.rolls, [99,100,101,102,104,105,106,107,108,109,111,112,113,114,115,117])
        XCTAssertEqual(result.damage.twoHit.text, "123/128"); XCTAssertEqual(result.damage.ohko.text, "0")
        XCTAssertEqual(result.attackerSpeed, 85); XCTAssertEqual(result.defenderSpeed, 80)
        configuration.attacker.paralyzed = true
        let paralyzed = try await calculator.calculate(configuration)
        XCTAssertEqual(paralyzed.attackerSpeed, 42); XCTAssertEqual(paralyzed.damage.rolls, result.damage.rolls)
        XCTAssertFalse(result.request.isEmpty); XCTAssertFalse(result.response.isEmpty)
    }
    /// 配置与完整变更队列同事务保存，重启后可编辑/删除且稳定 ID 不变；知识更新不清空用户库。
    func testConfigurationPersistenceQueueAndDeletion() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("user.sqlite")
        let store = try ConfigurationStore(url: url)
        var input = BattleConfiguration.example(); input.name = "中文 ' 配置\0完整"
        let first = try await store.save(input, knowledgeVersion: "v1", engineVersion: "0.4.0")
        let again = try await store.save(input, knowledgeVersion: "v1", engineVersion: "0.4.0")
        XCTAssertEqual(first.id, again.id); XCTAssertEqual(again.localSequence, 1)
        let initialQueue = try await store.pendingChanges(); XCTAssertEqual(initialQueue.count, 1)
        let restarted = try ConfigurationStore(url: url)
        let loaded = try await restarted.all(); XCTAssertEqual(loaded.first?.configuration, input)
        input.attacker.level = 51
        let edited = try await restarted.save(input, knowledgeVersion: "v1", engineVersion: "0.4.0"); XCTAssertEqual(edited.localSequence, 2)
        let knowledge = try KnowledgeStore(directory: root.appendingPathComponent("knowledge"), initial: KnowledgePack.bundled())
        try await knowledge.install(KnowledgePack.bundled())
        let preserved = try await restarted.all(); XCTAssertEqual(preserved.first?.configuration, input)
        try await restarted.delete(input.id); try await restarted.delete(input.id)
        let visible = try await restarted.all(); XCTAssertTrue(visible.isEmpty)
        let queue = try await restarted.pendingChanges(); XCTAssertEqual(queue.count, 3)
        XCTAssertEqual(queue.map(\.kind), [.upsert, .upsert, .delete]); XCTAssertEqual(Set(queue.map(\.operationId)).count, 3)
        XCTAssertTrue(queue.allSatisfy { $0.entityId == input.id && $0.baseRevision == 0 })
        try await restarted.setServerURL(URL(string: "http://127.0.0.1:41105"))
        let storedURL = try await ConfigurationStore(url: url).serverURL(); XCTAssertEqual(storedURL?.absoluteString, "http://127.0.0.1:41105")
    }
    /// 队列写失败时配置 upsert 必须一起回滚，不留下 UI 看得到但无法同步的半条数据。
    func testChangeQueueFailureRollsBackConfiguration() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("user.sqlite")
        let store = try ConfigurationStore(url: url)
        let injection = try SQLiteConnection(url: url, readOnly: false)
        try injection.execute("CREATE TRIGGER fail_queue BEFORE INSERT ON pending_changes BEGIN SELECT RAISE(ABORT,'test queue failure'); END")
        do { try await store.save(BattleConfiguration.example(), knowledgeVersion: "v1", engineVersion: "0.4.0"); XCTFail("queue failure was ignored") }
        catch StorageFailure.database { }
        let rows = try await store.all(), queue = try await store.pendingChanges()
        XCTAssertTrue(rows.isEmpty); XCTAssertTrue(queue.isEmpty)
    }
    /// 连接两项原子保存并跨重启保留；写失败或换同步空间不得留下半套设置或清除旧用户库。
    func testConnectionSettingsRollbackAndBoundScope() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("user.sqlite"), store = try ConfigurationStore(url: url)
        let first = try XCTUnwrap(URL(string: "http://127.0.0.1:41106"))
        let other = try XCTUnwrap(URL(string: "http://127.0.0.1:41107"))
        try await store.setConnectionSettings(serverURL: first, userIdentifier: " alice ")
        let restarted = try ConfigurationStore(url: url)
        let savedUser = try await restarted.syncUserIdentifier(), savedServer = try await restarted.serverURL()
        XCTAssertEqual(savedUser, "alice"); XCTAssertEqual(savedServer, first)
        // 即使同步账户为空，非法计算服务地址也必须整体拒绝，不清空原账户。
        do { try await restarted.setConnectionSettings(serverURL: URL(string: "http://127.0.0.1:41107?query=invalid"), userIdentifier: ""); XCTFail("query endpoint accepted") }
        catch SyncFailure.invalidEndpoint { }
        let injection = try SQLiteConnection(url: url, readOnly: false)
        try injection.execute("CREATE TRIGGER fail_identity BEFORE UPDATE ON settings WHEN NEW.key='sync_user' BEGIN SELECT RAISE(ABORT,'test settings failure'); END")
        do { try await restarted.setConnectionSettings(serverURL: other, userIdentifier: "bob"); XCTFail("partial settings commit accepted") }
        catch StorageFailure.database { }
        let unchangedURL = try await restarted.serverURL(), unchangedUser = try await restarted.syncUserIdentifier()
        XCTAssertEqual(unchangedURL, first); XCTAssertEqual(unchangedUser, "alice")
        try injection.execute("DROP TRIGGER fail_identity")
        try await restarted.bindSyncScope(HTTPSyncTransport(serverURL: first, userId: "alice").scopeIdentifier)
        do { try await restarted.setConnectionSettings(serverURL: other, userIdentifier: "alice"); XCTFail("different server reused sync state") }
        catch SyncFailure.scopeMismatch { }
        do { try await restarted.setConnectionSettings(serverURL: first, userIdentifier: "bob"); XCTFail("different user reused sync state") }
        catch SyncFailure.scopeMismatch { }
        do { try await restarted.setConnectionSettings(serverURL: first, userIdentifier: "bad\0identity"); XCTFail("control character accepted") }
        catch SyncFailure.invalidEndpoint { }
        let finalURL = try await ConfigurationStore(url: url).serverURL(), finalUser = try await restarted.syncUserIdentifier()
        XCTAssertEqual(finalURL, first); XCTAssertEqual(finalUser, "alice")
    }
}
