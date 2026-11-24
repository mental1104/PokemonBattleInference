# P3 Go 服务迁移

2026-11-24 当前检查点：已迁移原 41 项 API 中的 **38 项**，包括配置/知识/图片、任务、候选池、模板/属性求解、两种伤害、固定摘要/任务/组合预览、图创建/四导航及胜利路径查询，并接入 P5 同步处理器。以上均有真实 PG/Core/独立客户端验收；其余stateless step、dragonite-vs-weavile及configuration casegraph三项仍须接齐。现代静态特性兼容和旧damage原NameError的独立修复证据保留。原 Python 生产服务、生产库及部署均未改动。

| 范围 | 实现与真实验证 |
| --- | --- |
| 配置 7 项 | GET 列表、GET 性格、POST 创建、PUT 更新、DELETE 软删除、POST hidden/order；使用原两张运行表、可信租户 header、七项内置定义、25 性格、EV/IV 约束及 UTF-8 不可变快照。真实 PG 验证跨租户禁止更新/删除、隐藏、排序失败整体回滚、重复迁移和 handler 重建后持久化、软删除后快照仍可解释。 |
| 知识 6 项 | Pokémon 搜索/详情/特性/招式分页、道具、模板。使用原 poke_champion 物化视图及历史特性 SQL；全量固定 submodule CSV 实际初始化后验证快龙 91/134 种族值、dragon/flying、中文搜索、历史特性/道具、去重总数/稳定分页/完整 18 属性筛选。 |
| 图片 3 项 | Pokémon/type/item BYTEA 读取、原选择视图与固定路径、强/弱 ETag 及 304；实际 PNG 字节逐字节比较，验证不存在时 404。没有引入文件系统任意下载或在线图片 fallback。 |
| PostgreSQL | pgx/v5/stdlib + database/sql。显式 DSN、连接池；原六张运行表采用 additive 初始化，一笔事务/advisory lock、不 DROP、不重建已有数据；二次运行保持记录。独立 pbi-db-init 已纯 Go 导入全量固定 CSV 并创建八个原物化视图，具体事务/版本边界见下文。 |
| P5 接线 | NewServer(db) 挂 GET/POST /v1/sync；主进程显式迁移时调用 syncstore.Migrate；本轮真实 PG 重跑 P5 三项事务/并发/HTTP 测试通过。Swift 测试专用服务入口缺少 PBI_SYNC_TEST_SERVE_ADDR 时有一个预期 SKIP，不能记成跨语言 PASS；P5 另有独立跨语言验收。 |
| 子进程边界 | pbi-core-worker 从 stdin 接收单批 JSON，stdout 输出完整 Core ABI 响应。所有 Core HTTP 请求统一使用绝对路径子进程，缺失时 503，绝不回退进程内 CGO；原生进度和实际 PG daemon 另见 [native-worker.md](native-worker.md)。 |
| 静态计算器 1 项 | POST /v1/calculator/damage 从单个 repeatable-read 快照读取原规则集、双方种族值/合法历史特性、version-aware 招式及完整属性表；Core 子进程执行 hp/stat、stage、damage 三个依赖批次。旧单轴 plus 模板不降低其他轴；快照完整 paired nature/EV/IV 保留。合法未实现特性沿旧入口返回原中文 warning。显式reference_static保留InnerFocus/Multiscale身份及原静态无实时HP/畏缩钩子的语义，默认strict与真实回合不变；14项原完整JSON差分通过。 |
| 旧伤害 1 项 | POST /v1/damage保留defenser拼写、原七字段、EV/4/Quiet/忽略individual_values等历史独立语义，从原全图鉴raw表读取事实；Core legacy_damage执行原责任链和随机数学，Go仅注入单位随机事实。原路由当前NameError500明确记为独立缺陷修复，不冒称修复前可用。 |
| 任务查询 3 项与仓库 | GET jobs 列表/详情、POST 幂等取消；读取原任务表与冻结执行规格。新 jobs.Store 已实测事务创建、完整 Core 输入冻结、同 ID 不同定义拒绝、revision 过滤、SKIP LOCKED 领取、有效 owner 心跳、过期恢复不重复记账、精确任意精度结果与旧 Python 同算法指纹、晚到/重复结果、真实进度、取消宽限、终态收口及分页。真实 graph/fixed-battle coordinator/daemon 和 NDJSON 进度见 [native-worker.md](native-worker.md)。 |
| 配置任务查询 4 项 | GET configuration-jobs 状态/results/issues、POST cancel，保持原独立 DTO、粗粒度状态、精确概率/期望回合、微秒时间、错误码过滤及 sequence 分页。结果和总数同一 repeatable-read 快照，无 N+1 查询；旧 Python 数据没有 Go definition 也可查询，结果分页不依赖 execution spec。原任意非空 explanation 读兼容保留，HTTP 非对象/损坏 JSON 仍为 null；新结果写入继续严格验证 JSON。 |
| 原任务创建 1 项 | POST configuration-jobs 保留原 one-on-one-move-pool.v1 DTO 与 202、原内容寻址 Idempotency-Key；同一 PG repeatable-read 快照交 Core strict/factory reconciliation，收齐全部失败后才分页取得原具体 canonical case。全部能力计算、严格准入、组合、SHA/权重均由 Core 完成；单个共享 template/admission 与轻量 case 原子冻结，daemon 领取后只投影招式与槽。没有任意 Core JSON 入队入口，也不删除不支持项缩小候选池。 |
| 候选池 1 项 | GET inference/candidate-pools/{pokemon_id} 从同RR快照向独立Core提交所有合法招式事实，不隐藏不支持项；完整status/selectable/reason/missing与原factory reconciliation一致。七种Pokemon及原业务错误/重复query最后值真实同库13/13逐字段差分通过。 |
| 配置求解 2 项 | POST configuration_solver/solve与search-spreads保留原WithSpeed合同；单RR冻结所有主体/目标/合法性与属性表，Core准备actual stats/target Speed后调用正式.8模板或EV/IV搜索。完整候选/首失败/严格速度/性格选项/独立区间及中文说明均保留；Go不枚举投入、不求伤害/阈值或比较速度。 |

