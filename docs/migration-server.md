# P3 Go 服务迁移

2026-11-24 当前检查点：已迁移原 41 项 API 中的 **19 项配置/知识/图片及任务查询取消 API**，并接入 P5 同步处理器；正式推演创建及计算 API 尚未替换。原 Python 生产服务、生产库及部署均未改动。

| 范围 | 实现与真实验证 |
| --- | --- |
| 配置 7 项 | GET 列表、GET 性格、POST 创建、PUT 更新、DELETE 软删除、POST hidden/order；使用原两张运行表、可信租户 header、七项内置定义、25 性格、EV/IV 约束及 UTF-8 不可变快照。真实 PG 验证跨租户禁止更新/删除、隐藏、排序失败整体回滚、重复迁移和 handler 重建后持久化、软删除后快照仍可解释。 |
| 知识 6 项 | Pokémon 搜索/详情/特性/招式分页、道具、模板。使用原 poke_champion 物化视图及历史特性 SQL；全量固定 submodule CSV 实际初始化后验证快龙 91/134 种族值、dragon/flying、中文搜索、历史特性/道具、去重总数/稳定分页/完整 18 属性筛选。 |
| 图片 3 项 | Pokémon/type/item BYTEA 读取、原选择视图与固定路径、强/弱 ETag 及 304；实际 PNG 字节逐字节比较，验证不存在时 404。没有引入文件系统任意下载或在线图片 fallback。 |
| PostgreSQL | pgx/v5/stdlib + database/sql。显式 DSN、连接池；原六张运行表采用 additive 初始化，一笔事务/advisory lock、不 DROP、不重建已有数据；二次运行保持记录。独立 pbi-db-init 已纯 Go 导入全量固定 CSV 并创建八个原物化视图，具体事务/版本边界见下文。 |
| P5 接线 | NewServer(db) 挂 GET/POST /v1/sync；主进程显式迁移时调用 syncstore.Migrate；本轮真实 PG 重跑 P5 三项事务/并发/HTTP 测试通过。Swift 测试专用服务入口缺少 PBI_SYNC_TEST_SERVE_ADDR 时有一个预期 SKIP，不能记成跨语言 PASS；P5 另有独立跨语言验收。 |
| 子进程边界 | pbi-core-worker 从 stdin 接收单批 JSON，stdout 输出完整 Core ABI 响应。所有 Core HTTP 请求统一使用绝对路径子进程，缺失时 503，绝不回退进程内 CGO；原生进度和实际 PG daemon 另见 [native-worker.md](native-worker.md)。 |
| 任务查询 3 项与仓库 | GET jobs 列表/详情、POST 幂等取消；读取原任务表与冻结执行规格。新 jobs.Store 已实测事务创建、完整 Core 输入冻结、同 ID 不同定义拒绝、revision 过滤、SKIP LOCKED 领取、有效 owner 心跳、过期恢复不重复记账、精确任意精度结果与旧 Python 同算法指纹、晚到/重复结果、真实进度、取消宽限、终态收口及分页。创建 HTTP/实际 coordinator 尚未接入，不能把仓库测试当成完整推演闭环。 |

## 运行边界

- 无 PBI_POSTGRES_DSN：继续提供 Core-only `/healthz`、`/v1/core/calculate`，不创建假仓库。
- 显式 PBI_POSTGRES_DSN：启用以上数据库路由；仅 PBI_MIGRATE=1 时执行增量运行表与 P5 表初始化。默认不迁移、不导入、不刷新。
- Core 子进程优先使用绝对 `PBI_CORE_WORKER_PATH`，否则只查 server 实际可执行文件同目录的 `pbi-core-worker`；不搜索 PATH。所有计算默认派生 30 秒 context，35 秒 HTTP WriteTimeout 留出完整 504 写出时间。SIGTERM 根 context 传播到请求和 child，main 等待实际 Shutdown 完成；healthz 仍是进程存活语义。
- `X-Pokeop-Tenant` 沿用旧可信网关注入约定，开发默认 default-tenant；它不是认证。P5 的 `X-Pokeop-User` 必填，用户不能在正文或 query 指定身份。生产开放前仍需在真正认证网关建立可信边界。
- 所有数据库异常对外返回稳定 503，不输出连接字符串或 SQL。未迁计算端点没有返回演示结果，也没有调用 Python 在线运行时。

