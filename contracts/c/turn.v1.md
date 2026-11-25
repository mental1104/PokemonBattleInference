# C ABI v1：正式回合、固定战斗和真实进度

引擎 `0.6.0` / `calculation-rules.v6`，ABI/schema 仍 v1。`tests/vectors/abi-calculations.v1.*.json` 的新增两操作来自原 Python 正式执行链冻结；原十一请求和结果保留。概率、条件事件权重和期望仍为精确分数字符串。

## 单步回合

`kind: "battle_turn"` 必填 `state`、`type_chart`、`selection`，可选 `turn_limits`。

`state` 使用 [唯一状态合同](state.v1.md)，`type_chart` 使用原伤害知识快照。`selection` 为互斥对象：

| mode | attacker / defender |
| --- | --- |
| actions | 各为完整 use-move/struggle/pass 行动对象，形状与 legal_actions 输出相同 |
| policies | 各为 uniform-random 或 first-legal-action |

`turn_limits` 可含正整数或 null 的 max_branches/max_event_paths。省略或 null 沿用原 Core 无上限语义；显式保护超过实际中间分支/历史数量时返回 RESOURCE_LIMIT，整批没有部分结果，不裁剪概率后归一。

结果含 kind、transitions、phases、unsupported_aspects。每条转移完整保存 probability、state、paths、source_key；每条路径含完整 events 与当前后继状态条件下的精确 probability。阶段按原十一阶段不可重排，从 turn-start 到 turn-end。

随机事件保留 kind=random、event_type、event_id、outcome_id、numeric_value。业务事实保留 kind=battle 及相同随机身份，同时包含 battle_kind、turn_number、actor、target、move_id、source_identifier、value、before、after。任意精度解释数值使用十进制字符串，合法空值保持 null，不转换成零或缺失。

## 固定战斗

`kind: "fixed_battle"` 必填 state/type_chart/attacker_policy/defender_policy/observer。策略同上，observer 为 attacker/defender。可选字段：

| 字段 | 缺省及语义 |
| --- | --- |
| graph_limits.max_nodes | 20,000；显式 1…2,000,000，与原在线任务能力一致 |
| graph_limits.max_edges | 80,000；显式 1…8,000,000 |
| graph_limits.max_turns | 省略/null 继承 state.rules；显式 1…10,000 |
| max_equation_nodes | 省略/null 无上限，与原精确 solver 一致；显式正整数用于可见保护 |
| turn_limits | 同单步回合，省略/null 不加入额外执行裁剪 |
| include_graph | 默认 false；true 才传输完整节点、事件边及 SCC |
| graph_mode | 默认 `full`，保持原完整探索；`configuration_summary` 使用原任务的摘要构图和遇预算停止全部frontier语义 |
| include_root_action_explanation | 默认 false；true 在同次typed图上生成原 `battle-inference.explanation.v1` 完整归因对象，或明确null |
| progress_interval | 默认 100；每多少实际展开节点触发 Core 观察回调，正整数 |

生成图每批按请求上限预留最多 2,000,000 节点、8,000,000 边。该预算与显式 `graph` JSON 拓扑的 65,536/262,144 输入预算分开；固定战斗不复用显式 graph 的 128 方程保护。多项固定推演不能各自占满同一批次的全部配额。

结果顶层保留 kind=fixed_battle、observer、status、win/loss/draw/closed_cycle、expected_turns，另有 statistics、truncations、unsupported_aspects、graph。统计包含 nodes/edges/max_turn_number/closed_cycles/terminal_reachable_cycles 及五类 terminal_counts。完整图为所有节点状态、终止/保护原因、前驱节点/边、代表路径、精确带权事件边和全部 SCC；summary 模式 graph 为 null，不虚构空图。

构图节点/边/回合保护产生 unknown 节点、真实 truncations 和 incomplete-graph，概率为 null；不能变成数学平局或零胜率。封闭循环的 draw/closed_cycle 与无限期望保持原数学语义。显式执行/方程保护和传输输出超限是 RESOURCE_LIMIT，不提供部分业务结果。

