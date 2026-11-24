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
        var initial = BattleConfiguration.example(); initial.name = "shared initial"
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
}