## 验证证据

路径：`/volume1/homes/mental1104/Backup/PokemonBattleInference/p3-server-20261124/`。

- `integration/catalog-initialization.log`：通用测试 PG 的 512 MiB tmpfs 在刷新原 pokemon_catalog_zh_mv 时真实 DiskFull；该实例已自动清理，失败证据保留。
- `integration-2g/`：专属维护 Compose 使用 2 GiB tmpfs/3 GiB 内存，全量原 CSV + 八个原物化视图初始化成功。Go race 实跑 Core 3 项、HTTP/配置/目录/图片 5 项、P5 PG 3 项；共 **11 PASS / 1 专用 Swift 服务入口 SKIP**；go vet 通过。独立宿主 curl 的 Pokémon 详情/招式/特性、道具、配置列表均 HTTP 200，响应头/正文/状态及服务/PG 日志已归档，自有实例全部退出回收。
- `worker-process.log`：独立 native worker 向量与拒绝/取消验证、真实 SIGKILL 进程隔离 **2 PASS**，race 与 go vet 通过。
- `worker-cgo-crash.log`：修复“任意 exit=2 都视为 unsupported”的分类缺口。真实 CGO `raise(SIGSEGV)` 被 Go runtime 转为 **exit=2**，父进程现在只有在退出码与完整 ABI error JSON 一致时保留业务错误，否则记 worker_crash；三项真实子进程 race 测试通过，父进程继续可用。测试注入只存在 testdata 独立二进制，不进入产品入口。
- `jobs-final/`：按当前源码独立构建 Core **0.5.0**，CTest **46/46 PASS**；全量 CSV/原 MV、自有 PG 下所有 Go 包 **18 PASS / 1 专用 Swift 服务入口 SKIP**，race/vet 通过，含新的三项任务仓库 PG 测试、一项旧指纹精确约分测试及任务 HTTP 状态/取消实测。宿主独立 curl 六条 API（包含任务列表）全部 200，自有实例已回收。中途扩大回归曾使用旧 `/build/core` 0.4.0 对新 0.5 ABI fixture 返回 unsupported；保存于 `jobs/jobs-postgres.log`，最终改为 `/build/p3/core` 独立重建，没有跳过该 Core HTTP 用例。
- `http-isolation-v6.log`：Core **0.6.0** 新 13-op 共享完整响应，经真实 HTTP→独立 child 全字段相同；原非法 400/unsupported 422、ctx 408、缺 child 503、真实 CGO SIGSEGV 500 后 health 200、运行中 deadline 504 后 PID 确实消失，**4/4 race 测试、零 SKIP** 与 vet 通过。未提供测试 child 路径时自动真实 `go build -a`，没有跳过原 Mac/Linux HTTP 断言。
- `http-lifecycle-v5-final/`：实际 API 主进程与受控慢 child 的独立宿主 curl 验收，默认截止 **30.024763 秒**返回完整 **504**，之后进程清单无该 child；第二个 child 实际运行时 SIGTERM，客户端得到完整 **408**，API **exit 0**，自有实例清理完成。该场景只验生命周期、不伪造数学计算，真正计算由上项 0.6 完整向量证明。
- `go-images-v6-final/`：实际构建 scratch API/数据镜像，包含 server、单请求 Core child、PG daemon、healthcheck 和纯 Go db-init 五个二进制。运行文件清单证明没有 Python、shell 或编译器；独立空 PG 完整导入当前 `42563467286d` 知识版本，六条目录/配置/任务 HTTP 均 200，Core 0.6 的 13-op 完整响应与共享向量逐字段相同。API 镜像 **46,786,282 bytes**，数据镜像 **82,609,776 bytes**；默认同目录 child 实际可执行，自有实例退出清理。复现入口 `tools/migration/accept-go-images.sh`。
- 复现：`bash tools/migration/validate-go-server.sh`。脚本只使用 manager + 已声明 maintenance run --rm、自有 tmpfs PG、不发布 DB 端口；唯一 Web 测试实例发布随机回环端口，退出仅清理本脚本精确 ID。上述早期检查点当时使用原 Python bootstrap 准备离线夹具；当前脚本已改用下文的真实 Go 初始化命令。

