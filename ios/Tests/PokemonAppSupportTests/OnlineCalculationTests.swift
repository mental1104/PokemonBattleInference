import Foundation
import XCTest
@testable import PokemonAppSupport

/// 实际 HTTP 服务集成：本机 Swift 调用和远端 Go 都使用正式 Core，不使用网络替身。
final class OnlineCalculationTests: XCTestCase, @unchecked Sendable {
    /// 从显式测试环境取得本轮独占服务；未配置时跳过，错误 URL 则失败，不连接默认或生产地址。
    private func server() throws -> URL {
        guard let address = ProcessInfo.processInfo.environment["PBI_ONLINE_TEST_URL"] else {
            throw XCTSkip("PBI_ONLINE_TEST_URL is required for real Go HTTP calculation acceptance")
        }
        guard let value = URL(string: address), value.host != nil, ["http", "https"].contains(value.scheme ?? "") else {
            throw StorageFailure.invalidData("invalid online integration server URL")
        }
        return value
    }

    /// 返回独占知识目录；调用者只删除本测试创建的 UUID 目录，不打开现有用户数据。
    private func directory() throws -> URL {
        let value = FileManager.default.temporaryDirectory.appendingPathComponent("pbi-online-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: value, withIntermediateDirectories: true)
        return value
    }

    /// result 为完整实测结果，prefix 区分路径和用例；可选报告目录保存可独立复查的正式 JSON。
    private func archive(_ result: CalculationResult, prefix: String) throws {
        guard let path = ProcessInfo.processInfo.environment["PBI_ONLINE_REPORT_DIRECTORY"] else { return }
        let output = URL(fileURLWithPath: path, isDirectory: true)
        try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
        try result.request.write(to: output.appendingPathComponent("\(prefix)-request.json"), options: .atomic)
        try result.response.write(to: output.appendingPathComponent("\(prefix)-response.json"), options: .atomic)
    }

    /// 同一知识和输入先后调用本机 Core、真实 Go HTTP，核对全部能力/速度/伤害/轨迹/概率/版本及原始 JSON。
    func testOnlineAndOfflineFullResultsMatch() async throws {
        let remote = try server(), root = try directory()
        defer { try? FileManager.default.removeItem(at: root) }
        let knowledge = try KnowledgeStore(directory: root.appendingPathComponent("knowledge"), initial: KnowledgePack.bundled())
        let calculator = CalculationService(knowledge: knowledge)
        var altered = BattleConfiguration.example()
        altered.attacker.level = 73
        altered.attacker.natureId = 4
        altered.attacker.ability = .technician
        altered.attacker.item = .lifeOrb
        altered.attacker.paralyzed = true
        altered.generationId = 6
        altered.critical = true
        var special = BattleConfiguration.example()
        special.attacker.pokemonId = 700
        special.defender.pokemonId = 212
        special.moveId = 247
        special.attacker.natureId = 15
        special.attacker.item = .choiceSpecs
        special.weather = .sandstorm
        for (index, configuration) in [BattleConfiguration.example(), altered, special].enumerated() {
            let offline = try await calculator.calculate(configuration)
            let online = try await calculator.calculate(configuration, server: remote)
            XCTAssertEqual(online.attackerStats, offline.attackerStats)
            XCTAssertEqual(online.defenderStats, offline.defenderStats)
            XCTAssertEqual(online.attackerSpeed, offline.attackerSpeed)
            XCTAssertEqual(online.defenderSpeed, offline.defenderSpeed)
            XCTAssertEqual(online.damage, offline.damage)
            XCTAssertEqual(online.engineVersion, offline.engineVersion)
            XCTAssertEqual(online.rulesVersion, offline.rulesVersion)
            XCTAssertEqual(online.knowledgeVersion, offline.knowledgeVersion)
            XCTAssertEqual(online.request, offline.request)
            XCTAssertEqual(online.response, offline.response)
            try archive(offline, prefix: "case-\(index)-offline")
            try archive(online, prefix: "case-\(index)-online")
        }
    }

    /// 实际 Go 返回 404 时在线请求必须失败，不能回退为成功的本机结果。
    func testHTTPFailureDoesNotFallBackToOffline() async throws {
        let remote = try server(), root = try directory()
        defer { try? FileManager.default.removeItem(at: root) }
        let knowledge = try KnowledgeStore(directory: root.appendingPathComponent("knowledge"), initial: KnowledgePack.bundled())
        let calculator = CalculationService(knowledge: knowledge)
        do {
            _ = try await calculator.calculate(BattleConfiguration.example(), server: remote.appendingPathComponent("missing-test-route"))
            XCTFail("failed remote request silently returned an offline result")
        } catch CalculationFailure.httpStatus(let status) { XCTAssertEqual(status, 404) }
    }
}
