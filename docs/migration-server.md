# P3 Go 服务迁移

2026-11-24 当前检查点：已迁移原 41 项 API 中的 **24 项配置/知识/图片及任务创建、查询取消 API**，并接入 P5 同步处理器；另有原静态计算器的受限实现，下文明确保留两项特性兼容缺口，不能计为完整迁移。原合同任务创建已经过真实 PG、独立 daemon 和 Swift 客户端验收，其余计算 API 仍须接齐。原 Python 生产服务、生产库及部署均未改动。

| 范围 | 实现与真实验证 |
| --- | --- |
| 配置 7 项 | GET 列表、GET 性格、POST 创建、PUT 更新、DELETE 软删除、POST hidden/order；使用原两张运行表、可信租户 header、七项内置定义、25 性格、EV/IV 约束及 UTF-8 不可变快照。真实 PG 验证跨租户禁止更新/删除、隐藏、排序失败整体回滚、重复迁移和 handler 重建后持久化、软删除后快照仍可解释。 |
| 知识 6 项 | Pokémon 搜索/详情/特性/招式分页、道具、模板。使用原 poke_champion 物化视图及历史特性 SQL；全量固定 submodule CSV 实际初始化后验证快龙 91/134 种族值、dragon/flying、中文搜索、历史特性/道具、去重总数/稳定分页/完整 18 属性筛选。 |
| 图片 3 项 | Pokémon/type/item BYTEA 读取、原选择视图与固定路径、强/弱 ETag 及 304；实际 PNG 字节逐字节比较，验证不存在时 404。没有引入文件系统任意下载或在线图片 fallback。 |
| PostgreSQL | pgx/v5/stdlib + database/sql。显式 DSN、连接池；原六张运行表采用 additive 初始化，一笔事务/advisory lock、不 DROP、不重建已有数据；二次运行保持记录。独立 pbi-db-init 已纯 Go 导入全量固定 CSV 并创建八个原物化视图，具体事务/版本边界见下文。 |
| P5 接线 | NewServer(db) 挂 GET/POST /v1/sync；主进程显式迁移时调用 syncstore.Migrate；本轮真实 PG 重跑 P5 三项事务/并发/HTTP 测试通过。Swift 测试专用服务入口缺少 PBI_SYNC_TEST_SERVE_ADDR 时有一个预期 SKIP，不能记成跨语言 PASS；P5 另有独立跨语言验收。 |
| 子进程边界 | pbi-core-worker 从 stdin 接收单批 JSON，stdout 输出完整 Core ABI 响应。所有 Core HTTP 请求统一使用绝对路径子进程，缺失时 503，绝不回退进程内 CGO；原生进度和实际 PG daemon 另见 [native-worker.md](native-worker.md)。 |
| 受限静态计算器 | POST /v1/calculator/damage 从单个 repeatable-read 快照读取原规则集、双方种族值/合法历史特性、version-aware 招式及完整属性表；Core 子进程执行 hp/stat、stage、damage 三个依赖批次。旧单轴 plus 模板不降低其他轴；快照完整 paired nature/EV/IV 保留。合法未实现特性沿旧入口返回原中文 warning。InnerFocus/Multiscale 当前静态 Core 明确 422，而旧静态入口为 200，仍属兼容缺口，不用 Go 静默抹掉机制或补倍率。 |
| 任务查询 3 项与仓库 | GET jobs 列表/详情、POST 幂等取消；读取原任务表与冻结执行规格。新 jobs.Store 已实测事务创建、完整 Core 输入冻结、同 ID 不同定义拒绝、revision 过滤、SKIP LOCKED 领取、有效 owner 心跳、过期恢复不重复记账、精确任意精度结果与旧 Python 同算法指纹、晚到/重复结果、真实进度、取消宽限、终态收口及分页。真实 graph/fixed-battle coordinator/daemon 和 NDJSON 进度见 [native-worker.md](native-worker.md)。 |
| 配置任务查询 4 项 | GET configuration-jobs 状态/results/issues、POST cancel，保持原独立 DTO、粗粒度状态、精确概率/期望回合、微秒时间、错误码过滤及 sequence 分页。结果和总数同一 repeatable-read 快照，无 N+1 查询；旧 Python 数据没有 Go definition 也可查询，结果分页不依赖 execution spec。原任意非空 explanation 读兼容保留，HTTP 非对象/损坏 JSON 仍为 null；新结果写入继续严格验证 JSON。 |
| 原任务创建 1 项 | POST configuration-jobs 保留原 one-on-one-move-pool.v1 DTO 与 202、原内容寻址 Idempotency-Key；同一 PG repeatable-read 快照交 Core strict/factory reconciliation，收齐全部失败后才分页取得原具体 canonical case。全部能力计算、严格准入、组合、SHA/权重均由 Core 完成；单个共享 template/admission 与轻量 case 原子冻结，daemon 领取后只投影招式与槽。没有任意 Core JSON 入队入口，也不删除不支持项缩小候选池。 |

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
- `calculator-final/`：独立 Core 0.6 重建、空 PG 全量导入、真实 Go HTTP 与原 FastAPI/同 PG 差分 **14/14 PASS、零 SKIP（1.50 秒）**。其中 **12 项完全等价**（八种双方/招式/道具/等级组合、软删除后快照及三种原 detail 拒绝），另两项明确记录原 200/新 422 的动态特性差异，不能称为完整兼容。比较包括原 JSON 全部键/null、六项未分级基础能力、分级后展示攻击/防御、16 档伤害、KO、trace/reason、全部中文 warning；新增 strict/null/range 入口 **11 子场景 race PASS** 与 vet 通过。数据和子进程均真实，不在 Go 复制战斗公式；自有 PG/API 全部清理。复现入口 `tools/migration/accept-go-calculator.sh`。
- `configuration-jobs-final3/`：原 Python store 直接在独占 PG 保存 canonical case/结果/规格，明确没有 Go definition；两端真实 HTTP **36/36 PASS、零 SKIP（3.39 秒）**。其中 30 项完整 JSON 逐字段等价，6 项框架 schema 校验比较 422 状态，未把框架生成的 detail 文案说成逐字兼容。覆盖大于 int64 的精确分母、nullable 字段、全部状态桶、过滤先于分页、重复 query 取最后值、原 404/业务错误、取消重放与终态、历史非 JSON 说明。`http/` 保存原请求与双方原始响应。查询资料夹具不冒称经过战斗执行。
- `configuration-jobs-go-all7/`：显式复用 P2 已验证 Core **0.7** 静态库并重链全部 Go/child/daemon，空 PG 全量 CSV/原 MV 后，所有 Go 包 **46 PASS / 1 专用 Swift test-serve fixture SKIP**，race/vet 通过；额外真实取消/租约恢复场景 **10/10 轮 PASS**。合计日志为 56 PASS/1 SKIP，不把重复轮数当新增能力。`configuration-jobs-final2/` 保留此前发现的停机 ctx 与数据库 Commit 竞态 ErrTxDone 失败；修复位于 daemon 的父 ctx 错误出口，最终全量回归确认，无隐匿失败或修改租约语义。
- 复现：`bash tools/migration/validate-go-server.sh`。脚本只使用 manager + 已声明 maintenance run --rm、自有 tmpfs PG、不发布 DB 端口；唯一 Web 测试实例发布随机回环端口，退出仅清理本脚本精确 ID。上述早期检查点当时使用原 Python bootstrap 准备离线夹具；当前脚本已改用下文的真实 Go 初始化命令。