| 固定推演摘要 1 项 | POST inference/fixed-one-on-one 保留原strict准入、Core规范招式顺序/初始状态/正式求解及完整工厂能力集合；真实Go→独立child与原Python同PG19/19全字段差分通过。预算截断、原不支持招式/特性和资料缺失保持明确错误，不伪造成功概率。 |
| 固定任务与组合预览 2 项 | POST fixed-one-on-one-jobs复用原strict/单case持久化/独立daemon；header key原SHA、当前状态重放与冲突、旧Python任务无Go definition时只读幂等保留。POST move-set-combinations只调用Core严格准入/组合与完整pair计数，Go不枚举或求乘积；两侧最多210完整技能组，与原列表顺序/名称/错误优先级相同。 |
| 图创建/导航 5 项 | POST fixed-one-on-one/graph与explore/groups outcomes/advance/backtrack，冻结完整事实、实际Core版本和图计数；每个查询由Core重建typed图再投影，Go不搜索、归并或算概率。正式final2实际同PG24项（含原19摘要与5图场景）完整差分通过，真实841节点/16095边及全部root outcomes未裁事件。 |
| 胜利路径 1 项 | POST winning_paths/graphs/{graph_id}复用唯一图缓存，Core负责重建、原100000 walk预算、精确胜率/覆盖、行动归并、前缀、分页和不透明cursor；Go只做原HTTP与任意精度整数转写。真实大图双方winner、uniform分页及错误共10组完整查询对照相同，不能以缓存存在冒称搜索成功。 |

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

