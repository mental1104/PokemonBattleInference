# P1 Core 迁移检查点

P1 仍为 **IN_PROGRESS**。纯 Core 正式回合、动态效果与固定战斗已有真实差分；配置候选生成正在独立验收，配置目标搜索及事件条件分析仍待迁移。正式 C ABI、跨语言链路与 Apple 构建各以对应真实验收为准。

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

测试脚本只提供可重放分支输入，不能当作 Pokémon 回合规则已迁移；正式固定战斗仍需要真实回合器。新批独立 `PBI_BUILD_ABI=OFF` 的 ASan/UBSan/leak **32/32 PASS**（1.58 秒），含新增六项转移/事件/构图测试；实际日志 `transitions-sanitizer.log`，未挪用旧 36 测试的 sanitizer 结果。

## 剩余依赖

现有事件/概率转移、不可变战斗图、正式回合器/动态效果与固定战斗的证据见下文。剩余链路为完整配置目标搜索、流式配置结果聚合、事件查询及反事实分析；各自仍需实际对照原调用链，不以已有图/SCC 能力推定这些业务算法已经迁移。

## Apple 标准库取消兼容修复（待本批复测）

提交 `e60eb2d` 的 [Native 45366954912](https://github.com/mental1104/PokemonBattleInference/actions/runs/45366954912) 实际失败在 Core 编译：AppleClang/Xcode 自带 libc++ 没有提供 `std::stop_token`，`graph.hpp`/`graph.cpp` 共九处类型错误；App 步骤尚未运行。原始日志在 `app-sync-20261124/github-native-45366954912.log`。不能将 GNU 工具链支持这项 C++20 库能力当作 Apple 已支持。

已核对全部调用只需要请求、读取和取得令牌，无回调依赖。新增纯 Core `CancellationSource`/`CancellationToken` 使用 `shared_ptr<atomic<bool>>` 的共享生命周期与单向原子标志：空令牌永不取消，源/令牌副本同源，源销毁后令牌仍有效；不增加轮询线程、实验编译开关或降低 C++ 标准。图/SCC/消元、不可变图 builder、适配解码和不透明 C ABI handle 都观察同一状态，C v1 函数和 JSON 合同不变。

新增三项原生测试覆盖空值、幂等请求、副本/移动、源销毁后生命周期及 16 读者/8 请求者并发。该修复与尚未完成的正式回合器分开；回合器新文件未注册到 CMake，未完成基础公式改动保存为私有 `core-graph-20261124/turn-in-progress.patch`，没有带入修复验证。

本批 `portable-cancellation-20261124/` 已实测：GCC14 与 Swift 工具镜像 GCC13 各 **49/49 CTest PASS**；`linux-final.log` 迁移 **23 passed / 1 skipped**（32.10 秒，仅工具镜像没有 Swift，含实际 Go `-a -race` 和 vet）；`swift-final.log` **20 tests / 3 explicit skip / 0 failure**（2.496 秒，跳过为未配置独立在线/同步测试 URL），含 Engine 运行中 Task 取消与真实知识 HTTP 更新；ASan/UBSan/leak **49/49 PASS**（433.29 秒，原大规模 GraphBatchNodeBudget 未跳过/缩减/重启）。首次 Go/Swift 委托分别遇到并行开发的缺失 reader 文件与 HTTP 夹具启动失败，原始日志保留，未把编辑期失败报告为全绿。Apple 修复仍由后续实际 GitHub CI 判定。

## 正式结构化回合与固定战斗（2026-11-24，待 P2 .6 接入）

新增 `turn.hpp/.cpp`，直接迁移实际 `BattleEventStandardMoveTurnResolver` 调用链，保留十一阶段、双侧行动身份、PP/上一招、命中/未命中、优先级与等级后速度、同速随机、直接伤害、挣扎最大 HP 反伤、濒死短路与回合末畏缩清理。`CalculateBaseDamage` 从原伤害链抽为同一纯 Core helper，挣扎复用该公式；静态直接伤害的所有原差分继续通过。

真实动态机制包括 ChoiceBand 选招锁定、FakeOut 首次出场限制/畏缩、Multiscale 实时满 HP 修正和 InnerFocus 畏缩免疫。静态 `damage` 入口仍明确拒绝需要实时状态的后两项，未将它们悄悄降为无效果。原尚未支持的 IcePunch 冰冻追加、BrickBreak 破壁、InnerFocus 威吓免疫，以及原默认回合管线未接入的主要状态/混乱/迷恋门禁和残余伤害，通过 `unsupported_aspects` 明确列出；不擅自加入官方规则、LifeOrb 反伤或原未执行的能力等级伤害修正。

`Expand` 组合原两种玩家策略与正式回合分布，每条路径保留原 `application.joint-action-probability` 的精确选择/随机概率元数据。`InferFixedBattle` 真实串联正式回合、BFS、SCC 和精确求解，返回拥有完整状态/事件图及有限/无限/不可用解。回合分支/事件历史超预算明确失败，不截断后重新归一；图节点/边/回合预算仍保留 unknown/incomplete，取消使用可移植共享原子令牌。

证据根 `turn-20261124/`：

- `native.log`：纯 Core **41/41 CTest PASS**，含新增六项正式回合测试。验证最后一点 PP、真实 FakeOut/InnerFocus/Multiscale、挣扎同时濒死、正式固定战斗胜率/期望、未知保护、预算/取消/未知机制。
- `differential-final.log` / `turn-tests-final.xml`：**7/7 pytest PASS**（3.94 秒）。**96** 个显式联合行动、**32** 个完整玩家策略展开，全状态、原阶段顺序、随机/业务事件全部字段与精确条件路径逐项一致；**4** 个真实固定战斗与保护场景对照原正式 expander/BFS/SCC/solver，比较完整图、每条边/代表路径/事件和全部概率/期望。旧 builder 两项及原静态 damage 三项同时通过，没有复制原算法作为 oracle。
- 首次随机场景因测试夹具写错 `BattleFieldState` 参数名而未进入比较；修正为原 `attacker_side_conditions`/`defender_side_conditions` 后，保留全部原断言并重跑通过，首次日志 `differential.log` 保留。
- `full-roll-differential.log` / `full-roll-turn-tests.xml`：正式回合差分 **3/3 PASS**（3.62 秒），在上述随机/固定场景之外增加 **12** 个完整 16 档显式场景，核对同速、FakeOut 首/非首次、InnerFocus、Multiscale 满 HP/差 1 HP、挣扎、最后 PP、75% 命中、濒死 Pass 和普通属性攻击幽灵免疫下的全部事件路径。
- `sanitizer.log`：本批纯 Core ASan/UBSan/leak **41/41 PASS**（2.26 秒），没有因无关旧大型 ABI 预算测试再次执行七分钟整套 sanitizer。正式 C ABI/Go/Swift .6 及 Apple 构建结果由 P2 后续实际验证，未用先前 .5 的绿灯替代。
- `fixed-battle-benchmark.json`：五个小型合成领域场景全部实际完整求解，分别覆盖优先 KO、同速 KO、挣扎互 KO、FakeOut 封闭循环和 75% 命中后挣扎；节点数 `[2,3,2,2,7]`、边数 `[1,2,1,2,6]`，五次采样每次完整精确结果一致。Python 中位 **0.062558 秒**，C++ 实际进程中位 **0.025591 秒**；包含 Python 模型投影与 C++ 进程/JSON/IPC，不外推到纯函数或完整配置空间。复跑入口 `python -m tests.migration.benchmark_core_turn --runner build/core/pbi_turn_vectors --repeats 5 --output /tmp/fixed-battle-benchmark.json`，固定证据副本 `docs/benchmarks/core-fixed-battle-20261124.json`。

## 标准四维配置候选与精确权重（2026-11-24，已注册纯 Core）

新增 `configuration_stats`、`configuration_moves`、`configuration_space` 三个纯类型模块；Go/Swift 不负责组合、过滤、等价归并或权重。输入为 version-aware 合法原候选、完整能力快照和原命令；输出是真正经过过滤、归并与保护校验的完整空间，不能用预先构造战斗状态的笛卡尔积代替。

能力维度按命令字段顺序、排序后的 EV 值和性格输入顺序惰性枚举；非负 EV 前缀超过 510 后直接跳过整段非法组合，只有合法原始 profile 消耗 `max_raw_profiles`。以实际六项能力值归并，保留第一个 EV/IV/性格代表和原标签；完整五轴 binary64 性格兼容旧预设仅提高单项 1.1、没有下降项的语义，不擅自替换成二轴性格。复用已有 HP/中性能力基础公式，再按原性格乘法 floor；概率与成员数仍为精确整数/有理数。预设或不可变用户快照的读取和解析仍属于输入组装。

招式维度区分命令排除、repository 可执行性和当前 factory 覆盖，保留每个合法候选的完整原因。支持候选按完整 MoveSpec 行为和 effect 归并，重复 projection 保留乘数；不同 projection 的同一招式 ID 不得占两个槽。默认少于四招取全量，达到四招仅枚举无序四招，显式模式保留 1..4 槽组合；原始组合成员数超过预算时整次失败。无附加 effect 的状态招式不会伪装成已实现。

特性/道具维度采用原 PokemonChampion factory 规则；未知机制和原声明 PARTIAL 的 InnerFocus 不进入标准生成空间。命令明确指定的无道具和受控道具按规范顺序枚举，不自动扩张全游戏道具表。保留原 generator 的整体支持判断；IcePunch/BrickBreak 的尚缺子能力仍可由较新的严格任务准入独立拒绝，不能混淆这两个旧入口。

单侧和双侧预算均按归并前原始成员计算。最终类按原 `repr(behavior_signature)` 排序，保留旧类索引和第一代表；原始成员均匀权重为 `member_count/raw_pair_count`，等价类均匀权重为 `1/unique_pair_count`，两种假设明确分开并验证精确总和为一。空支持维度、规则轴不匹配、超预算和取消整体失败，不重新归一化剩余子集。

证据根 `configuration-stats-20261124/`：初批三个模块 **11/11 原生测试 PASS**（独立编译），`space-differential.log/xml` **6/6 pytest PASS**（0.91 秒）：121 组原 `StatDimensionProvider`（120 随机受控 + 七个内置 preset 同组）、160 组原 `MoveSetDimensionProvider`、36 组双方真实候选各两种权重共 72 组完整原 `GenerateConfigurationSpaceUseCase` 对照，以及各层原始成员预算拒绝。逐字段比较完整行为键、首代表 EV/IV/性格、标签、招式名称、每项 coverage 字段/原因/顺序、每个配置对成员和精确分数；不复制原枚举/归并算法作为 oracle。初批 ASan/UBSan/leak **11/11 PASS**（6 毫秒），记录 `sanitizer.log`。最终 `space-final-differential.log/xml` **7/7 pytest PASS**（0.93 秒），额外完整对照 **40** 组原任意有限性格倍率（负值、正负零、非标准分数和小指数）对应的 binary64 floor 与原代表标签；没有以 25 种标准性格缩减旧输入范围。

最后追加非有限/输出溢出边界测试及性格去重从二次扫描改为有序集合后，单独重编译最终 stats 源并以 ASan/UBSan/leak **5/5 PASS**（2 毫秒），记录 `stats-final-sanitizer.log`；初批整包 11 项和本次 5 项各有独立运行记录，不冒称另跑了一套 12 项 CTest。冻结源文件校验清单为 `frozen-sources.sha256`。

在 `.6` 正式回合检查点 `76a40a0` 后核对上述 15 个冻结文件的 SHA256 全部一致，再于 `core/CMakeLists.txt` 登记三源、三项 GoogleTest 文件及三个独立 JSON 差分进程。新模块没有改变 `.6` C ABI、版本或 Go/Swift 桥接。独立 fresh 构建 `/build/p1-configuration-registered` 的完整旧/新 Core、ABI 与 C 头 **70/70 CTest PASS**（2.61 秒），七项配置差分 **7/7 PASS**（1.94 秒），证据 `configuration-registered-20261124/native.log/xml` 和 `differential.log/xml`。

注册审查同时根据 [LLVM 的浮点 to_chars availability 修订](https://reviews.llvm.org/D146367) 核实该 API 要求 macOS 13.3/iOS 16.3，高于项目 `Package.swift` 的 macOS 13/iOS 16 最低轴。已移除新标签格式化对该 API 的依赖，改用固定 classic locale 的科学计数流寻找最短精确 roundtrip 文本，不改变数值公式或全局 locale。增加最小/近最小次正规倍率标签对照后，最终增量重编的完整 **70/70 CTest PASS**，配置差分 **7/7 PASS**（1.31 秒）；记录 `portable-build.log`、`portable-native.log/xml`、`portable-differential.log/xml`。这是已核实部署约束的源码修正，Apple 实际编译仍以随后的 GitHub CI 为准，未声称已在 Mac 执行。

本批仅迁移真实默认四维，未声称旧运行时自定义 provider 插件、目标 EV 搜索、配置求解批量聚合或事件查询已经完成。三模块已注册纯 Core 和独立差分入口，尚未公开正式配置 ABI；后续由 P2 在新操作合同准备完毕后接入。最终本批冻结清单见 `configuration-registered-20261124/frozen-sources.sha256`，未覆盖前一批历史清单。
