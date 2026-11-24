import Foundation
import XCTest
@testable import PokemonAppSupport

/// 每个测试持有独立真实 SQLite；跨设备集成显式连接本次创建的 Go+PostgreSQL 服务，不使用内存假服务。
final class SynchronizationTests: XCTestCase, @unchecked Sendable {
    /// 返回独占 UUID 目录，调用者负责在测试结束时清理；不打开现有用户数据库。
    private func directory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-sync-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true); return root
    }
    /// 旧请求响应到达前再次编辑，不得把新内容回滚或删除后续队列；重试冻结请求保持相同字段。
    func testLateAcknowledgementPreservesNewEditAndFrozenRetry() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("user.sqlite"), store = try ConfigurationStore(url: url)
        var configuration = BattleConfiguration.example()
        try await store.save(configuration, knowledgeVersion: "knowledge-1", engineVersion: "0.4.0")
        let prepared = try await store.prepareSyncOperation(), operation = try XCTUnwrap(prepared)
        configuration.name = "new local edit while request is pending"
        try await store.save(configuration, knowledgeVersion: "knowledge-2", engineVersion: "0.4.1")
        let restarted = try ConfigurationStore(url: url), retry = try await restarted.prepareSyncOperation()
        XCTAssertEqual(try ContractJSON.encoder().encode(operation), try ContractJSON.encoder().encode(retry))
        let remote = SyncSnapshot(entityId: operation.entityId, revision: 1, deleted: false, configuration: operation.configuration,
                                  knowledgeVersion: operation.knowledgeVersion, engineVersion: operation.engineVersion)
        try await restarted.acknowledge(operation, result: SyncResult(operationId: operation.operationId, status: "accepted", current: remote))
        let current = try await restarted.all(), queue = try await restarted.pendingChanges()
        XCTAssertEqual(current.first?.configuration, configuration); XCTAssertEqual(current.first?.serverRevision, 1)
        XCTAssertEqual(queue.count, 1); XCTAssertEqual(queue.first?.baseRevision, 1); XCTAssertEqual(queue.first?.knowledgeVersion, "knowledge-2")
        XCTAssertEqual(queue.first?.engineVersion, "0.4.1"); XCTAssertEqual(queue.first?.localSequence, 2)
        // 重复 ack 幂等；已确认请求不再影响新变更。
        try await restarted.acknowledge(operation, result: SyncResult(operationId: operation.operationId, status: "accepted", current: remote))
        let remaining = try await restarted.pendingChanges(); XCTAssertEqual(remaining.count, 1)
    }
    /// 不合法增量页必须整体回滚，防止配置已写入但游标未提交；作用域变化也不能复用旧 revision。
    func testInvalidPageRollsBackAndScopeIsPersistent() async throws {
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let url = root.appendingPathComponent("user.sqlite"), store = try ConfigurationStore(url: url)
        let config = BattleConfiguration.example(), snapshot = SyncSnapshot(entityId: config.id, revision: 1, deleted: false, configuration: config, knowledgeVersion: "v1", engineVersion: "0.4.0")
        do { try await store.applySyncPage(SyncPage(changes: [snapshot], nextCursor: 9, hasMore: false)); XCTFail("invalid page accepted") }
        catch StorageFailure.invalidData { }
        let rows = try await store.all(), cursor = try await store.syncCursor(); XCTAssertTrue(rows.isEmpty); XCTAssertEqual(cursor, 0)
        try await store.bindSyncScope("test-server|alice")
        do { try await ConfigurationStore(url: url).bindSyncScope("test-server|bob"); XCTFail("different user reused sync state") }
        catch SyncFailure.scopeMismatch { }
    }
    /// 两个真实 SQLite 设备连接 Go HTTP+PostgreSQL：断线后重试、离线双写、显式冲突恢复、删除和重启最终收敛。
    func testTwoDevicesConvergeAgainstRealPostgreSQL() async throws {
        guard let address = ProcessInfo.processInfo.environment["PBI_SYNC_TEST_URL"], let server = URL(string: address) else { throw XCTSkip("PBI_SYNC_TEST_URL is required for real PostgreSQL sync acceptance") }
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let aURL = root.appendingPathComponent("device-a.sqlite"), bURL = root.appendingPathComponent("device-b.sqlite")
        let a = try ConfigurationStore(url: aURL), b = try ConfigurationStore(url: bURL)
        let transport = try HTTPSyncTransport(serverURL: server, userId: "swift-test-\(UUID().uuidString.lowercased())")
        let aClient = SyncClient(store: a, transport: transport), bClient = SyncClient(store: b, transport: transport)
        var initial = BattleConfiguration.example(); initial.name = "shared initial 中文\0preserved"
        try await a.save(initial, knowledgeVersion: "knowledge-1", engineVersion: "0.4.0")
        // 服务器已提交但设备尚未保存 ack，等价于响应丢失；重启后的请求必须使用旧 operationId。
        let first = try await a.prepareSyncOperation(), firstOperation = try XCTUnwrap(first)
        let ignored = try await transport.push(firstOperation); XCTAssertEqual(ignored.status, "accepted")
        let recovered = try ConfigurationStore(url: aURL), recoveredClient = SyncClient(store: recovered, transport: transport)
        let retried = try await recoveredClient.synchronize(); XCTAssertEqual(retried.accepted, 1); XCTAssertEqual(retried.received, 1)
        _ = try await bClient.synchronize()
        let bInitial = try await b.all(); XCTAssertEqual(bInitial.first?.configuration, initial)
        // 设备各自在无网络操作阶段修改同一个基线，A 先上线，B 必须得到可恢复冲突。
        var editA = initial, editB = initial; editA.name = "device A offline"; editB.name = "device B offline"
        try await a.save(editA, knowledgeVersion: "knowledge-1", engineVersion: "0.4.0")
        try await b.save(editB, knowledgeVersion: "knowledge-2", engineVersion: "0.4.1")
        _ = try await aClient.synchronize()
        let conflicted = try await bClient.synchronize(); XCTAssertEqual(conflicted.conflicts, 1)
        let bLocal = try await b.all(), conflicts = try await b.syncConflicts()
        XCTAssertEqual(bLocal.first?.configuration, editB); XCTAssertEqual(conflicts.first?.remote?.configuration, editA)
        XCTAssertEqual(conflicts.first?.local.knowledgeVersion, "knowledge-2")
        // 用户选择保留 B：生成新的幂等请求并引用远端最新 revision，A 拉取后两设备完整值一致。
        try await b.resolveConflict(entityId: initial.id, resolution: .keepLocal)
        let resolved = try await bClient.synchronize(); XCTAssertEqual(resolved.accepted, 1); XCTAssertEqual(resolved.conflicts, 0)
        _ = try await aClient.synchronize()
        let aResolved = try await a.all(), bResolved = try await b.all()
        XCTAssertEqual(aResolved.first?.configuration, editB); XCTAssertEqual(aResolved.first?.configuration, bResolved.first?.configuration)
        XCTAssertEqual(aResolved.first?.knowledgeVersion, "knowledge-2"); XCTAssertEqual(aResolved.first?.engineVersion, "0.4.1")
        try await b.delete(initial.id); _ = try await bClient.synchronize(); _ = try await aClient.synchronize()
        let aDeleted = try await ConfigurationStore(url: aURL).all(), bDeleted = try await ConfigurationStore(url: bURL).all()
        let aQueue = try await a.pendingChanges(), bQueue = try await b.pendingChanges()
        XCTAssertTrue(aDeleted.isEmpty); XCTAssertTrue(bDeleted.isEmpty); XCTAssertTrue(aQueue.isEmpty); XCTAssertTrue(bQueue.isEmpty)
        let aCursor = try await a.syncCursor(), bCursor = try await b.syncCursor(); XCTAssertEqual(aCursor, bCursor); XCTAssertEqual(aCursor, 4)
    }

    /// 两个真实SQLite离线写冲突后采用远端；保留已解决双方副本，重启收敛且不制造回声revision。
    func testKeepRemoteConflictConvergesAgainstRealPostgreSQL() async throws {
        guard let address = ProcessInfo.processInfo.environment["PBI_SYNC_TEST_URL"], let server = URL(string: address) else {
            throw XCTSkip("PBI_SYNC_TEST_URL is required for real PostgreSQL sync acceptance")
        }
        let root = try directory(); defer { try? FileManager.default.removeItem(at: root) }
        let aURL = root.appendingPathComponent("device-a.sqlite"), bURL = root.appendingPathComponent("device-b.sqlite")
        let a = try ConfigurationStore(url: aURL), b = try ConfigurationStore(url: bURL)
        let transport = try HTTPSyncTransport(serverURL: server, userId: "swift-keep-remote-\(UUID().uuidString.lowercased())")
        let aClient = SyncClient(store: a, transport: transport), bClient = SyncClient(store: b, transport: transport)
        var initial = BattleConfiguration.example(); initial.name = "initial remote recovery"
        try await a.save(initial, knowledgeVersion: "initial-knowledge", engineVersion: "0.9.0")
        _ = try await aClient.synchronize(); _ = try await bClient.synchronize()

        // 两侧只改自己的真实用户库；A先上线成为revision2，B保留完整本地参数与不同版本信息。
        var editA = initial, editB = initial
        editA.name = "remote device A"; editA.attacker.level = 73
        editB.name = "local device B"; editB.attacker.level = 22; editB.critical = true
        try await a.save(editA, knowledgeVersion: "remote-knowledge-2", engineVersion: "0.9.0")
        try await b.save(editB, knowledgeVersion: "local-knowledge-3", engineVersion: "0.9.1")
        let uploaded = try await aClient.synchronize(); XCTAssertEqual(uploaded.accepted, 1)
        let rejected = try await bClient.synchronize(); XCTAssertEqual(rejected.conflicts, 1)

        // 冲突与被冻结的未确认队列跨重启保留，不能先覆盖B再只保留一条错误提示。
        let reopenedB = try ConfigurationStore(url: bURL)
        let before = try await reopenedB.all(), conflicts = try await reopenedB.syncConflicts()
        let pending = try await reopenedB.pendingChanges(), cursorBefore = try await reopenedB.syncCursor()
        XCTAssertEqual(before.first?.configuration, editB); XCTAssertEqual(conflicts.count, 1)
        XCTAssertEqual(conflicts.first?.local.configuration, editB); XCTAssertEqual(conflicts.first?.remote?.configuration, editA)
        XCTAssertEqual(conflicts.first?.local.knowledgeVersion, "local-knowledge-3")
        XCTAssertEqual(conflicts.first?.local.engineVersion, "0.9.1")
        XCTAssertEqual(conflicts.first?.remote?.knowledgeVersion, "remote-knowledge-2")
        XCTAssertEqual(conflicts.first?.remote?.engineVersion, "0.9.0")
        XCTAssertEqual(conflicts.first?.remote?.revision, 2)
        XCTAssertEqual(pending.count, 1); XCTAssertEqual(pending.first?.configuration, editB)
        XCTAssertEqual(pending.first?.baseRevision, 1); XCTAssertEqual(cursorBefore, 2)

        // 采用远端只移除该实体的旧本地操作并使用完整远端快照，不发新的upsert或增加服务端revision。
        try await reopenedB.resolveConflict(entityId: initial.id, resolution: .keepRemote)
        let after = try await reopenedB.all(), queueAfter = try await reopenedB.pendingChanges()
        let unresolved = try await reopenedB.syncConflicts()
        XCTAssertEqual(after.first?.configuration, editA); XCTAssertEqual(after.first?.serverRevision, 2)
        XCTAssertEqual(after.first?.knowledgeVersion, "remote-knowledge-2"); XCTAssertEqual(after.first?.engineVersion, "0.9.0")
        XCTAssertTrue(queueAfter.isEmpty); XCTAssertTrue(unresolved.isEmpty)
        let resumed = try await SyncClient(store: reopenedB, transport: transport).synchronize()
        XCTAssertEqual(resumed.accepted, 0); XCTAssertEqual(resumed.conflicts, 0)
        _ = try await aClient.synchronize()

        // 两个库再次打开后逐字段收敛；各自本地序号可不同，完整配置/远端版本/游标和空队列必须一致。
        let finalA = try ConfigurationStore(url: aURL), finalB = try ConfigurationStore(url: bURL)
        let aRows = try await finalA.all(), bRows = try await finalB.all()
        XCTAssertEqual(aRows.count, 1); XCTAssertEqual(bRows.count, 1)
        XCTAssertEqual(aRows.first?.configuration, editA); XCTAssertEqual(aRows.first?.configuration, bRows.first?.configuration)
        XCTAssertEqual(aRows.first?.serverRevision, bRows.first?.serverRevision); XCTAssertEqual(bRows.first?.serverRevision, 2)
        XCTAssertEqual(aRows.first?.knowledgeVersion, bRows.first?.knowledgeVersion)
        XCTAssertEqual(aRows.first?.engineVersion, bRows.first?.engineVersion)
        let aQueue = try await finalA.pendingChanges(), bQueue = try await finalB.pendingChanges()
        let aCursor = try await finalA.syncCursor(), bCursor = try await finalB.syncCursor()
        XCTAssertTrue(aQueue.isEmpty); XCTAssertTrue(bQueue.isEmpty); XCTAssertEqual(aCursor, bCursor); XCTAssertEqual(bCursor, 2)

        // 已解决历史仍保留完整B本地值和A远端值，用户选择不能悄悄销毁冲突恢复资料。
        let connection = try SQLiteConnection(url: bURL, readOnly: true)
        let history = try connection.rows("SELECT local,remote,resolved FROM sync_conflicts") { row in
            (try ContractJSON.decoder().decode(StoredConfiguration.self, from: row.data(0)),
             try ContractJSON.decoder().decode(SyncSnapshot?.self, from: row.data(1)), try row.integer(2))
        }
        XCTAssertEqual(history.count, 1); XCTAssertEqual(history.first?.0.configuration, editB)
        XCTAssertEqual(history.first?.1?.configuration, editA); XCTAssertEqual(history.first?.2, 1)
    }
}