1. 剩余原HTTP三项为stateless fixed-one-on-one/step、dragonite-vs-weavile及configuration casegraph。新创建持久任务拒绝原strict声明为partial的机制；参考同步推演允许partial并返回coverage的入口不能误套相同策略。
2. 完整旧explanation与独立实际版本/输入溯源的存储/消费者接线另行收口，不能将提交时Admission版本当实际结果版本。configuration-jobs的旧Python任务与仅Core元数据变化的同ID重放已保留，key+command+预算的原SHA不变，新预算仍新ID202，不套用fixed仅key身份。
3. 生产发布编排、知识版本升级/历史库接管、Vue 全 API 兼容验收、旧新全 API 差分与真实业务升级回滚。纯 Go 数据镜像与五个真实二进制的 scratch 镜像、原生 daemon 的恢复/停机，以及独立 P6 预览/健康/镜像回退证据，不等于已完成生产迁移。
4. 所有Core HTTP已统一独立child，图创建与五种查询已真实接通；不将38项或子进程基础验收写成41项整体完成。纯Go BYTEA导入已由独立切片实现并以真实样本验收，完整来源图库与生产发布仍未在上述证据中证明。

本检查点不合并、不切生产，不将 38/41 误写为 P3 完成。

## 候选池与完整配置求解

`candidates-final/` 从空PG纯Go导入固定全量知识，原候选池HTTP与Go/独立Core **13/13 PASS、零SKIP（1.94秒）**。验证七种Pokemon全部合法move的本地化类型/威力null、strict状态与缺口、全部reason/disabled_reason、原404/规则轴错误以及重复query最后值；没有只统计支持数量或删掉合法未支持项。`candidate-124`首次两端都404，原测试误期望200的失败保留，最终作为原404用例核对。

`solver-final/` 从空PG纯Go导入后，真实旧两HTTP→独立Core **0.8**→旧DTO，与原FastAPI同库 **40/40 PASS、零SKIP（2.47秒）**；32项完整JSON相同，8项显式null的框架校验只比较422分类。覆盖攻/防/混合、纯速度/伤害加速度、paired snapshot与重复显式模板顺序、pressure降级warning、100级InnerFocus/Multiscale原静态语义、全部候选或完整首失败、25性格选项、EV/IV六字段独立范围、原400错误及省略默认/忽略extra。不是把一次damage结果改名为反推，也不以metadata-only响应冒充求解。

初轮模板8项失败源于.8模板IV/EV应为六顺序数组而误传了.7统计操作使用的对象；原日志保留，纯DTO映射修复后完整30项再通过，随后上述空库40项最终通过。两项针对真实25-op HTTP/独立Core与完整知识读取的Go race、vet通过；没有重跑仍在并行开发的其他代理未冻结用例。两个专属验收脚本 `accept-go-candidate-pools.sh`、`accept-go-configuration-solver.sh` 均exit0并精确回收自有API/PG。

## 纯 Go sprites BYTEA 初始化（2026-11-24）

固定推演摘要证据 `fixed-http-20261124/http-second/`：**19/19 PASS、零SKIP（73.82秒）**，完整JSON含机制集合、两个观察方、实际多招式及uniform选择、100级与原预算/拒绝边界。薄模板投影器实际Core结果一致及非法选择的race测试通过。首轮15PASS/3FAIL完整保留，三项双方实际均422（原strict拒绝BulletPunch、显式边预算下原100级图截断）；修正正向样本并保留拒绝场景后得到最终19项，未放宽strict或删除错误断言。Core+ABI使用同一新完整capability布局fresh构建，不能混旧Core archive。

`pbi-db-init --sprites-root`补齐独立图片导入，沿用原两张表、完整路径/变体元数据、原排序NUL分隔manifest和完成批次幂等。同摘要不重写BYTEA；变更保留asset_id与first_seen，源删除仅在整次事务成功后失效；导入完成刷新原两个图片MV。显式来源只读，未指定则不碰图库。完整来源和API/前端镜像分离，可叠加 `compose.go-stack-sprites.yaml` 挂给db-init。

`sprites-go-20261124/knowledge-fixed/`的真实PG/race测试通过，包括两连接同时重跑、变更/删除、以及真实PG trigger在第二个文件拒绝写入后的整批回滚。原177 CSV的1,051,800记录类型/摘要及原资料查询回归也通过，vet通过。初轮发现精简镜像没有系统mime.types导致txt变为octet-stream，补齐原Python内置常用MIME后通过；失败日志保留。