## 纯 Go 知识初始化

`cmd/pbi-db-init` 从显式 `--csv-root` 和 `PBI_POSTGRES_DSN` 初始化空目标，成功打印 JSON 回执。它不依赖 Python/CGO，先校验全部文件 SHA，再在单个 PG 事务/advisory lock 中创建缺失 raw 对象、流式 COPY 临时表、按原主键冲突规则去重、建立八个原 MV、登记版本；失败整体回滚。同版本重跑核对各 CSV 表行数后复用，`--refresh-views` 才显式刷新已有视图。不清空、覆盖或认领未知非空 CSV 目标库；现有生产库接管/升级仍须单独审查。

`server/internal/knowledge/manifest.json` 保存固定 PokeAPI **1567d53073a069b6c96e1c393c5c490f602e3ab5**、179 张 raw 表、177 CSV 的列顺序/Integer/Boolean/Text 类型、原始文件及 Python 语义摘要；完整原许可保存在同包 `LICENSE.pokeapi.txt`。SQL 由 [export-go-knowledge.py](../tools/migration/export-go-knowledge.py) 离线读取拥有者 RawBase metadata、原 view registry/SQL 生成，未把“不可执行”的参考快照当迁移运行。生成器不访问数据库，传入的 source commit 已与实际干净 submodule 核对。

