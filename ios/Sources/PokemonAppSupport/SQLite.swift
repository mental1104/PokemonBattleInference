import CSQLite
import Foundation

/// 固定绑定值，禁止把用户搜索/配置拼接进 SQL。
enum SQLValue { case integer(Int64), text(String), blob(Data), null }

/// 连接使用 FULLMUTEX，实际操作仍由所属 actor 串行调用。
/// unchecked Sendable 仅保证连接可随 actor 生命周期释放，不暴露给 UI 或跨 actor 任意执行。
final class SQLiteConnection: @unchecked Sendable {
    fileprivate let handle: OpaquePointer

    /// - Parameters:
    ///   - url: 明确的知识库/用户库文件；不会删除或重置既有文件。
    ///   - readOnly: 知识库强制只读，用户库才允许创建与写入。
    init(url: URL, readOnly: Bool) throws {
        var pointer: OpaquePointer?
        let flags = (readOnly ? SQLITE_OPEN_READONLY : SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE) | SQLITE_OPEN_FULLMUTEX
        let code = sqlite3_open_v2(url.path, &pointer, flags, nil)
        guard code == SQLITE_OK, let pointer else {
            let message = pointer.map { String(cString: sqlite3_errmsg($0)) } ?? "cannot open SQLite database"
            if let pointer { sqlite3_close_v2(pointer) }
            throw StorageFailure.database(message)
        }
        handle = pointer
        sqlite3_busy_timeout(handle, 5_000)
        try execute("PRAGMA foreign_keys=ON")
    }
    /// 所有 statement 强持有本连接，最后一个引用释放后再关闭，避免悬空句柄。
    deinit { sqlite3_close_v2(handle) }

    /// sql 为固定语句，bindings 为独立值；只接受执行完成，不把 ROW 当作写入成功。
    func execute(_ sql: String, _ bindings: [SQLValue] = []) throws {
        let statement = try SQLiteStatement(connection: self, sql: sql, bindings: bindings)
        guard sqlite3_step(statement.handle) == SQLITE_DONE else { throw StorageFailure.database(String(cString: sqlite3_errmsg(handle))) }
    }

    /// sql 为固定查询，bindings 单独绑定，decode 在同一同步调用内读取行；返回独立值数组。
    func rows<Value>(_ sql: String, _ bindings: [SQLValue] = [], decode: (SQLiteStatement) throws -> Value) throws -> [Value] {
        let statement = try SQLiteStatement(connection: self, sql: sql, bindings: bindings)
        var result: [Value] = []
        while true {
            let code = sqlite3_step(statement.handle)
            if code == SQLITE_DONE { return result }
            guard code == SQLITE_ROW else { throw StorageFailure.database(String(cString: sqlite3_errmsg(handle))) }
            result.append(try decode(statement))
        }
    }

    /// operation 在 BEGIN IMMEDIATE 内同步执行；任一步失败回滚并保留原始错误。
    func transaction<Value>(_ operation: () throws -> Value) throws -> Value {
        try execute("BEGIN IMMEDIATE")
        do { let value = try operation(); try execute("COMMIT"); return value }
        catch { try? execute("ROLLBACK"); throw error }
    }
}

/// 单条 prepared statement 的 RAII 所有者，绑定值交由 SQLite 复制。
final class SQLiteStatement {
    fileprivate let handle: OpaquePointer
    private let connection: SQLiteConnection

    /// connection 在整个 statement 生命周期内强持有；sql 与 bindings 不保留外部指针。
    init(connection: SQLiteConnection, sql: String, bindings: [SQLValue]) throws {
        var pointer: OpaquePointer?
        guard sqlite3_prepare_v2(connection.handle, sql, -1, &pointer, nil) == SQLITE_OK, let pointer else {
            throw StorageFailure.database(String(cString: sqlite3_errmsg(connection.handle)))
        }
        handle = pointer; self.connection = connection
        // 全部存储属性已初始化，后续抛出由 deinit finalize，不能手工再次释放。
        for (offset, value) in bindings.enumerated() {
                let index = Int32(offset + 1)
                let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
                let code: Int32
                switch value {
                case .integer(let number): code = sqlite3_bind_int64(handle, index, number)
                case .text(let text):
                    guard text.utf8.count <= Int(Int32.max) else { throw StorageFailure.invalidData("SQLite text is too large") }
                    code = text.withCString { sqlite3_bind_text(handle, index, $0, Int32(text.utf8.count), transient) }
                case .blob(let data):
                    guard data.count <= Int(Int32.max) else { throw StorageFailure.invalidData("SQLite blob is too large") }
                    code = data.withUnsafeBytes { sqlite3_bind_blob(handle, index, $0.baseAddress, Int32($0.count), transient) }
                case .null: code = sqlite3_bind_null(handle, index)
                }
                guard code == SQLITE_OK else { throw StorageFailure.database("cannot bind SQLite value") }
        }
    }
    /// 离开作用域即归还 statement；connection 直到 finalize 完成后才释放。
    deinit { sqlite3_finalize(handle) }
    /// column 为零起始列；返回非空整数，固定 schema 中不得把 NULL 读成 0。
    func integer(_ column: Int32) throws -> Int64 {
        guard sqlite3_column_type(handle, column) == SQLITE_INTEGER else { throw StorageFailure.invalidData("expected an integer SQLite column") }
        return sqlite3_column_int64(handle, column)
    }
    /// column 为零起始列；SQL NULL 返回 nil，其余必须是整数。
    func optionalInteger(_ column: Int32) throws -> Int64? {
        if sqlite3_column_type(handle, column) == SQLITE_NULL { return nil }
        return try integer(column)
    }
    /// column 为零起始列；复制非空 UTF-8 字符串，不返回 SQLite 借用指针。
    func text(_ column: Int32) throws -> String {
        guard sqlite3_column_type(handle, column) == SQLITE_TEXT, let bytes = sqlite3_column_text(handle, column) else { throw StorageFailure.invalidData("expected a text SQLite column") }
        let buffer = UnsafeBufferPointer(start: bytes, count: Int(sqlite3_column_bytes(handle, column)))
        guard let value = String(bytes: buffer, encoding: .utf8) else { throw StorageFailure.invalidData("SQLite text is not UTF-8") }
        return value
    }
    /// column 为零起始列；返回独立 BLOB 数据，允许空 BLOB，拒绝 NULL。
    func data(_ column: Int32) throws -> Data {
        guard sqlite3_column_type(handle, column) == SQLITE_BLOB else { throw StorageFailure.invalidData("expected a blob SQLite column") }
        let count = Int(sqlite3_column_bytes(handle, column))
        guard let bytes = sqlite3_column_blob(handle, column) else { return Data() }
        return Data(bytes: bytes, count: count)
    }
}