`actual-source/`从空PG纯Go导入CSV及PokeAPI/sprites固定c0542f7c51215d9672439012838c99f520596cbd的五张真实PNG（149/212/242、life-orb、fire），首次/复用回执与原Python importer全部业务列/原字节严格相同；五条公开图片HTTP逐字节相同、Content-Type与ETag/304通过，**6/6 pytest PASS、零SKIP（0.41秒）**。每个下载均与GitHub原blob SHA一致，原版权/CC0文本与source.json保存在Download的专项输入旁。该五图是自有空库验收样本，**不是全量sprites导入证明**；尚未重跑带图片的整套Docker/Vue浏览器。

Python专项ruff与strict mypy通过，bash syntax/diff检查通过。没有连接生产数据库、将样本导入历史图库或将全量资源放进源码/运行镜像。

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

## 两种伤害HTTP最终验收

`legacy-http-final/`从独立空PG纯Go导入完整固定CSV，真实API与独立Core0.9子进程 **33/33 PASS、零SKIP（4.62秒）**。现代calculator14项均完整JSON相同，InnerFocus/Multiscale通过明确reference_static上下文恢复原静态语义；历史`calculator-final/`的原200/新422证据保留，但不再代表当前状态。默认Core strict与真实回合不受此上下文影响。

旧`/v1/damage`19项保留公开defenser/默认/null/原全图鉴10021等事实；先实证原NameError500，再只恢复历史PokemonDirector构造配方，以原真实AbilityFactory及责任链作为oracle。五个确定字段逐值比较，两个随机字段检查属于原uniform/round产生的支持集，未把独立随机抽样说成逐值一致。原UNKNOWN/Stellar/空白Type失败与六类null schema也保留明确分类；全部324属性关系与原矩阵逐格核对。原Type枚举无UNKNOWN，固定全量Pokemon type无0/新类型/缺slot1；没有在Go删除或归一化未知类型。

新增全图鉴资料实际PG测试及11个现代schema子场景race通过，vet通过。`legacy-domain/release-o3-bitset.log`另有最终Release -O3/Werror的2原生+369原责任链差分通过；早期Boost左移编译告警保留，修复没有关闭告警。复现`PBI_VALIDATION_CORE_DIRECTORY=/build/root-event-abi9 bash tools/migration/accept-go-legacy-damage.sh`，脚本exit0并回收全部自有实例。该批未连接生产，旧随机接口故障修复不冒充原生产迁移已完成。

## 固定任务与组合预览

`fixed-workflow-final2/`从空PG纯Go导入完整CSV，真实Go→独立Core0.9与原FastAPI同库 **24/24、零SKIP**；其中23项完整对照3.63秒，独立daemon真正完成后终态重提1项1.60秒。覆盖原固定任务202/同key/同key不同预算409、none/null、两招规范顺序、HTML key、uniform、未知profile异步202，以及原Python先创建且没有Go definition的任务只读重放。旧任务没有被偷偷补写执行模板，随后通过公开取消避免未迁移执行规格被认领。

组合预览完整比较两侧原名称/ID/自然顺序与move-set ID，实际5招侧5组及10×10侧各210组、全局44,100 count。Core configuration_coverage裁strict、configuration_moves枚举、job_move_pool空页重复关联准入并返回完整pair数；Go没有重新生成组合、相乘或缩小候选池。非法特性/道具/招式/候选缺失/错revision/重复ID，以及特性错误优先于重复候选的原顺序均逐字段相同。

实际原固定输入212/149同50级经过独立PG daemon，结果 **841节点/16095边**，精确攻胜0/1、防胜1/1、平0/1、期望5/1；只是该输入的真实结果，不写死到服务。完成后同key202返回当前succeeded，原phase字段仍queued，原完整响应一致。Go vet通过，bash syntax/diff检查通过，专属API/PG/daemon均已清理。复现`PBI_VALIDATION_CORE_DIRECTORY=/build/root-event-abi9 bash tools/migration/accept-go-fixed-workflow.sh`；该批不改生产或增加Core数学规则。

`fixed-workflow-quotes/`追加原字符串repr兼容：特性/道具ID分别含单引号、双引号、反斜杠的六项真实HTTP拒绝逐字段一致，复用原pythonRepr而不手拼引号。完整空库重跑 **30/30零SKIP**（29项3.68秒及daemon完成后重提1项），保留前24项和真实单case执行回归；专属实例均已清理。该小修只修错误DTO转义，不改变准入或数学规则。

