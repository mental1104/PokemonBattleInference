# P1 Core 迁移检查点

P1 仍为 **IN_PROGRESS**。已验证的能力不能替代尚未迁移的完整回合、动态效果、固定战斗和配置搜索。

## 合法行动与有限概率图（2026-11-24）

`actions.hpp/.cpp` 复用不可变 `BattleState`：按动态槽位顺序检查 PP、禁用与讲究锁招，濒死方返回内部 Pass，无普通行动时返回 Struggle。行动保留稳定 side/move_id/priority/slot_id，不能用列表位置代替身份。已实现原 uniform-random 和 first-legal-action；玩家选择概率与命中/伤害/同速随机概率分开，分布严格验证正性、去重、合法集合与精确总和。

`graph.hpp/.cpp` 接收纯类型化的有限概率拓扑，Core 不读取 JSON、数据库或展示数据。节点与分量使用不同 ID 类型；图构造校验正概率、端点和非终局出边总和。迭代 Kosaraju 同时保留 SCC 编号、完整成员、出分量、分类及终局可达性，没有递归深度依赖。

求解器对 DAG 逆拓扑递推，对有出口循环使用 `(I-Q)X=B` 精确高斯消元；所有概率与期望值均为 `boost::rational<cpp_int>`，不用浮点容差。无出口循环计入平局并单独保留 closed-cycle 概率；只有该概率大于零时，期望回合为 infinite。显式平局、无限循环和未知截断互不混同。方程节点上限只约束消元，不约束 DAG；未知/截断、资源限制、奇异方程、取消返回不携带部分概率的互斥失败结果。

实际 Linux 证据在 `/volume1/homes/mental1104/Backup/PokemonBattleInference/core-graph-20261124/`：

- `native-final.log`：C/C++ **36/36 PASS**，含新增 2 个行动域测试和 6 个图域测试（原 28 项仍通过）；图遍历另有 **12,000** 节点深链、200 位分母与预先取消验证。
- `graph-tests.xml`：真实 `pbi_graph_vectors` 进程与原 Python `analyze_strong_components`、`PurePythonBattleGraphSolver` 差分 **3/3 PASS**（1.16 秒）。完整比较 **128 DAG、96 有出口循环、64 含封闭循环拓扑、7 边界输入、2,500 节点深链**，逐项核对全部 SCC/胜负平/封闭循环/有限或无限期望；没有复制原算法作为测试 oracle，也没有放宽分数相等断言。
- 编译时 `-Werror=missing-field-initializers` 曾捕获测试节点缺少 field 初始化；已补完整初始化并保留原警告策略，首次失败日志为 `native.log`。
- `sanitizer.log`：上述 **36/36** C/C++ 测试在 ASan/UBSan/leak 下通过（32.52 秒）。
- `graph-benchmark.json`：同组 **240** 拓扑（2,770 节点、6,740 边），五次采样且每次完整结果精确一致。原 Python 中位 **0.618002 秒**，C++ 实际进程中位 **0.087117 秒**；Python 包含领域输入投影和输出模型，C++ 包含进程、JSON 和 IPC，这不是纯函数或完整战斗 benchmark。可复跑入口为 `python -m tests.migration.benchmark_core_graph --runner build/core/pbi_graph_vectors --count 240 --repeats 5 --output /tmp/graph-benchmark.json`；固定证据副本在 `docs/benchmarks/core-graph-20261124.json`。

`pbi_graph_vectors` 是差分进程适配器，其 JSON 只存在测试边界，不能当作正式 C ABI。P2 负责把这些稳定 typed 接口纳入版本化 C ABI/Go/Swift，尚不能声称正式 fixed_battle 入口已实现。

## 条件历史与不可变战斗图（2026-11-24）

新增 `transitions.hpp/.cpp`：随机事件与业务事件用不同 variant 类型保留；结构化业务事件包含回合、主体/目标、招式、机制、数值和 before/after，保留任意精度整数和原稳定事件身份。事件摘要对相同完整历史去重，串联按条件概率相乘，同状态替代历史按父分支绝对概率重基准；不同顶层来源归并时清除单值 source_key，完整路径继续保留。

新增 `battle_graph.hpp/.cpp`：真正调用回合级 expander 的 BFS 按完整 StateKey 去重，保留首次发现前驱、代表路径、完整随机边/历史、SCC 和实际进度。先检查每个节点的整组出边预算再提交；节点/边/回合上限均记录 unknown，而非伪造平局。完整图可以直接投影到同一精确图求解器。

纯 Core `PBI_BUILD_ABI=OFF` 的新增 **6/6** 测试已通过，含运行中取消与全部主要不变量；日志 `transitions-native.log`。真实 Python builder/事件差分与前项拓扑差分合计 **5/5 PASS**（1.41 秒），图/行动/转移/事件域 **14/14 CTest PASS**；证据为 `battle-graph-differential-final.log` 与 `battle-graph-tests.xml`。新增 **106** 组构图输入完整对照原 `StateGraphBuilder`，逐项比较全部状态字段、前驱/代表路径、每条边/随机与业务事件/条件权重、SCC、三类预算保护和统计。独立适配器初次因缺少 `contracts/c` include path 编译失败，修正 target include 路径后通过，首次日志保留在 `battle-graph-differential.log`。

测试脚本只提供可重放分支输入，不能当作 Pokémon 回合规则已迁移；正式固定战斗仍需要真实回合器。新的转移/构图 ASan 批次正在独立执行，不将前项 36 测试的旧 sanitizer 结果挪作本批证据。

## 剩余依赖

下一条真实计算链为：带条件权重的事件/概率转移 → 不可变战斗图构建 → 正式回合器/动态效果 → fixed_battle/graph/step → 配置空间搜索及事件分析。回合阶段、资源截断、PP/状态/道具效果与 Python 行为都必须继续实际差分；未支持机制必须明确失败，不能用无伤害回合或假的完成状态顶替。
