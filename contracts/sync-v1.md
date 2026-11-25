# 用户配置同步协议 v1

同步对象是完整 `BattleConfiguration`、知识/引擎版本及删除标记。知识目录及知识包不进入用户同步库。服务端 PostgreSQL 是持久化权威，设备 SQLite 保存离线编辑、待提交队列、增量游标和可恢复冲突。

## 身份与版本

端点为 `POST /v1/sync` 和 `GET /v1/sync`。主服务提供 `UserResolver`，成功解析的用户标识决定所有 SQL 的作用域。当前部署兼容可信入口提供的 `X-Pokeop-User`，缺少时返回 401；它本身不是互联网认证。请求正文或 query 不能选择用户。不同用户可以有相同 entity/operation UUID，彼此不可见。

协议 `schema_version=1`。Swift 身份字段 UUID 编码为小写，配置内 UUID 大小写均可解码。revision/cursor 使用非负、有符号 64 位整数；新实体基线为 0。时间戳不参与冲突判定。

## 提交一条冻结操作

单次 POST 提交一条完整操作；设备在保存后第一次发送前将其标记为已发送，此后超时、重启和重复请求都复用同一个 ID 和原内容。

| 字段 | 内容 |
|---|---|
| schema_version | 固定 1 |
| operation_id | 本次编辑的稳定 UUID，禁止复用于其他内容 |
| entity_id | 用户配置的稳定 UUID |
| base_revision | 该编辑依赖的服务端 revision，首次创建为 0 |
| local_sequence | 本设备该实体递增序号，至少 1 |
| kind | `upsert` 或 `delete` |
| configuration | 完整配置 JSON，包含与 entity_id 相同的 id 及非空 name；删除仍保留内容 |
| knowledge_version / engine_version | 该次编辑对应的版本，各最多 256 字节 |

正文上限 2 MiB，单配置上限 1 MiB。服务端保存完整 JSON；不要求历史知识版本仍在当前知识目录中。原始 JSON 数字在规范化时使用 `json.Number`，不经过 float64。PostgreSQL 使用 JSON 类型而非 JSONB，保留 SQLite/Swift 支持的 `\u0000` 字符串。

返回 200 的结果包含 `operation_id`、`status`、`current`：

- `accepted`：base_revision 等于当前 revision。一次事务保存实体、完整增量、用户 cursor 和幂等回执。current 是提交后快照。
- `conflict`：base_revision 不同。实体和 cursor 不变，回执持久化；current 是冲突时远端完整快照，实体不存在则为 null。客户端保留本地值和待提交请求，并将该实体阻塞等待明确选择。

快照字段为 `entity_id`、`revision`、`deleted`、`configuration`、`knowledge_version`、`engine_version`。同一 operation_id 的相同请求永远返回已保存的原回执，包括原冲突；改变任意字段返回 409 `operation_reused`。普通错误使用 ASCII code，不泄露 SQL/载荷。输入错误 400、身份错误 401、数据库暂不可用 503、方法不支持 405。

客户端收到 accepted 后只删除该 operation_id。若用户在等待响应时再次编辑，ack 只提升其 server_revision，保留新 payload、local_sequence 和后续队列；只对尚未发送的后续操作更新 base_revision，绝不修改已经发送的请求内容。

## 拉取与删除

`GET /v1/sync?after=<cursor>&limit=<1…200>` 返回 `changes`、`next_cursor`、`has_more`。默认 limit=100；Swift 使用 10，以将单页完整快照响应约束在其 16 MiB 边界内。changes 按 revision 严格递增，next_cursor 为本页最后一项；空页保持请求游标。删除以同一实体的完整 tombstone 增量传播，不物理移除历史。

服务端在同一用户行上加事务锁后分配 cursor，锁覆盖去重、revision 比较和所有写入。因此 cursor 次序等于该用户的提交次序，避免独立 BIGSERIAL 分配早于提交而让客户端永久跳过晚提交记录。

客户端在同一个 SQLite 事务应用整页及 cursor。已处理旧 revision 幂等跳过；干净配置直接替换或设 tombstone，脏配置建立冲突且保持本地完整值。非法顺序或 next_cursor 导致整页回滚。首次同步绑定服务端 URL 与用户标识；不同作用域必须使用独立用户库，不能借用旧 revision/cursor。

## 冲突恢复

`ConfigurationStore.syncConflicts()` 返回本地完整记录与当前已知远端快照。`resolveConflict(entityId:resolution:)` 要求明确 `.keepLocal` 或 `.keepRemote`。

- keepLocal：归档冲突、删除旧队列、用远端 revision 为基线创建新 operation_id，保留用户当前完整内容和删除意图。
- keepRemote：归档当前本地完整值，删除该实体队列，采用完整远端或远端删除状态。

冲突历史留在 SQLite `sync_conflicts` 的 resolved 行中，未提供历史回放 UI。恢复后的再次并发编辑仍可产生新冲突，不静默覆盖另一设备。
