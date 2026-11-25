import CPokemonCore
import Foundation

/// 原生错误副本，响应 Data 由 Swift 独立拥有，不借用 C 的缓冲区。
public struct NativeFailure: Error, Sendable {
    public let status: Int32
    public let response: Data
}

/// 单向原子取消令牌。unchecked Sendable 仅适用于 C 层已明确并发安全的 cancel 操作。
/// 每次 calculate 都用 withExtendedLifetime 保持强引用，避免原生读取期间释放。
public final class CancellationToken: @unchecked Sendable {
    fileprivate let pointer: OpaquePointer

    /// 创建新的未取消令牌；分配失败抛出 NativeFailure，不取得其他资源。
    public init() throws {
        guard let pointer = pbi_v1_cancel_token_create() else {
            throw NativeFailure(status: 3, response: Data())
        }
        self.pointer = pointer
    }

    /// 最后一个 Swift 强引用释放后销毁原生令牌，不允许暴露指针给调用者。
    deinit { pbi_v1_cancel_token_destroy(pointer) }

    /// 永久取消所有借用此令牌的计算，可从任意线程调用，不会重置令牌。
    public func cancel() { pbi_v1_cancel_request(pointer) }
}

/// 纯原生桥接入口；不在 Swift 中重写能力值、伤害或概率规则。
public enum Engine {
    /// 返回 Core 静态引擎版本的 Swift 副本。
    public static var version: String { String(cString: pbi_v1_engine_version()) }

    /// 同步计算完整 JSON 批次；重计算调用方应使用 calculateAsync。
    /// - Parameters:
    ///   - request: UTF-8 JSON 字节，读取期间不修改，不跨调用保留其指针。
    ///   - cancellation: 可空的单向令牌，本次计算结束前保持强引用。
    /// - Returns: 拥有独立字节的响应 Data；非成功状态抛出带正文的 NativeFailure。
    public static func calculate(_ request: Data, cancellation: CancellationToken? = nil) throws -> Data {
        var output = pbi_buffer_v1(data: nil, size: 0)
        defer { pbi_v1_buffer_release(&output) }
        let status = withExtendedLifetime(cancellation) {
            request.withUnsafeBytes { bytes in
                pbi_v1_compute(bytes.bindMemory(to: UInt8.self).baseAddress, bytes.count,
                               cancellation?.pointer, &output)
            }
        }
        let response = output.data.map { Data(bytes: $0, count: output.size) } ?? Data()
        guard status == PBI_OK_V1 else {
            throw NativeFailure(status: Int32(status.rawValue), response: response)
        }
        return response
    }

    /// 在 detached task 中调用同一 Core，不阻塞 MainActor；Task 取消传播到 C 原子令牌。
    /// - Parameter request: 调用方拥有的 JSON Data 值，不进行规则计算。
    /// - Returns: 完整响应；取消抛出 CancellationError，其他错误保持 NativeFailure。
    public static func calculateAsync(_ request: Data) async throws -> Data {
        try Task.checkCancellation()
        let token = try CancellationToken()
        return try await withTaskCancellationHandler {
            do {
                let result = try await Task.detached { try calculate(request, cancellation: token) }.value
                try Task.checkCancellation()
                return result
            } catch let failure as NativeFailure where failure.status == 4 {
                throw CancellationError()
            }
        } onCancel: {
            token.cancel()
        }
    }
}
