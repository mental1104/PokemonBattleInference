# 用户同步表

规范 SQL 唯一来源为 [`server/internal/syncstore/schema.sql`](../../server/internal/syncstore/schema.sql)，由 Go `syncstore.Store.Migrate(ctx)` 嵌入并在事务内执行，避免维护两份漂移的 SQL。只 `CREATE TABLE IF NOT EXISTS` 新增 `pbi_sync_users/entities/changes/operations`，不删除或重写旧配置、知识库或推演任务表。

PostgreSQL 连接由主服务所有并关闭；同步仓库借用连接池。用户身份由主服务 resolver 决定，不读取生产连接作为默认值。验收仅使用显式 `PBI_TEST_POSTGRES_DSN`，每项测试创建唯一 `pbi_sync_test_<nanoseconds>` schema，结束只删除该 schema。跨语言验收使用独立 tmpfs PostgreSQL 容器和两个真实 SQLite 文件。

协议见 [`contracts/sync-v1.md`](../../contracts/sync-v1.md)，当前证据和边界见 [`docs/migration-sync.md`](../../docs/migration-sync.md)。