`include_graph` 只控制传输，`graph_mode` 决定构图行为，两者独立。`configuration_summary` 保留原任务的状态、精确概率、根事件归因及预算统计；默认 `full` 保持探索前沿处理。`fixed_graph_query` 明确拒绝Summary输入，导航缓存不能用Summary计数验证Full重算。

可选 `root_action_explanation` 完整保留 version、basis、coverage、root、buckets、omitted_bucket_count、graph。桶内含双方move_id、精确概率与胜负/平贡献、条件概率、代表目标和path_count；TopK按原12桶，余量显式记录。根价值固定攻守轴，不随observer交换。未请求时不增加字段；请求后未解或无法归因时为null，取消仍撤销整批。Go直接保存该业务对象，实际engine/rules和输入SHA另存，不混入解释。

成功结果传输上限为 **32 MiB**，完整图事件逐项检查并保留整批原子性；调用者可请求 summary 避免传输大型图。事件/路径额外计数保护各为一百万，仍受同一字节上限约束。生成图预算不承诺任何规模都可在实际机器内存/时间内完成；失败分类和取消明确可观察，不提供近似概率。

## 机制边界

正式入口使用 `StandardTurnResolver` 和真实不可变 BFS/精确求解器，不能传入测试 expander。保留原默认结构化调用链的 Flinch、Fake Out、Choice Band 锁招、Multiscale、Inner Focus 及全部既有伤害行为。

unsupported_aspects 保存来源 source、标识 identifier、尚未实现能力 capability。冰冻拳冻结追加、劈瓦屏障破坏、Inner Focus 威吓免疫明确保留原缺口；原默认执行链未接入的主状态门禁/残余伤害、混乱/迷恋门禁不会悄悄添加。Life Orb 反伤等原未接通行为同样不补写。本接口表示原参考实现兼容，不表示完整官方历代规则覆盖。

## C 与 Go 进度观察

既有 `pbi_v1_compute` 完全保留。新增 `pbi_v1_compute_with_progress` 同步借用回调及 uintptr_t 数值上下文。`pbi_progress_v1` 含 struct_size、operation_index、phase、nodes、edges、expanded、frontier，计数来自实际 GraphProgressObserver；非构图操作不制造帧。

回调在调用线程同步执行，帧指针仅借用至本次回调返回；调用者必须先复制字段，不得保留指针、抛异常或在回调阻塞数据库。数值句柄须等 compute 和所有同步回调结束后销毁。进度不代表任务成功，后续仍可能返回失败/取消，结果仍整批原子。

Go `ComputeWithProgress(ctx, request, func(Progress))` 使用 cgo.Handle 管理观察者，C 只保留数值句柄。取消监视和同步回调结束后才释放资源；观察回调 panic 被转换成明确错误和原生取消，不跨 C 栈传播。Root Worker 在外部主循环写 PG，不能在 C 回调直接写库。

## 独立进程流

Core Worker 缺省仍输出单个原 ABI JSON。显式 `--progress` 输出 NDJSON：零或多个 kind=progress/progress 计数帧，以及唯一末尾 kind=result/response 完整原 ABI JSON。结果字节保持原样，不重新实现或重编规则。

CLI 只对观察层采样：同一操作的中间帧在节点增加 256、边增加 1024 或已展开增加 256 时发送，built 末帧必发；不改变 Core 回调、概率或任何业务事件。额外有限帧配额只合并中间观察，不丢最终结果。

`workerprocess.ExecuteWithProgress` 保留旧 Execute 的真实退出码/错误 JSON 对照。每流至多 65,536 帧/64 MiB，单个最终结果仍最多 32 MiB；拒绝未知/重复/末帧后数据，缺失结果不能成功。ctx 取消或协议超限会终止并回收本次子进程。CGO SIGSEGV 即使由 Go runtime 转为 exit=2，也只有完整对应错误结果才能识别为 unsupported，否则为 worker_crash。
