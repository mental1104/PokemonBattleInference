-- 只追加同步专属表，不修改知识库、历史任务或用户原表。调用者负责事务/连接生命周期。
CREATE TABLE IF NOT EXISTS pbi_sync_users (
    user_id TEXT PRIMARY KEY,
    cursor BIGINT NOT NULL DEFAULT 0 CHECK (cursor >= 0)
);
CREATE TABLE IF NOT EXISTS pbi_sync_entities (
    user_id TEXT NOT NULL REFERENCES pbi_sync_users(user_id),
    entity_id UUID NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    -- JSON 保留 Swift/SQLite 支持的 \u0000；JSONB 会拒绝这种合法 JSON 字符串。
    snapshot JSON NOT NULL,
    PRIMARY KEY (user_id, entity_id)
);
-- 用户行锁串行分配游标，避免 BIGSERIAL 先分配后提交导致拉取永久漏项。
CREATE TABLE IF NOT EXISTS pbi_sync_changes (
    user_id TEXT NOT NULL REFERENCES pbi_sync_users(user_id),
    cursor BIGINT NOT NULL,
    snapshot JSON NOT NULL,
    PRIMARY KEY (user_id, cursor)
);
CREATE TABLE IF NOT EXISTS pbi_sync_operations (
    user_id TEXT NOT NULL REFERENCES pbi_sync_users(user_id),
    operation_id UUID NOT NULL,
    request_hash TEXT NOT NULL,
    result JSON NOT NULL,
    PRIMARY KEY (user_id, operation_id)
);
