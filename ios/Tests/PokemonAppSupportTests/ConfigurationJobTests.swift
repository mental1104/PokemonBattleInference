import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import PokemonAppSupport

/// 对齐原公开技能池合同；独立真实服务验收在显式URL下运行，单纯解码测试不冒充HTTP闭环。
final class ConfigurationJobTests: XCTestCase, @unchecked Sendable {
    /// 返回原合同的真实单配置对命令；双方同等级，结果由正式Core在显式图预算内执行。
    private func command() -> ConfigurationJobCommand {
        ConfigurationJobCommand(attacker: JobMovePool(fixed: JobFixedPokemon(pokemonId: 212, level: 50, statProfileId: "max_atk_plus", abilityIdentifier: "technician"), candidateMoveIds: [404]),
            defender: JobMovePool(fixed: JobFixedPokemon(pokemonId: 149, level: 50, statProfileId: "max_hp_def_plus", abilityIdentifier: "multiscale"), candidateMoveIds: [337]),
            execution: JobExecutionBudget(processCount: 1, queueDepth: 1, maxNodesPerPair: 20_000, maxEdgesPerPair: 80_000, maxTurns: 100))
    }

    /// 请求维度/规则轴/策略/null保持原HTTP语义，不能发送 Core operations 或随意改变 stat profile。
    func testOriginalCommandEncodingAndExplicitNull() throws {
        let bytes = try ContractJSON.encoder().encode(command())
        let value = try JSONDecoder().decode(EncodedCommand.self, from: bytes)
        XCTAssertEqual(value.contract_version, "one-on-one-move-pool.v1")
        XCTAssertEqual(value.calculation_revision, "battle-inference.summary-exploration.v2")
        XCTAssertEqual(value.dimensions.moves, "candidate_pool"); XCTAssertEqual(value.dimensions.special_mechanics, "disabled")
        XCTAssertEqual(value.attacker.fixed.stat_profile_id, "max_atk_plus")
        XCTAssertEqual(value.attacker.candidate_move_ids, [404]); XCTAssertEqual(value.defender.candidate_move_ids, [337])
        let text = String(decoding: bytes, as: UTF8.self)
        XCTAssertTrue(text.contains("\"form_id\":null")); XCTAssertTrue(text.contains("\"item_identifier\":null"))
        XCTAssertFalse(text.contains("\"operations\"")); XCTAssertFalse(text.contains("\"ivs\""))
    }

