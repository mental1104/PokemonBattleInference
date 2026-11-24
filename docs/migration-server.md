# P3 Go 服务迁移

2026-11-24 当前检查点：已迁移原 41 项 API 中的 **16 项读取/配置/图片 API**，并接入 P5 同步处理器；复杂推演任务 API 尚未替换。原 Python 生产服务、生产库及部署均未改动。

| 范围 | 实现与真实验证 |
| --- | --- |
| 配置 7 项 | GET 列表、GET 性格、POST 创建、PUT 更新、DELETE 软删除、POST hidden/order；使用原两张运行表、可信租户 header、七项内置定义、25 性格、EV/IV 约束及 UTF-8 不可变快照。真实 PG 验证跨租户禁止更新/删除、隐藏、排序失败整体回滚、重复迁移和 handler 重建后持久化、软删除后快照仍可解释。 |
| 知识 6 项 | Pokémon 搜索/详情/特性/招式分页、道具、模板。使用原 poke_champion 物化视图及历史特性 SQL；全量固定 submodule CSV 实际初始化后验证快龙 91/134 种族值、dragon/flying、中文搜索、历史特性/道具、去重总数/稳定分页/完整 18 属性筛选。 |
| 图片 3 项 | Pokémon/type/item BYTEA 读取、原选择视图与固定路径、强/弱 ETag 及 304；实际 PNG 字节逐字节比较，验证不存在时 404。没有引入文件系统任意下载或在线图片 fallback。 |
| PostgreSQL | pgx/v5/stdlib + database/sql。显式 DSN、连接池；原六张运行表采用 additive 初始化，一笔事务/advisory lock、不 DROP、不重建已有数据；二次运行保持记录。尚未迁移 Go 自有 raw CSV 导入及物化视图管理器。 |
| P5 接线 | NewServer(db) 挂 GET/POST /v1/sync；主进程显式迁移时调用 syncstore.Migrate；本轮真实 PG 重跑 P5 三项事务/并发/HTTP 测试通过。Swift 测试专用服务入口缺少 PBI_SYNC_TEST_SERVE_ADDR 时有一个预期 SKIP，不能记成跨语言 PASS；P5 另有独立跨语言验收。 |
| 子进程边界 | pbi-core-worker 从 stdin 接收单批 JSON，stdout 输出唯一 Core ABI 响应。workerprocess.Execute 使用绝对可执行路径、无 shell、32 MiB 输出上限、ctx 取消回收、ABI 错误类别与信号崩溃区分。实际独立 native 子进程运行完整冻结向量、未知操作及取消；自有子进程 SIGKILL 不杀死父进程。尚未接入 PG 任务 coordinator/lease。 |

## 运行边界

- 无 PBI_POSTGRES_DSN：继续提供 Core-only `/healthz`、`/v1/core/calculate`，不创建假仓库。
- 显式 PBI_POSTGRES_DSN：启用以上数据库路由；仅 PBI_MIGRATE=1 时执行增量运行表与 P5 表初始化。默认不迁移、不导入、不刷新。
- `X-Pokeop-Tenant` 沿用旧可信网关注入约定，开发默认 default-tenant；它不是认证。P5 的 `X-Pokeop-User` 必填，用户不能在正文或 query 指定身份。生产开放前仍需在真正认证网关建立可信边界。
- 所有数据库异常对外返回稳定 503，不输出连接字符串或 SQL。未迁计算端点没有返回演示结果，也没有调用 Python 在线运行时。

## 验证证据

路径：`/volume1/homes/mental1104/Backup/PokemonBattleInference/p3-server-20261124/`。

- `integration/catalog-initialization.log`：通用测试 PG 的 512 MiB tmpfs 在刷新原 pokemon_catalog_zh_mv 时真实 DiskFull；该实例已自动清理，失败证据保留。
- `integration-2g/`：专属维护 Compose 使用 2 GiB tmpfs/3 GiB 内存，全量原 CSV + 八个原物化视图初始化成功。Go race 实跑 Core 3 项、HTTP/配置/目录/图片 5 项、P5 PG 3 项；共 **11 PASS / 1 专用 Swift 服务入口 SKIP**；go vet 通过。独立宿主 curl 的 Pokémon 详情/招式/特性、道具、配置列表均 HTTP 200，响应头/正文/状态及服务/PG 日志已归档，自有实例全部退出回收。
- `worker-process.log`：独立 native worker 向量与拒绝/取消验证、真实 SIGKILL 进程隔离 **2 PASS**，race 与 go vet 通过。
- 复现：`bash tools/migration/validate-go-server.sh`。脚本只使用 manager + 已声明 maintenance run --rm、自有 tmpfs PG、不发布 DB 端口；唯一 Web 测试实例发布随机回环端口，退出仅清理本脚本精确 ID。真实知识初始化暂借既有 Python bootstrap 作为离线测试夹具，不是 Go 服务依赖。

## 剩余范围

1. 原任务 API、PG coordinator 与 case lease/heartbeat/恢复/持久化幂等结果、进度与分页；现有六张表只是 schema 基础，不能代表完整生命周期已通过。
2. 原 damage/calculator damage/configuration solve/search、fixed-one-on-one/step/graph、graph 导航/重算、candidate pool/move combinations/winning paths 等计算服务。依赖 P1 尚未迁完的正式回合、动态效果、图扩展/SCC 与配置求解合同。Go 仅负责知识/请求组装，不复制战斗规则。
3. Go 原生 CSV/物化视图管理命令、生产 Go Docker 构建与独立 Worker 编排、Vue 接入、旧新全 API 差分、重启恢复和部署回滚演练。
4. 当前同步 Core-only HTTP 计算入口仍直接 CGO，复杂推演必须接独立 Worker；子进程工具通过不等于 PG 任务系统完成。

本检查点不合并、不切生产，不将 16/41 误写为 P3 完成。