保留旧 DAO 的空整数 **0**、空布尔 **false**、空文本 **空串** 语义。固定 CSV 存在非标准引号：ability_prose 的引号前空格、location_area_prose 的闭引号后直接接未引用文本；Go 标准 Reader 和 LazyQuotes 都曾在实测中暴露差异。私有四状态读取器只服务该导入边界，全部 **177 CSV / 1,051,800 条来源记录的每一个字段值** 必须匹配 Python DictReader+旧类型规则的长度前缀 SHA，不能只凭总行数宣布等价。

数据库导入版本为 **pg-pokeapi-1567d53073a0-42563467286d**；这是完整 PG 来源的 `import_version`，与 iOS 15 CSV SQLite 投影的客户端 `dataVersion` 分开记录，不能互相冒用。`knowledge-normalized-final/` 保存纯 Go 首次命令回执：179 raw / 177 CSV / 8 原 MV、来源 **1,051,800** 行、主键去重后 **1,051,052** 行；第二次命令 `reused=true`。知识包 **6/6 race 测试、零 SKIP** 与 vet 通过，包括并行复用、未知非空目标拒绝且原记录/事务保留、全字段 Python 差分及真实 MV 查询；自有 PG 已清理。

独立复现入口为 `bash tools/migration/validate-go-knowledge.sh`，不依赖 C++ 编译。`validate-go-server.sh` 也已改为调用真实 Go 初始化器，后续全链回归不再使用 Python 初始化夹具。早期解析拒绝、字段语义不一致及原生并行编辑期间的混合构建失败记录均保留在上述证据根，未覆盖为成功日志。

`catalog.Store.Inference` 已补齐任务创建所需的完整只读资料端口：精确 ruleset/version group、全部合法招式（含变化/变化威力/未支持项）、历史特性去重、受控道具、原形态/进化和属性矩阵，在同一 repeatable-read 事务中冻结。`inference-knowledge-first/` 保存七只 Pokémon 的完整 **416,820 bytes** 产物；与原 Python owning repository 同一独占 PG 的全部字段/原 capability status/reason 严格差分 **1/1 PASS**，Go 知识/读取 **7/7 race PASS、零 SKIP** 与 vet 通过。查询还实测拒绝错误版本轴、缺失对象及 ctx 取消。端口不预先删除 unsupported 合法候选，不做 effect factory 对账、严格准入、组合或权重求解；原任务创建仍须后续正式 Core 合同接入。

## 剩余范围

1. 原候选池与单配置完整图 HTTP API：复用已用于真实任务创建的严格 admission/同快照知识/正式 Core 编排，保持各入口原有边界。持久任务入口已拒绝旧规则声明为 partial 的机制；旧同步推演允许 partial 并返回 coverage 的策略不能混用。44,100 case 已采用共享模板，不重复属性矩阵。
2. 原 damage、configuration solve/search、fixed-one-on-one/step/graph、graph 导航/重算、candidate pool/move combinations/winning paths 等 HTTP 适配；静态 calculator 的两项动态特性差异仍需正式 Core 合同解决。真实固定战斗、图/SCC 和 typed 配置候选能力已有独立 Core 验证，配置公开 ABI 由 P1/P2 接入；Go 仅负责知识/请求组装，不重复枚举、权重或战斗规则。
3. 生产发布编排、知识版本升级/历史库接管、Vue 全 API 兼容验收、旧新全 API 差分与真实业务升级回滚。纯 Go 数据镜像与五个真实二进制的 scratch 镜像、原生 daemon 的恢复/停机，以及独立 P6 预览/健康/镜像回退证据，不等于已完成生产迁移。
4. 所有 Core HTTP 已统一独立 child，原配置任务创建已接通；完整配置与图交互 API 仍需迁移。子进程工具和 graph/fixed daemon 通过不等于 41 项旧业务整体完成；空库完整网页交付还缺旧 BYTEA sprites 导入，目录与计算通过不代表图片数据已交付。

本检查点不合并、不切生产，不将 24/41 误写为 P3 完成。

## 原合同任务创建的真实闭环

`submission-final/` 保存纯 Go 全量 CSV 初始化、原 HTTP 请求、202、进度和真实终态。Scizor212/Dragonite149 同50级、单候选，实际 daemon 完成 **841 nodes / 16,095 edges**，给出精确概率和期望回合；独立 Swift 客户端随后在同一已修 none 边界的服务 **5/5、零 SKIP** 通过创建/幂等重提/完成/results/issues/终态取消，以及先观察 running 再取消。Swift 证据另存 `p4-jobs-p3-none7-20261124/jobs/`。

