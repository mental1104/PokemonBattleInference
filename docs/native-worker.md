# Go 持久化 Worker

`server/cmd/pbi-worker` 从 PostgreSQL 的冻结 Go 任务定义领取工作，通过独立 `pbi-core-worker` 进程计算，再将结果和计数原子提交到原运行表。它不调用 Python、不在 Go 重写概率或战斗规则，也不会领取没有 Go 冻结定义的旧 Python 任务。

## 2026-11-25 摘要与业务归因接线

新建configuration/fixed任务通过同一模板显式冻结`graph_mode=configuration_summary`及`include_root_action_explanation=true`。旧持久模板继续按原字节执行；Full浏览图及按需重算入口不使用Summary。成功结果的`explanation_json`保存同次Core返回的完整`battle-inference.explanation.v1`对象，缺失/null保持nil。引擎、规则及最终请求SHA继续使用独立`go_case_result_metadata`，不再放入业务归因字段。

`serial-resume-20261125/worker-abi11/`记录正式.11真实PG/child/daemon **11/11 race通过（4.181秒）**及vet。固定战斗以另一次真实child结果核对完整保存说明；显式graph不生成说明，实际来源仍可独立读取。

`PBI_VALIDATION_CORE_DIRECTORY=/build/root-summary-abi11 bash tools/migration/accept-go-job-submission.sh`的最终证据在`serial-resume-20261125/job-results-final2/`：独占空PG、全量CSV、真实Go API/daemon和原Python独立协调器 **20/20 PASS，零SKIP（39.79秒）**。成功配置完整结果（含完整根行动归因）及节点/边/回合三类预算逐字段一致，44,100配置真实创建/运行取消和共享定义保留。归一仅独立任务ID与时刻，配置身份、概率、计数、诊断和解释均未省略。

`job-results-first/`及`job-results-final/`保留两次17通过/3失败。差异仅截断诊断：旧Go通用文本和纯Core通用solver说明均不是原持久任务DTO文本。适配层依据实际truncations按原顺序格式化原因/solver说明，保持节点→边→回合失败码优先级；没有更改Core数学、构图、共享向量、预算或断言。最终完整公开对照证明修复。

随后`PBI_VALIDATION_CORE_DIRECTORY=/build/root-summary-abi11 bash tools/migration/validate-go-server.sh`在主工作树组合上完整执行，`serial-resume-20261125/go-all-abi11/`记录 **66 PASS / 1专用Swift serve夹具SKIP**及额外恢复 **10/10 PASS**，race/vet及六条独立HTTP读取通过。该全量测试包含最新nativeworker全部11项；唯一SKIP不当作Swift实际验收。新增Python结果测试ruff/strict mypy通过，原生archive仍为同一冻结.11。

当前可执行单个正式 `graph` 或 `fixed_battle` 批次；后者从完整初始状态及冻结知识实际构图、SCC 分解并精确求解，保存真实资源统计与覆盖说明。配置候选到任务的完整 HTTP 创建链仍在迁移，不能将本切片当作 P3/P6 已完成。

任务首次领取与过期恢复都匹配明确的 calculation revision；运行时按冻结规格的 process_count 并行，最多八个原生子进程。只有有效 owner 才能续租和写结果，失去租约立即回收自己的子进程。队列、用例与稳定结果都在 PostgreSQL 中，daemon 重启不会丢弃已提交用例或重复增加完成计数。

用户取消会停止后续领取并回收活跃子进程，保存 cancelled 终态；daemon 自身停机则保留未确认租约供下一 owner 过期恢复。执行使用有界 NDJSON 进度/最终结果协议，取消时杀死并等待确切原生子进程。回调每用例只更新一个不可变最新进度，PG 主循环保存实际节点、边、已展开节点及 frontier，避免慢数据库阻塞原生回调。所有错误分类保留原结果合同，截断或未解决图不产生默认胜率。CGO fatal 可能以 exit=2 退出，因此仅退出码与完整 ABI 错误 JSON 同时匹配才认定业务拒绝，其他信号/损坏输出属于 worker_crash。

结果保存原生引擎/规则版本、精确分数与视角，完整输入保留在冻结定义。分页摘要不会复制全部 SCC；未来完整战斗图仍须通过对应 API 按需重算，不能声称已经交付该接口。

## 运行条件

先由独立初始化步骤建立原运行表与 Go 冻结定义表。daemon 必须收到 `PBI_POSTGRES_DSN`、`-revision` 和绝对 `-native-executable`，不会自行导入知识或破坏已有数据库。默认 lease 为 120 秒、heartbeat 为 20 秒、取消/队列轮询为 250 毫秒；构造时拒绝不安全的相对路径和租约时序。数据库错误不输出连接字符串，交给外层监督者重启。