## 纯 Go 知识初始化

`cmd/pbi-db-init` 从显式 `--csv-root` 和 `PBI_POSTGRES_DSN` 初始化空目标，成功打印 JSON 回执。它不依赖 Python/CGO，先校验全部文件 SHA，再在单个 PG 事务/advisory lock 中创建缺失 raw 对象、流式 COPY 临时表、按原主键冲突规则去重、建立八个原 MV、登记版本；失败整体回滚。同版本重跑核对各 CSV 表行数后复用，`--refresh-views` 才显式刷新已有视图。不清空、覆盖或认领未知非空 CSV 目标库；现有生产库接管/升级仍须单独审查。

`server/internal/knowledge/manifest.json` 保存固定 PokeAPI **1567d53073a069b6c96e1c393c5c490f602e3ab5**、179 张 raw 表、177 CSV 的列顺序/Integer/Boolean/Text 类型、原始文件及 Python 语义摘要；完整原许可保存在同包 `LICENSE.pokeapi.txt`。SQL 由 [export-go-knowledge.py](../tools/migration/export-go-knowledge.py) 离线读取拥有者 RawBase metadata、原 view registry/SQL 生成，未把“不可执行”的参考快照当迁移运行。生成器不访问数据库，传入的 source commit 已与实际干净 submodule 核对。

保留旧 DAO 的空整数 **0**、空布尔 **false**、空文本 **空串** 语义。固定 CSV 存在非标准引号：ability_prose 的引号前空格、location_area_prose 的闭引号后直接接未引用文本；Go 标准 Reader 和 LazyQuotes 都曾在实测中暴露差异。私有四状态读取器只服务该导入边界，全部 **177 CSV / 1,051,800 条来源记录的每一个字段值** 必须匹配 Python DictReader+旧类型规则的长度前缀 SHA，不能只凭总行数宣布等价。

数据库导入版本为 **pg-pokeapi-1567d53073a0-42563467286d**；这是完整 PG 来源的 `import_version`，与 iOS 15 CSV SQLite 投影的客户端 `dataVersion` 分开记录，不能互相冒用。`knowledge-normalized-final/` 保存纯 Go 首次命令回执：179 raw / 177 CSV / 8 原 MV、来源 **1,051,800** 行、主键去重后 **1,051,052** 行；第二次命令 `reused=true`。知识包 **6/6 race 测试、零 SKIP** 与 vet 通过，包括并行复用、未知非空目标拒绝且原记录/事务保留、全字段 Python 差分及真实 MV 查询；自有 PG 已清理。

独立复现入口为 `bash tools/migration/validate-go-knowledge.sh`，不依赖 C++ 编译。`validate-go-server.sh` 也已改为调用真实 Go 初始化器，后续全链回归不再使用 Python 初始化夹具。早期解析拒绝、字段语义不一致及原生并行编辑期间的混合构建失败记录均保留在上述证据根，未覆盖为成功日志。

## 剩余范围

1. 原任务创建/配置结果 API、实际 PG coordinator 与子进程调度接线。仓库 lease/heartbeat/恢复/幂等结果/进度/分页已通过独立 PG 测试，完整业务推演仍需正式 Core 回合合同和真实调度。
2. 原 damage/calculator damage/configuration solve/search、fixed-one-on-one/step/graph、graph 导航/重算、candidate pool/move combinations/winning paths 等计算服务。依赖 P1 尚未迁完的正式回合、动态效果、图扩展/SCC 与配置求解合同。Go 仅负责知识/请求组装，不复制战斗规则。
3. 独立 Worker 发布编排、知识版本升级/历史库接管、Vue 接入、旧新全 API 差分、重启恢复和部署回滚演练。纯 Go 数据镜像与五个真实二进制的 scratch 镜像已完成隔离黑盒验证，不等于已完成生产迁移。
4. 所有 Core HTTP 已统一独立 child，正式推演创建/完整配置与图交互 API 仍需接通；子进程工具和 graph/fixed daemon 通过不等于 41 项旧业务整体完成。

本检查点不合并、不切生产，不将 19/41 误写为 P3 完成。
