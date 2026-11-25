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

## 后续成熟验收

`event-abi9-20261124/swift-live/swift-live.log`使用正式0.9双语言Core、独立Go/PG，整包 **25/25、零SKIP（16.613秒）**：三项同步、三项真实HTTP知识更新与两项真实在线计算全部通过。在线/离线核对三组完整输入的全部字段、版本及请求/响应原始字节；404明确失败无离线回退。更新测试实际截断连接、取消、损坏/404/超大/重定向后核对旧指针逐字节不变、旧库可查询、完整用户配置及待提交队列保留；真实断点请求`Range: bytes=65536-`获得206并安装成功。

`p5-keep-remote-20261124/swift-sync.log`随后补齐现有`keepRemote`分支，两个独立真实SQLite经Go/PG离线冲突，**同步4/4、零SKIP（0.476秒）**，新增分支0.185秒。采用远端之前，完整本地B与远端A配置、各自knowledge/engine版本、被冻结队列baseRevision1及cursor2均跨重启保留；采用后完整A落地、队列及未决冲突为空，两库再次打开和同步后cursor仍为2，没有回声提交产生新revision。SQLite已解决历史仍保留完整B本地值与A远端值。该次仅运行同步4项，不把它与前次25项相加冒称整包新增通过。

App已接入身份/服务设置、手动同步/状态、冲突双方展示与明确选择。固定`c0b048e`的Apple CI实际iPhone **9/9**、iPad **9/9** UI通过，包括iPhone上传→iPad拉取、同步后重启及在线离线计算。证据`apple-results-c0b048e-20261124/github-native-45404217482.log`；这是两模拟器的真实App/Go/PG链路，未把SDK测试替代为UI验收，也未声称已自动点击App冲突双方选择。

## 范围边界与 HUMAN_PENDING

物理真机的签名、安装与人工体验仍为HUMAN_PENDING；后台被系统终止、断电或安装提交瞬间SIGKILL未实测，不能把已验证的HTTP截断/Task取消扩称这些故障也已通过。冲突两种选择已由真实SDK/SQLite/Go/PG验证，App冲突选择UI尚无独立XCUITest。互联网身份认证仍须由实际可信网关提供，开发header不是认证。

冲突历史已保存，但没有历史恢复界面；同步日志与tombstone尚不压缩或清理，以保留离线恢复资料。旧Vue配置模型与此原生完整配置协议的互通没有在上述同步验收中证明。以上边界不影响已实测的离线修改、双客户端收敛、重复、冲突恢复、删除、中断更新保护及同Core在线离线一致结果；也不代表生产迁移已执行。