`pbi-healthcheck` 是无 shell/curl 运行镜像中的 HTTP 探针；从 `PBI_LISTEN` 推导本机地址，成功时退出 0，不输出响应或凭据。

## 实际验证

2026-11-24：`tools/migration/validate-native-worker.sh` 使用已声明的 maintenance、只读源码、独立 tmpfs PG 与真实原生可执行文件验证。输入为已构建 Core archive，使用 `PBI_NATIVE_CORE_BUILD_DIR` 指定容器内路径；报告根可按已有 `POKEOP_REPORT_ROOT` 配置。

最终 **五项真实 PostgreSQL/独立原生进程测试 PASS**（3.616 秒），`go test -a -race` 与 `go vet` 通过：

1. 真正 `pbi-worker` daemon 进程消费持久化任务，空闲后 SIGTERM 正常退出。
2. 并行原生子进程得到精确 `1/3`、`2/3`、期望一回合；攻守视角转换不改变原概率，重启不重复处理终态。
3. daemon 停机保留已确认工作和未确认租约，新 owner 过期后恢复全部用例。
4. 用户取消停止队列/活跃子进程，最终所有进度桶守恒。
5. 原生拒绝、不完整图和引擎版本不一致保存明确非成功结果，不伪造成平局或零胜率。

证据在 `/volume1/homes/mental1104/Backup/PokemonBattleInference/nativeworker-20261124/final/`，含 archive 摘要、构建/race/vet 与精确 PG 实例日志。第一次四项业务测试通过后 `go vet` 捕获外包结构体未命名字段，修正为命名字段后最终五项重跑通过；首次证据保留在相邻 `acceptance/`。自有实例退出后已自动移除，不涉及生产切换。

正式 Core **0.6.0** 接入后的 `progress6/` 独立重跑 **7/7 PASS**（3.943 秒），包含上述五项及两个新增场景，`go test -a -race` 和 `go vet` 均通过：完整真实固定战斗从初始状态得到两节点一边、攻击方胜率一及期望一回合；攻守两个视角还原到同一旧结果合同，最终进度实际保存 `graph_built/2/1/1/0` 和版本。另一场景用一节点预算真实触发 `graph_node_limit`，保存资源统计及 NULL 概率，绝不编造平局。报告同时保存本轮两个静态 archive 摘要和自有 PG 日志。

配置任务查询回归发现真实停机竞态：父 context 取消与 SQL Commit 同时发生，驱动可能返回 `sql.ErrTxDone`。`RunOnce` 现在仅在已有错误且父 context 确实撤销时统一返回 `ctx.Err()`；父 context 活跃时保留真实数据库、租约与内部超时错误。`configuration-jobs-final2/` 保存首次失败；修复后的 `configuration-jobs-go-all7/` 使用正式 **0.7** 库，全部 Go 包 **46 PASS / 1 专用 Swift 服务 fixture SKIP**、race/vet 通过，另对停机/租约恢复场景实际重复 **10/10 PASS**（24.198 秒），未跳过或降低原恢复断言。

## 共享冻结输入

原10+10池共有44,100个具体case。实际完整PG属性表为14,504字节，固定战斗请求约18,025字节；若逐case重复，原始请求就达794,902,500字节，尚未计入解码和序列化副本。`Definition` 因此新增可选共享 `CoreTemplate` 与冻结 `Admission`：知识/完整状态只保存一次，case继续保存原canonical身份和技能ID。旧完整请求模式保留，模板模式禁止混用每case完整请求，未使用新字段时omitempty保持原序列化形状。

Worker只索引轻量case，领取后按冻结ID选择原始MoveSpec和PP槽，覆盖`spec.moves/move_slots`，其余原始状态/规则/属性表逐字段保留。真实`slot_id`可能为9001等值，不按位置或move_id重编号。每个原生进程只拥有当前请求，结束后释放；不预先物化全部44,100个请求、不重查知识、不执行Go战斗公式。

`nativeworker-template-20261124/`：真实PG/child/daemon **8/8 race PASS**（3.897秒）及vet，包括同一模板两个不同技能配置，经PG重载后实际构图/精确结果并保持轻量case；独立完整fixture投影/原slot身份/未知选择拒绝/缓冲区所有权测试 **PASS**（1.046秒），使用JSON Number精确比较。完整44,100用例的实际HTTP提交体积和任务闭环由服务端后续验收，不以此两个用例代替。
