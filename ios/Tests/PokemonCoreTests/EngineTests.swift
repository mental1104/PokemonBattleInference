import Foundation
import XCTest
@testable import PokemonCore

/// 无共享可变成员的跨语言调用测试；异步测试可安全交给 XCTest 执行。
final class EngineTests: XCTestCase, @unchecked Sendable {
    /// - Parameter suffix: request/response 文件后缀。
    /// - Returns: 所有语言共用的冻结 JSON 字节；读取失败使测试抛出。
    private func fixture(_ suffix: String) throws -> Data {
        let root = ProcessInfo.processInfo.environment["PBI_CONTRACT_FIXTURES"].map { URL(fileURLWithPath: $0) }
            ?? URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("tests/vectors")
        return try Data(contentsOf: root.appendingPathComponent("abi-calculations.v1.\(suffix).json"))
    }

    /// 同步调用真实 C++ 静态库，完整核对版本和全部可区分结果。
    func testSharedFixture() throws {
        let actual = try XCTUnwrap(JSONSerialization.jsonObject(with: Engine.calculate(fixture("request"))) as? NSDictionary)
        let expected = try XCTUnwrap(JSONSerialization.jsonObject(with: fixture("response")) as? NSDictionary)
        XCTAssertEqual(actual, expected)
        XCTAssertEqual(Engine.version, "0.2.0")
    }

    /// 明确取消与错误状态不能返回成功结果；错误正文为已复制的 Swift 数据。
    func testErrorsAndCancellation() throws {
        let token = try CancellationToken()
        token.cancel()
        XCTAssertThrowsError(try Engine.calculate(fixture("request"), cancellation: token)) { error in
            XCTAssertEqual((error as? NativeFailure)?.status, 4)
        }
        XCTAssertThrowsError(try Engine.calculate(Data("{".utf8))) { error in
            XCTAssertEqual((error as? NativeFailure)?.status, 1)
            XCTAssertFalse((error as? NativeFailure)?.response.isEmpty ?? true)
        }
    }

    /// 多个独立异步请求共享相同引擎实现，响应字节和版本必须一致。
    func testConcurrentAsyncCalls() async throws {
        let request = try fixture("request")
        let expected = try Engine.calculate(request)
        try await withThrowingTaskGroup(of: Data.self) { group in
            for _ in 0..<32 { group.addTask { try await Engine.calculateAsync(request) } }
            for try await response in group { XCTAssertEqual(response, expected) }
        }
    }

    /// 大批次在后台计算时取消 Swift Task，等待其原生调用完全结束。
    func testRunningTaskCancellation() async throws {
        let operation: [String: Any] = ["kind": "ko", "defender_hp": 3, "rolls": Array(repeating: 1, count: 256)]
        let request = try JSONSerialization.data(withJSONObject: ["schema_version": 1, "operations": Array(repeating: operation, count: 4096)])
        let work = Task.detached { try await Engine.calculateAsync(request) }
        try await Task.sleep(nanoseconds: 2_000_000)
        work.cancel()
        do {
            _ = try await work.value
            XCTFail("cancelled task returned success")
        } catch is CancellationError {
            // await 已等到 native 调用退出，令牌和 buffer 可由各自拥有者安全释放。
        }
    }
}