实际最大双十招池（Azumarill184/Marill183，原 supported_only）创建 **44,100** 对，HTTP **202 / 8.347426 秒**。默认 daemon lease120秒/DB调用10秒；API 和 daemon 均实限 **1 GiB**。运行51对后真实取消并收口为 **51 truncated + 44,049 cancelled = 44,100**，pending/running均0；截断没有填入成功概率或数学平局。原取消 HTTP 200/0.002364秒只表示接受取消，后续终态另行轮询验证。

PG 中实际共享 Definition 为 **25,648,268 bytes**，其中 template **20,416 bytes**、admission **22,794 bytes** 各一份，44,100 case 没有 CoreRequest。此前每 case 复制18,025-byte请求的 **794,902,500 bytes** 是旧方案序列化估算，非实测运行峰值；PG `pg_column_size=3,728,431` 是数据库压缩存储值，也不能当作进程内存峰值。采样RSS/容器统计另存原资源报告。

原 Python 同 PG 差分已验证完整202与同 key 重提、null/明确none、含HTML标点的合法key，以及原 partial/未知选择/跨四招块失败的完整422详情；全部 **44,100** 个实际持久化 case 与原公开 iterator + case_definition 逐字段相同，包含 canonical pair、双方 SHA、具体招式顺序，bulk job ID 也与原应用 SHA 相同。实际 source/ABI 为已验证的 `root-job-none7`；没有编译正在开发的后续 ABI 来混淆证据。最初 daemon 配置不相容导致未消费、测试客户端不接受非ASCII header 的失败均保留原日志，未记成服务通过。

扩大的负向场景保留两项原缺陷修复差异：原缺 Pokémon/错误版本因未捕获 `BattleCandidatePoolNotFound` 返回500，新入口在写入前返回422；测试单独断言并保存两端原始响应，不把差异算成逐字等价。未知 ruleset 已恢复原工厂轴不匹配的完整422文案。早期未知 stat_profile_id 被提前422拒绝的证据仍留存，后续已按下段修复原异步合同。

`PreparationFailure` 与共享 template/逐case完整请求三种模式互斥；该可选字段省略时不改变旧 JSON/哈希。原 inference 只接受七项 PRESETS 加合法 snapshot，静态 calculator 的 `no_investment`/`max_spatk_*` 不能借用到任务准备。未知模板仍通过原严格机制准入并返回202，冻结精确准备失败事实；真实 Worker 领取后逐case写 `failed/invalid_configuration`、零节点/边/预算，概率/期望/说明为空，不构造假能力或启动原生计算。最后任务为 `completed_with_failures`（原公开状态partial），header last_failure 两字段仍null，而不是协调器级failed。

`submission-preparation/` 中真实 Go daemon 与原公开 `RunBattleInferenceWorkerUseCase` + repository-backed preparer 对照 **5/5 PASS、零 SKIP（2.61秒）**：unknown-profile、no_investment、max_spatk_plus、max_spatk_neutral、损坏snapshot，每个五case。两端完整状态除任务ID/时刻外相同，全部结果逐字段相同，包含原 `ConfigurationSpaceError` 精确诊断；参考库克隆同一固定知识，运行时单独隔离，避免两个真实coordinator互相抢任务。模型层另有真实 PG **7/7 jobs race/vet PASS**，验证往返、幂等、改变失败事实冲突与模式混用拒绝。P4改用原七模板后又独立 **25/25、零SKIP** 通过真实计算/同步/任务，证明原样本841节点/16095边/期望5回合，旧 no_investment 新成功日志保留但不计原兼容证据。

最终复现 `preparation-final/` 又从空 PG 完整导入后运行全部链路：有效原模板 `max_atk_neutral` 的实际44,100提交 **202/8.536307秒**，共享定义 **25,824,669 bytes**；新增未知性格snapshot一例，全部原HTTP/原协调器差分 **16/16 PASS、零SKIP（10.30秒）**，其中14项等价验证、2项原资料缺失500→新422的明确缺陷修复对照。`preparation-go-all/` 完整 Go 包实际PG/child/daemon **50 PASS + 1专用Swift服务fixture SKIP**，额外停机恢复 **10/10轮 PASS**，race与vet通过；不把重复10轮当成新增测试能力。两套脚本均exit0并清理自有实例。

复现入口 `tools/migration/accept-go-job-submission.sh` 使用已声明 maintenance、自有空 PG、完整 CSV、原合同202、独立 daemon 成功结果、实际44100创建/运行取消、同库原 Python 差分，退出精确清理。生产服务不受影响。