    /// 摘要保留任意长度精确分母/nullable字段和不同终态；decimal不能反向替代原分数。
    func testCaseSummaryKeepsExactProbabilityAndFailure() throws {
        let bytes = Data(#"{"job_id":"job-1","offset":0,"limit":100,"total":2,"next_cursor":null,"items":[{"configuration_id":"canonical-1","sequence_no":0,"status":"succeeded","attacker_pokemon_id":212,"defender_pokemon_id":149,"attacker_move_ids":[404],"defender_move_ids":[337],"attacker_win_probability":{"numerator":"1","denominator":"100000000000000000000000000000000001","decimal":1e-35},"defender_win_probability":{"numerator":"100000000000000000000000000000000000","denominator":"100000000000000000000000000000000001","decimal":1},"draw_probability":{"numerator":"0","denominator":"1","decimal":0},"expected_turns_kind":"finite","expected_turns":"4/3","node_count":23,"edge_count":41,"explanation":{"summary":"result","items":[1,null,true]},"failure_code":null,"diagnostic":null,"attempt_count":1},{"configuration_id":"canonical-2","sequence_no":1,"status":"truncated","attacker_pokemon_id":212,"defender_pokemon_id":149,"attacker_move_ids":[404],"defender_move_ids":[337],"attacker_win_probability":null,"defender_win_probability":null,"draw_probability":null,"expected_turns_kind":null,"expected_turns":null,"node_count":17,"edge_count":29,"explanation":null,"failure_code":"graph_node_limit","diagnostic":"resource limit","attempt_count":2}]}"#.utf8)
        let value = try ContractJSON.decoder().decode(ConfigurationJobPage.self, from: bytes)
        XCTAssertEqual(value.items.count, 2); XCTAssertNil(value.nextCursor)
        XCTAssertEqual(value.items[0].attackerWinProbability?.text, "1/100000000000000000000000000000000001")
        XCTAssertEqual(value.items[0].expectedTurnsKind, .finite); XCTAssertEqual(value.items[0].expectedTurns, "4/3")
        XCTAssertEqual(value.items[0].explanation?["items"], .array([.number(1), .null, .bool(true)]))
        XCTAssertEqual(value.items[1].status, .truncated); XCTAssertNil(value.items[1].attackerWinProbability)
        XCTAssertEqual(value.items[1].failureCode, "graph_node_limit"); XCTAssertEqual(value.items[1].attemptCount, 2)
    }

    /// 显式null才代表旧来源未知；未知schema、缺字段或不成对版本必须报协议错误而非回填本地版本。
    func testExecutionMetadataExplicitUnknownAndValidation() throws {
        let decoder = ContractJSON.decoder()
        XCTAssertNil(try decoder.decode(ConfigurationJobMetadataEnvelope.self, from: Data(#"{"schema_version":1,"metadata":null}"#.utf8)).metadata)
        let metadata = #"{"schema_version":1,"engine_version":null,"rules_version":null,"input_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","input_schema_version":1,"operation":"fixed_battle","observer":"attacker"}"#
        let value = try decoder.decode(ConfigurationJobMetadataEnvelope.self, from: Data("{\"schema_version\":1,\"metadata\":\(metadata)}".utf8))
        XCTAssertNil(value.metadata?.engineVersion); XCTAssertNil(value.metadata?.rulesVersion)
        XCTAssertEqual(value.metadata?.inputSha256, String(repeating: "a", count: 64))
        for text in [#"{"schema_version":2,"metadata":null}"#, #"{"schema_version":1}"#,
                     "{\"schema_version\":1,\"metadata\":\(metadata.replacingOccurrences(of: "\"engine_version\":null", with: "\"engine_version\":\"unexpected\""))}",
                     "{\"schema_version\":1,\"metadata\":\(metadata.replacingOccurrences(of: String(repeating: "a", count: 64), with: "invalid"))}"] {
            XCTAssertThrowsError(try decoder.decode(ConfigurationJobMetadataEnvelope.self, from: Data(text.utf8)))
        }
    }

    /// 错误地址/路径和页界必须在发出任何网络请求前失败，不让任务ID变成任意路由。
    func testHTTPBoundaryRejectsInvalidInputs() async throws {
        for text in ["file:///tmp", "https://example.invalid/?private=x", "https://example.invalid/#fragment"] {
            do { _ = try ConfigurationJobClient(serverURL: URL(string: text)!); XCTFail("invalid job endpoint was accepted") }
            catch ConfigurationJobFailure.invalidEndpoint { }
        }
        let client = try ConfigurationJobClient(serverURL: URL(string: "http://127.0.0.1:1")!)
        for id in ["", "../job", "job/id", "..", "job\n"] {
            do { _ = try await client.status(id); XCTFail("invalid job identifier was accepted") }
            catch ConfigurationJobFailure.invalidInput { }
        }
        do { _ = try await client.results("job", limit: 501); XCTFail("invalid page was accepted") }
        catch ConfigurationJobFailure.invalidInput { }
        for pair in ["", ".", "..", "pair\n"] {
            do { _ = try await client.executionMetadata("job", configurationId: pair); XCTFail("invalid metadata identifier was accepted") }
            catch ConfigurationJobFailure.invalidInput { }
        }
        do { _ = try await client.submit(command(), idempotencyKey: "invalid\nkey"); XCTFail("invalid request key was accepted") }
        catch ConfigurationJobFailure.invalidInput { }
    }

    /// 真HTTP提交→PG/daemon→完整结果，并以同一幂等键再次提交核对返回同一任务；未提供服务明确SKIP。
    func testLiveGoCreatePollResultAndIdempotency() async throws {
        guard let text = ProcessInfo.processInfo.environment["PBI_CONFIGURATION_JOB_TEST_URL"], let url = URL(string: text) else {
            throw XCTSkip("PBI_CONFIGURATION_JOB_TEST_URL is required for actual Go job acceptance")
        }
        let client = try ConfigurationJobClient(serverURL: url), input = command(), key = "swift-job-\(UUID().uuidString)"
        let created = try await client.submit(input, idempotencyKey: key)
        XCTAssertEqual(created.status, "pending"); XCTAssertEqual(created.submittedConfigurationPairs, 1)
        let repeated = try await client.submit(input, idempotencyKey: key); XCTAssertEqual(repeated.jobId, created.jobId)
        var status = try await client.status(created.jobId)
        for _ in 0..<600 {
            if status.status.terminal { break }
            try await Task.sleep(for: .milliseconds(100)); status = try await client.status(created.jobId)
        }
        XCTAssertEqual(status.status, .completed); XCTAssertEqual(status.counts.succeeded, 1)
        XCTAssertEqual(status.rulesetId, input.rulesetId); XCTAssertEqual(status.calculationRevision, input.calculationRevision)
        let page = try await client.results(created.jobId)
        XCTAssertEqual(page.items.count, 1); XCTAssertEqual(page.items[0].status, .succeeded)
        let recordedMetadata = try await client.executionMetadata(created.jobId, configurationId: page.items[0].configurationId)
        let metadata = try XCTUnwrap(recordedMetadata)
        // 实际来源来自同服务的独立子进程信封；不读取解释、提交admission或本地SDK版本作后备。
        let coreProbe = Data(#"{"schema_version":1,"operations":[{"kind":"hp","base":91,"iv":31,"ev":0,"level":50}]}"#.utf8)
        var probeRequest = URLRequest(url: url.appendingPathComponent("v1/core/calculate")); probeRequest.httpMethod = "POST"
        probeRequest.setValue("application/json", forHTTPHeaderField: "Content-Type"); probeRequest.httpBody = coreProbe
        let (probeBytes, probeResponse) = try await URLSession.shared.data(for: probeRequest)
        XCTAssertEqual((probeResponse as? HTTPURLResponse)?.statusCode, 200)
        let actual = try JSONDecoder().decode(ExecutionVersionProbe.self, from: probeBytes)
        XCTAssertEqual(metadata.engineVersion, actual.engine_version); XCTAssertEqual(metadata.rulesVersion, actual.rules_version)
        XCTAssertEqual(metadata.schemaVersion, 1); XCTAssertEqual(metadata.inputSchemaVersion, 1)
        XCTAssertEqual(metadata.inputSha256.count, 64); XCTAssertEqual(metadata.operation, "fixed_battle"); XCTAssertEqual(metadata.observer, "attacker")
        do { _ = try await client.executionMetadata(created.jobId, configurationId: "missing-case"); XCTFail("missing case was treated as unknown provenance") }
        catch ConfigurationJobFailure.httpStatus(let code, _) { XCTAssertEqual(code, 404) }
        // 该冻结输入的实际.7 Core/PG响应已独立取证，保护完整概率/期望结果不被客户端舍入。
        XCTAssertEqual(page.items[0].attackerWinProbability?.text, "0"); XCTAssertEqual(page.items[0].defenderWinProbability?.text, "1")
        XCTAssertEqual(page.items[0].drawProbability?.text, "0"); XCTAssertEqual(page.items[0].expectedTurnsKind, .finite)
        XCTAssertEqual(page.items[0].expectedTurns, "5/1")
        XCTAssertGreaterThan(page.items[0].nodeCount, 0); XCTAssertGreaterThan(page.items[0].edgeCount, 0)
        let issues = try await client.issues(created.jobId); XCTAssertTrue(issues.items.isEmpty)
        let terminalCancellation = try await client.cancel(created.jobId); XCTAssertEqual(terminalCancellation.status, .completed)
        // 保存真实输入/完整服务响应对象，方便与P3 HTTP/PG证据关联，不把合同解码样本当作真实结果。
        if let path = ProcessInfo.processInfo.environment["PBI_CONFIGURATION_JOB_REPORT_DIRECTORY"] {
            let directory = URL(fileURLWithPath: path).appendingPathComponent(created.jobId)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try ContractJSON.encoder().encode(input).write(to: directory.appendingPathComponent("request.json"))
            try Data(created.jobId.utf8).write(to: directory.appendingPathComponent("job-id.txt"))
            // 独立溯源及版本探针保留真实HTTP原文；配置ID按单路径段编码，与SDK同样经过正式路由。
            var allowed = CharacterSet.urlPathAllowed; allowed.remove(charactersIn: "/%?#\\")
            var metadataURL = URLComponents(url: url.appendingPathComponent("v1/inference/configuration-jobs/\(created.jobId)/results"), resolvingAgainstBaseURL: false)!
            metadataURL.percentEncodedPath += "/\(page.items[0].configurationId.addingPercentEncoding(withAllowedCharacters: allowed)!)/metadata"
            let (metadataBytes, metadataResponse) = try await URLSession.shared.data(from: metadataURL.url!)
            XCTAssertEqual((metadataResponse as? HTTPURLResponse)?.statusCode, 200)
            try metadataBytes.write(to: directory.appendingPathComponent("execution-metadata.json"))
            try probeBytes.write(to: directory.appendingPathComponent("core-version-probe.json"))
            // 独立HTTP再次读取不可变终态，保留原始响应而非只保存重编码后的DTO。
            for suffix in ["", "/results", "/issues"] {
                let endpoint = url.appendingPathComponent("v1/inference/configuration-jobs/\(created.jobId)\(suffix)")
                let (data, response) = try await URLSession.shared.data(from: endpoint)
                XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
                try data.write(to: directory.appendingPathComponent(suffix.isEmpty ? "status.json" : String(suffix.dropFirst()) + ".json"))
            }
        }
    }

    /// 观察正式daemon已经报告running后才请求取消，并要求真正cancelled终态，不用终态取消冒充运行中取消。
    func testLiveGoCancelRunningTask() async throws {
        guard let text = ProcessInfo.processInfo.environment["PBI_CONFIGURATION_JOB_TEST_URL"], let url = URL(string: text) else {
            throw XCTSkip("PBI_CONFIGURATION_JOB_TEST_URL is required for actual Go running cancellation acceptance")
        }
        let client = try ConfigurationJobClient(serverURL: url)
        var input = command()
        // 已由正式服务strict+202验证的75case合法池，提供真实取消窗口，不给计算器注入测试延迟。
        input.attacker.candidateMoveIds = [17, 404, 806, 814, 851]
        input.defender.candidateMoveIds = [17, 21, 56, 337, 401, 406]
        let created = try await client.submit(input, idempotencyKey: "swift-running-cancel-\(UUID().uuidString)")
        XCTAssertEqual(created.submittedConfigurationPairs, 75)
        var status = try await client.status(created.jobId)
        for _ in 0..<300 {
            if status.status == .running || status.status.terminal { break }
            try await Task.sleep(for: .milliseconds(20)); status = try await client.status(created.jobId)
        }
        XCTAssertEqual(status.status, .running, "Cancellation must target a daemon-owned running task")
        let acknowledgement = try await client.cancel(created.jobId)
        XCTAssertTrue(acknowledgement.cancellationRequested)
        for _ in 0..<600 {
            status = try await client.status(created.jobId)
            if status.status.terminal { break }
            try await Task.sleep(for: .milliseconds(50))
        }
        XCTAssertEqual(status.status, .cancelled)
        XCTAssertEqual(status.counts.completed, status.counts.total)
        // 取消时尚未交给子进程的case没有执行来源。实际HTTP null应保留nil，不从本地或准入版本补值。
        let cancelledPage = try await client.results(created.jobId)
        var unexecutedCase: String?
        for item in cancelledPage.items where item.status == .cancelled {
            if try await client.executionMetadata(created.jobId, configurationId: item.configurationId) == nil { unexecutedCase = item.configurationId; break }
        }
        XCTAssertNotNil(unexecutedCase, "A pending case cancelled before execution must retain explicit null metadata")
        if let path = ProcessInfo.processInfo.environment["PBI_CONFIGURATION_JOB_REPORT_DIRECTORY"] {
            let output = URL(fileURLWithPath: path).appendingPathComponent(created.jobId)
            try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
            try ContractJSON.encoder().encode(input).write(to: output.appendingPathComponent("request.json"))
            let (data, response) = try await URLSession.shared.data(from: url.appendingPathComponent("v1/inference/configuration-jobs/\(created.jobId)"))
            XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
            try data.write(to: output.appendingPathComponent("cancelled-status.json"))
        }
    }
}

/// 独立读取子进程真实信封的版本；不复用metadata DTO解码，防止共享字段映射错误自证。
private struct ExecutionVersionProbe: Decodable { let engine_version: String; let rules_version: String }

/// 独立读取请求JSON边界；字段使用原snake_case，避免借同一编码模型自证字段映射。
private struct EncodedCommand: Decodable {
    let contract_version: String
    let calculation_revision: String
    let dimensions: Dimensions
    let attacker: Pool
    let defender: Pool
    /// 请求维度在HTTP上的固定字段。
    struct Dimensions: Decodable { let moves: String; let special_mechanics: String }
    /// 请求侧的原候选数组与固定配置。
    struct Pool: Decodable { let fixed: Fixed; let candidate_move_ids: [Int64] }
    /// 请求侧的公开模板引用。
    struct Fixed: Decodable { let stat_profile_id: String }
}
