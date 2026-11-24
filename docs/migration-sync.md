# P5 用户同步实现与验收

已完成可运行协议和客户端切片：Go HTTP → database/sql + pgx → PostgreSQL 持久化，Swift `SyncClient` → `HTTPSyncTransport` → 真实用户 SQLite。不是内存同步示例；未切换生产数据库或服务。

## 已实现

- 稳定实体 UUID、持久化 operation_id、完整快照、删除 tombstone、用户范围 revision/cursor、幂等回执和修改幂等请求拒绝。
- 用户行事务锁保证变更提交次序；分页按 cursor 增量读取且不会跨过尚未提交的 revision。
- 配置和待提交队列同 SQLite 事务；首次发送冻结请求，ack 不丢弃后续编辑或删除；未发送的后继编辑在确认后更新基线。
- 离线冲突保留本地完整值及远端快照，阻塞该实体；显式选择本地/远端后继续同步，并在数据库保留已解决冲突副本。
- 服务端/用户作用域绑定，避免换用户后沿用旧游标。知识更新与用户库独立，任何同步逻辑均不安装或覆盖知识库。
- ASCII 网络错误和有界请求，身份由外层 resolver 解析。当前 `X-Pokeop-User` 只是可信入口约定，不提供互联网认证。

## 数据迁移

PostgreSQL 仅非破坏性添加同步专属表，规范 SQL 见 `server/internal/syncstore/schema.sql`。没有修改旧任务或配置表。完整快照和回执采用 JSON 类型，支持合法 JSON 的 `\u0000` 和 int64 精度。

用户 SQLite 从 v1 原子升级至 v2：待提交队列新增知识/引擎版本和 sent 字段，新增冲突表与活跃冲突唯一索引。旧队列元信息使用升级时配置中的版本回填，因为 v1 没有逐次保存此元信息；不声称能够重建已经丢失的历史版本。已有配置、操作 UUID、序号、计算记录、设置全部保留。未知新 schema 明确失败，不执行 reset。降级应使用升级前文件副本，不能让旧程序改写 v2 库。

## 实际验证（2026-11-24）

隔离 PG16 临时实例、只读源码挂载、SSD 构建目录和 HDD 报告目录；未读取生产 DSN，未开放宿主服务端口。

Go 真实 PostgreSQL 的 `go test -race -v ./internal/sync...` 通过三项：

1. 仓库重建后的重复提交返回原持久化回执；幂等 ID 复用拒绝、双设备同 revision 冲突及显式恢复、删除、分页、用户隔离、JSON int64 精度与 NUL 字符串。
2. 24 个并发实体提交得到连续且无缺失的 revision，按每页三条增量读取全部收敛。
3. HTTP 未提供用户返回 401；真实提交重试不生成额外 revision，非法分页拒绝。

Swift 整包 13/13、零失败、零跳过（已提供 `PBI_SYNC_TEST_URL`），包含三个同步用例：

1. ack 到达前的新编辑保留，重启重试内容与 operationId 不变，后续队列正确重设基线。
2. 非法增量页整体回滚，服务端/用户作用域绑定跨重启保留。
3. 两个真实 SQLite 设备通过 Go HTTP + PostgreSQL：首响应已提交但未保存 ack → 重启幂等重试 → 双设备离线编辑 → 冲突保留 B 内容 → 人工 keepLocal 恢复 → A/B 完整值及版本相同 → 删除传播 → 重启后两端为空、队列为空、cursor 均为 4。

独立测试服务由 `TestServeSwiftIntegration` 在显式 `PBI_SYNC_TEST_SERVE_ADDR` 下启动，180 秒超时清理；未设置测试环境时该辅助服务测试明确跳过，不在普通测试中常驻。Swift 跨语言用例缺少显式 URL 时也明确跳过，因此普通 Swift 绿灯不能替代上述实际连接证据。

本次验收日志保存在 NAS HDD 的 `/volume1/homes/mental1104/Backup/PokemonBattleInference/migration-p5-sync-20261124/`：`go-sync.log`、`go-sync-vet.log`、`go-swift-server.log`、`swift-real-postgres.log`。

## 仍待完成

当前交付不等于产品 P5/P6 全部验收：App 尚需接入同步用户标识、同步操作/状态和冲突选择界面；真实 iPhone/iPad 双设备、后台断网/恢复体验仍需 Apple 环境验证。互联网使用前需实际身份认证，不能把可任意设置的 header 当成安全边界。冲突历史已有存储但未有历史恢复界面；同步日志和 tombstone 尚无压缩/保留策略，避免过早清理破坏离线恢复。旧 Vue 配置模型与此完整原生配置协议的互通需要单独明确迁移合同。