## 胜利路径与完整图传输边界

原合法841节点/16095边图的完整JSON实测 **565,290,981 bytes**，含102,688条事件路径与1,915,328个事件，直接经过32MiB通道真实413；没有将图裁小或改成成功概率。最终共享缓存只保存首次完整冻结fixed请求、实际engine/rules和节点/边计数。每次导航/winning由独立Core按同一事实重建typed图、校验版本/计数后直接调用唯一纯域算法，返回所需小DTO，所有事件仍参与原算法。此方案以构图CPU换取传输/解析与API缓存内存；不是保存565MiB后静默过滤。

`winning-first/`使用正式`/build/root-graph-abi10-final2`，空PG完整CSV、真实Go HTTP/独立child、原Python同库，**3/3零SKIP（61.29秒）**。实际10组查询完整JSON相同，包括大图双方winner、uniform两页及原样cursor、跨winner游标、损坏cursor、不存在图及sort/版本错误顺序。只固定原测试store的随机句柄为Go生成ID，计算/图/搜索未替换。

真实baseline查询：攻击方原0.479秒、Go重建查询2.818秒/1016B；防守方原15.045秒、Go重建搜索5.385秒/6525B。原100000有限walk预算与traversal_truncated/query_complete均保留，不把不完整覆盖说成数学平局。Go前置lookup/TTL与超过int64/2**53整数转写两测试race/vet通过；Pythonruff/strictmypy、bash syntax、diff检查通过，所有自有PG/API精确清理。复现`PBI_VALIDATION_CORE_DIRECTORY=/build/root-graph-abi10-final2 bash tools/migration/accept-go-winning-paths.sh`。

## 独立实际执行溯源存储

新增私有`go_case_result_metadata`，以原job/case唯一键关联；只在显式Migrate时创建，不改原六表/explanation/结果指纹，不回填旧行。`ExecutionMetadata`接收调用方实际child版本和最终发送请求SHA，缺真实响应的版本可为null。首次有效lease的终态及aux记录同事务，重复终态不覆盖旧来源；旧Python无记录返回nil。该存储层不自行请求Core，也不拿Definition.Admission版本冒充实际执行版本。

`p3-result-metadata-20261124/`真实独占PG的全部jobs **8/8 race/vet通过（1.529秒）**，含aux trigger拒写后case/lease/计数整体回滚、旧owner拒绝、来源字段往返、终态不覆盖、原无metadata结果与重复Migrate。Root随后在`native-execution-metadata-20261124/`完成实际child来源注入，正式final2 archive/独立daemon与PG **11/11 race及vet通过（4.716秒）**：保存最终传输请求SHA，刻意错误的协调器版本不会替代真实child版本，执行前拒绝不造记录；取消、停机恢复及精确结果保留。首次新断言误用不含CoreRequest的公开case列表，原失败日志保留；改从持久化冻结Definition核对实际字节后全部通过，未改producer来迎合断言。独立HTTP/Swift读取仍在接线，旧explanation的业务归因等待下一Core批。BattleSide未导入缺陷按BASE-EXPLANATION-001单独记录修复，未修原基线并非普遍可生成完整说明。

## 配置任务跨实现幂等

`idempotency-first/`用正式final2、独占空PG/完整CSV和原Python同库HTTP，**4/4零SKIP（1.75秒）**：原Python已创建而没有Go definition的任务可原样202重放；只改变已存Admission中的Core版本时仍202且保留旧JSON/hash；同key修改预算按原SHA产生新ID202；同ID异规格仍返回原409及精确错误文案。匹配仅检查原规则轴、完整spec和全局case数，不要求Go私有执行格式相同，不重置结果、队列或来源。该入口的身份规则与fixed任务仅key身份分别保留。

Go服务及真实child重新构建、go vet、Pythonruff/strictmypy、bash syntax和diff检查通过；专属PG/API均已清理。复现`PBI_VALIDATION_CORE_DIRECTORY=/build/root-graph-abi10-final2 bash tools/migration/accept-go-job-idempotency.sh`。
