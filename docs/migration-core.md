# P1 Core 迁移检查点

P1 仍为 **IN_PROGRESS**。纯 Core 正式回合、动态效果、固定战斗、配置搜索及事件分析已有真实差分；最新组合与消费者证据如下。正式 C ABI、跨语言链路与 Apple 构建各以对应真实验收为准。

## 2026-11-25 正式0.11组合验证

独立登记的`abi11-verification`从b476d0f固定基线整合已冻结的Summary构图、根行动完整归因、透明上下文、原独立状态门禁、stateless snapshot及reference provider codec。`summary-snapshot-abi11-20261125/native-first.log`记录 **149/149 CTest PASS（14.45秒）**及 **111 Python差分/Go委托PASS（187.54秒）**；207项缺外部PG/HTTP/Swift环境明确SKIP。新共享样本42个，前39项数学结果保持不变；正式32MiB边界和Full图导航保持。

统一入口为`make test-native CORE_BUILD_DIR=/build/root-summary-abi11`。该GCC14 archive冻结后不再覆盖；同源码GCC13兼容archive已独立构建为`root-summary-swift11`，没有链接GCC14/glibc2.41产物。`serial-resume-20261125/swift-live-abi11/`实际Swift/Go/PG/daemon **27/27零SKIP通过（7.971秒）**，含42共享样本；新版Apple构建仍未验证。根行动原参考缺少BattleSide导入的独立修复记录为BASE-EXPLANATION-001，差分使用明确修正后的oracle。

串行消费者检查点`serial-resume-20261125/worker-abi11/`：新任务显式冻结`graph_mode=configuration_summary`及`include_root_action_explanation=true`，真实PG/独立child/daemon **11/11 race PASS（4.181秒）**且vet通过。成功说明核对另一次真实child完整归因对象，实际版本/输入SHA仍独立保存；显式graph没有归因时保持nil。公开HTTP完整结果及预算诊断的后续复验单独记录，不把该11项当作全API验证。

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

## 原 job-v1 具体配置池与严格准入（2026-11-24，待 P2 正式协议接入）

`job_move_pool.hpp/.cpp` 直接迁移原 `configuration_space/one_on_one/commands.py` 的固定配置和具体候选池。双方总候选数最多 20；每侧少于四招只取全池，达到四招按自然 ID 字典序枚举恰好四招，攻方外层、守方内层。10+10 精确保留 **44,100 个具体 case**，不以通用 `configuration_space` 的等价代表或 `member_count` 替代。`CaseAt` 用组合数按原索引定位，`Page` 有界惰性生成并整页取消，不缓存完整 case 集合，也不缩减原始分母。

固定 Pokémon/form/level/stat_profile_id/ability/item、规则轴、计算修订和 v1 维度模式均按原合同校验，所有身份文本继续要求 ASCII 非空规范化。pair ID 是原 `one-on-one-configuration:` 加紧凑六位置可读 canonical JSON，**不是 SHA**；两侧 ID 则是原 `one-on-one-side-` 加原八位置数组的 SHA-256。保留 `null`、引号/反斜杠、全部 ASCII 控制字节，以及 pair `ensure_ascii=False` 与 side `ensure_ascii=True` 对 DEL 的不同编码。正式 common C++ 子模块没有对应 SHA-256 可复用，局部 SHA 实现仅服务该旧身份协议，没有增加通用加密 API。

`configuration_admission.hpp/.cpp` 将原 `ListBattleCandidatePoolUseCase._admission` 的最终严格准入留在 Core。工厂显式区分原标准 PokemonChampion 与真实 HTTP composition 的 Transparent 版本；标准默认行为不变，透明版 `pressure`/`pickpocket` 为整体 SUPPORTED 的中性占位，但缺失 `real_ability_behavior`，故严格准入必须是 PARTIAL。基础字段不足、部分覆盖、未知机制、明确 no-effect 和允许无附加效果分别处理；原 repository 三态不替代最终工厂裁定。严格准入在任务创建前整池执行，具体 case 迭代不会边过滤边继续缩减候选。原公开中文 coverage reason 按既有 HTTP 合同保留，未新增本地化日志或异常。

实际 HTTP 还经过 `FactoryReconciledBattleInferenceRepository`：能提升为可执行的 move/ability/item 会先追加 `Factory reconciliation` 原因，再由严格边界追加 `Current factory coverage`。Core 的 `ConfigurationRepositoryMode` 显式区分 raw 与 factory_reconciled；后者根据真实产品/基础字段完成这层对账，外层只提供原 repository 原因，不在 Go 拼接或裁定工厂结论。默认 raw 保持直接 `_admission` 的独立合同，真实 HTTP 使用 transparent_inference + factory_reconciled。

证据根 `job-move-pool-20261124/`：

- `native.log`：新增 **5/5 GoogleTest PASS**，含完整固定 canonical 文本、44,100 计数和边界索引、唯一 ID/固定维度/20 招限制、分页/取消，以及默认/透明工厂和严格 no-effect/PARTIAL 差别。
- `final-differential.log/xml`：**2/2 pytest PASS**（2.71 秒）。原 `OneOnOneMovePoolCommand.iter_configurations` 与 `case_definition` 对照全部 **44,100** case 的顺序、完整 canonical pair ID、两侧 SHA、技能组和精确权重，另对照 **64** 组随机有界页，强制覆盖全部 ASCII 字节、跨 SHA 分块长度、空页和末页。没有另写 Python 组合/JSON/SHA 算法作为 oracle。
- 同一差分另有 **512** 组真实两类工厂和原 `_admission`，逐字段比较所有来源、四种 raw repository 状态、基础可执行性/NO_EFFECT 开关组合的完整工厂与严格 status、reason、missing identifiers 和 selectable。
- `pure-sanitizer.log/xml`：注册新源和测试后的完整纯 Core ASan/UBSan/leak **58/58 CTest PASS**（2.86 秒），独立 Debug 缓存 `/build/p1-job-pure-san`；未运行或挪用 P2 的正式配置 ABI/Go/Swift .7 结果。
- `composition-differential.log/xml`：补上实际 repository 对账层后重跑 **2/2 PASS**（2.71 秒）；保留所有 44,100 身份/64 页对照，并将 strict 扩为 **1,024** 组 raw/reconciled × standard/transparent 全链输入，直接调用原 `_move/_ability/_item` 对账和原 `_admission` 比较完整原 reason/status/missing/selectable。最终纯 Core sanitizer 再次 **58/58 PASS**（2.84 秒），记录 `composition-sanitizer.log/xml`；最终纯源冻结清单为 `frozen-pure-sources-composition.sha256`，前一清单保留作历史证据。

纯 Core 的 admission/job 源、五项测试和独立 job JSON 差分入口已注册 CMake；正式版本和 ABI 操作仍由 P2 同步。目标 EV 搜索、配置流式执行 orchestration 和事件分析仍未完成；独立结果聚合切片的证据见下一节。

## 流式配置结果的精确聚合（2026-11-24，独立模块未注册）

`configuration_aggregate.hpp/.cpp` 真实迁移 `stream_configuration_pairs/aggregation.py:AggregateState`。成功、截断与失败用互斥类型表达，未完成结果不能携带部分概率；每次显式 `Add` 累计全部尝试数、三种状态数、原配置权重和全部已尝试节点/边资源。加权胜负平只纳入成功结果，精确总和为 completed_weight；失败、截断和未执行配置的权重不重新归一化，也不会把不完整概率解释成零胜率。

三个有界 Top-K 分别按原胜率降序、有限期望回合降序、节点数/边数降序，使用 pair_id 作为稳定 tie 轴；相同 pair_id 和指标仍保留执行先后顺序。无限期望不进入有限期望排行。保留完整排行身份/技能组/胜负平/期望/资源，额外内存只与 K 有关，接口不接收或缓存完整状态图。重复观察按原执行流累加，不擅自加入与数据库幂等语义混淆的去重。

所有权重、概率和期望使用精确有理数；配置数和累计资源使用任意精度整数。完整保留原 Fraction 的中间观察次数、最大分子/分母位数和最终三类概率位数。原聚合器没有分数位数截断预算，本切片不新增上限改变原成功结果。六类原停止原因均保留，只有处理数等于完整配置数时最终原因统一为 completed；配置/节点/边/失败数量预算的执行循环仍属后续 orchestration，不能将这些摘要当作已实现完整调度。

证据根 `configuration-aggregate-20261124/`：

- `native.log`：独立实际编译的 **5/5 GoogleTest PASS**，覆盖原完整空间分母、全部结果桶/资源、K 限制、有限/无限期望、稳定 tie、重复观察、200 位分母、100 位资源计数，以及无效输入/空间拒绝。
- `differential.log/xml`：真实 C++ 进程对照原 `AggregateState`，**1/1 pytest PASS**（0.71 秒），包含 **384** 组随机完整/部分结果流。逐个 Add 比较全部进度，再比较最终全部计数/权重/概率、三类 Top-K 的每一项完整字段、停止原因及全部分数复杂度；不复制原统计或排序算法作为 oracle。
- `sanitizer.log`：独立新模块 ASan/UBSan/leak **5/5 GoogleTest PASS**（3 毫秒），没有借用前面候选或 job 批次的 sanitizer 结果。

本切片五个新文件仍未登记 CMake、版本或 ABI，按主 agent 指示独立冻结；尚未纳入正式在线/离线链路。冻结校验清单为同证据根 `frozen-sources.sha256`。

## 完整模板目标求解与实际 WithSpeed 入口（2026-11-24，待主 agent .8 公共注册）

`configuration_goals.hpp/.cpp` 迁移原完整模板搜索，并作为后续 EV 搜索的同一目标求值基础。它复用既有基础能力/伤害公式，按原默认十模板顺序或显式用户顺序去重逐项计算；同一候选必须满足全部目标。达到原 max_candidates 后立即停止，不先算完整空间再截列表。无解返回第一失败模板的完整目标证据；攻击要求总伤害 `>= HP`，防守要求 `< HP`，失败防守的剩余 HP 可以为负。没有新增原需求外的求值次数预算或统计 API，求值器使用只读 const 接口和共享取消。

读取实际 `configuration_solver.py` 后确认 `/solve` 和 `/search-spreads` 均已使用 WithSpeed 派生用例。因此本切片同时覆盖 damage-only、speed-only 与混合目标：比较候选实际 Speed 严格大于目标实际 Speed，同速失败；不加入原未纳入的状态、道具、天气或能力速度修正。两类目标共享唯一 ID 空间，无解保留首个失败模板的伤害与速度证据，不被后面的模板覆盖。仅有速度目标时也能真实求解，不伪造一个伤害目标。

原目标使用无实时 HP 的静态 DamageContext。Multiscale 只实现动态 `modify_battle_damage`、InnerFocus 只处理畏缩，在原静态上下文不修改伤害；本切片在 Core 内显式保持此语义，不改变既有 `damage` 默认拒绝合同或真实 fixed_battle 回合的动态行为。模板或不可变 snapshot 的完整 EV/IV/五轴性格在输入组装阶段提供，实际能力、选档、阈值、速度比较与候选选择全部由 Core 完成。

专属正式 codec `configuration_goals_contract.hpp/.cpp` 提供 `ConfigurationTemplatesRequest`、`ReadConfigurationTemplatesRequest` 与 `EvaluateConfigurationTemplates`，操作名 `configuration_templates`；差分 runner 的模板路径直接调用该 codec，不另写第二套演示计算协议。输入保留 subject_base、原模板快照、原 allowed 顺序、已准备伤害/速度参照、规则策略与完整所需相克知识；输出包含 kind、可达性、候选实际能力、全部目标/完整伤害证据和双类拒绝证据。独立三项正式 golden 在 `tests/vectors/configuration-templates.v1.json`，不修改 .7 已冻结的十九项公共数学向量。

证据根 `configuration-goals-20261124/`：

- `registered-native.log/xml`：新六项目标测试与全部既有 Core/ABI/C 头 **83/83 CTest PASS**（1.89 秒）。
- `registered-differential.log/xml`：正式 codec 路径 **3/3 pytest PASS**（0.62 秒），含 **65** 个原基础公开 Solve（64 随机 + 自定义 snapshot）、**32** 个真实原 prepared 静态能力目标、**64** 个实际 `SolvePokemonConfigurationWithSpeedUseCase.execute`（纯伤害/纯速度/混合、同速、模板顺序/上限与双类首失败）。逐项目标比较全部数值、方向、原角色和完整伤害 roll/trace/KO，不用 C++ 结果推导预期。
- `registered-sanitizer.log/xml`：注册新纯源后的全部 **64/64** 纯 Core ASan/UBSan/leak CTest PASS（3.13 秒）。
- 三个正式 golden 各自在写入前再次通过原公开 WithSpeed 用例和完整伤害 oracle：damage-only、严格同速不可达、混合自定义速度 snapshot；不是从未经对照的 C++ 输出直接冻结。

纯源、专属 codec、runner 与原生测试已登记 CMake；公共 `abi.cpp` Operation/dispatch、.8 engine/rules 和 Go/Swift 由主 agent 统一接入，未冒称 .7 已可调用该新操作。完整 EV/IV/性格反推与事件分析继续迁移，不能以本模板搜索替代真正 EV 搜索。冻结源文件清单见本证据根 `frozen-sources.sha256`。

## 实际 WithSpeed EV/IV/性格反推（2026-11-24，待公共注册）

`configuration_spread_search.hpp/.cpp` 直接迁移实际 HTTP 使用的 `SearchPokemonStatSpreadsWithSpeedUseCase.execute`。完整 25 性格事实由知识边界注入，Core 根据当前目标相关轴合并等价性格，保留原偏好代表和全部可选性格顺序。攻击/特攻、严格速度和防御/特防分别使用原 4EV 网格二分，遍历 HP 权衡，在构造能力分布前执行 510 总量过滤，再以同一 `ConfigurationGoalEvaluator` 验收全部伤害与速度目标。相同组和六项实际能力按原成本选代表，全体排序后才取原 max_candidates；没有用十模板、预构造状态 Cartesian 积或外层 Go 搜索替代真正反推。

最终候选保留原稳定 candidate_id、EV、6V、六项实际能力、等价性格与全部双类目标证据。EV/IV 六个区间按原整数二分计算，表示其余五项固定在代表值时该单项独立可调整的范围，不能任意联合组合。没有速度目标时代表 Speed EV=0、IV=31，但 IV 安全下界可以为 0；无解保留首性格组的零 EV/6V 基线全部证据，不自动放宽目标。取消整体失败，没有增加原需求外搜索预算。

正式 `configuration_spread_search_contract.hpp/.cpp` 提供 `ConfigurationSpreadSearchRequest`、`ReadConfigurationSpreadSearchRequest` 与 `EvaluateConfigurationSpreadSearch`，操作名 `configuration_spread_search`。输入仅有 subject_base、25 性格、已准备目标和规则/相克知识，不接受已求解候选。模板 codec 的目标读取与目标/能力/速度结果投影已提升为同一内部共享函数，模板公开合同不变，避免两个求解入口出现不同伤害上下文或输出证据。差分 runner 直接执行正式 codec；独立三项 golden 保存在 `tests/vectors/configuration-spread-search.v1.json`。

证据根 `configuration-spread-search-20261124/`：

- `registered-ctest.log`：新增四项真实反推边界与全部旧 Core/ABI/C 头 **87/87 CTest PASS**（1.93 秒）。
- `registered-differential.log`：模板共享 codec 回归三项及 EV 完整差分两项 **5/5 pytest PASS**（24.45 秒）。EV 对照 **36** 个原公开 WithSpeed execute，其中 **24** 个纯伤害/纯速度/混合和 **12** 个同一配置四轴攻防加可选速度的完整案例，逐字段比较全部候选 ID/成本顺序、等价性格、EV/IV、六项独立范围、全部目标及完整伤害 roll/trace/KO、无解基线。
- `asan-ctest.log`：登记 EV 纯源后的完整纯 Core **68/68 ASan/UBSan/leak CTest PASS**（3.59 秒），独立 Debug 缓存 `/build/p1-job-pure-san`。
- 三个专属 golden 在写入前逐例通过原完整公开搜索与伤害 oracle：严格速度、攻击与速度混合、最大速度同速不可达。

该批纯源、专属 codec、runner 和测试已登记 CMake，公共 ABI Operation/dispatch 和版本由主 agent 统一接入。事件查询/产品图/反事实和配置事件聚合仍在迁移，不能将本批证据解释成 P1 全部完成。

## 完整事件历史、独立反事实与配置事件加权（2026-11-24，待公共 v9 注册）

`event_analysis.hpp/.cpp` 迁移原 `BattleEventAnalyzer` 的完整产品自动机，不把单边命中概率求和当作全历史概率。原图每条边的每条替代事件路径按“边绝对概率 × 路径条件权重”分别展开；独立分析状态包含原节点、饱和次数、首次回合、范围命中和下一回合桶，不修改战斗 StateKey。次数与回合桶使用任意精度整数，保留 ANY/FIRST 回合语义、整条历史 min/max 次数限制和 never/overflow 分布。产品图与二分类属性图直接复用既有 SCC/精确吸收求解器，封闭循环保留无限历史；unknown、截断或不能精确求解的图整体拒绝。

输出完整基线胜负平、事件概率、事件与观察方获胜联合概率、正反条件胜率、首次/次数分布、结构化路径组覆盖、关键事件身份与实际产品图规模/求解次数。零条件概率显式为 undefined-zero-condition，没有以零代替不可定义。事件谓词使用完整结构化字段 AND 语义，不解析展示文字。元数据覆盖保持原先“先按完整事件去重、再按摘要身份计数”的顺序，数值不同的同身份事件不会被提前合并；这些覆盖计数不冒充随机概率。

`event_analysis_batch.hpp/.cpp` 同时迁移两个原公开领域入口：`AnalyzeCounterfactualEvents` 强制执行两次独立 runner，验证不同 revision、返回 revision 一致以及不同 run ID，然后对两套完整图分别分析并计算对照减基线的三个精确差值；原合同的 exact_solver_runs 统计两个事件分析，不推测 runner 内部额外求解。原源码只有规则覆盖/推演 runner 端口，没有通用规则键到机制的映射，因此没有发明映射或接收两份旧图伪称重算。原生集成中的 runner 每次真正调用 InferFixedBattle，覆盖标准回合、BFS、图投影与事件分析；Python 反事实差分另明确使用原端口夹具，不能将夹具视为公开生产操作。

`AggregateConfigurationEvents` 保留原完整配置分母和输入组顺序，配置数量/可能配置数量、配置权重覆盖、未解析权重与加权战斗概率分开。失败/截断/未分析的权重不重新归一化；重复身份、不同 observer/query 或已分析与未解析权重不精确和为一时整体失败。正式 `event_analysis_contract` 与 `event_analysis_batch_contract` 分别读取 event_analysis / configuration_event_analysis，后者逐组真正分析原图后再调用同一纯聚合器，不从外部接受预计算概率。紧凑图输入只投影原结果、拓扑、完整事件路径及 root 实际回合；从完整图拆字段不涉及任何概率或分组业务计算。专属三项 golden 为 `tests/vectors/event-analysis.v1.json`。

证据根 `event-analysis-20261124/`：

- 首轮单图原完整差分 48 个 DAG/开放循环/封闭循环全部通过；补充同身份不同数值、百位次数/回合后共 **51 个完整单图案例**，另有 **32** 组原配置事件聚合与 **16** 组原反事实完整双结果对照。
- 四个活动 metadata 文件复制前后 SHA 一致；Core、C ABI、头文件和向量冻结到 `/build/p1-event-frozen-source`，完整输入清单为 `frozen-build-inputs.sha256`。fresh Release `frozen-normal-ctest.log` 为 **103/103 CTest PASS**（2.85 秒），包含新增九项事件原生检查、两个正式运行中取消回归及全部旧接口。
- `frozen-differential.log`：模板/EV 回归和上述事件完整差分 **10/10 pytest PASS**（32.47 秒），不是抽样单一概率或浮点容差检查。
- `frozen-pure-san-ctest.log`：完整纯 Core ASan/UBSan/leak **82/82 PASS**（7.01 秒）；`frozen-selected-abi-san-ctest.log`：完整 fixture、进度、原 256 次 ownership、32 并发调用及两个运行中取消 **6/6 PASS**（70.31 秒），没有缩短旧检查预算。
- `frozen-event-codec-san-differential.log`：真实 sanitizer 编译的正式事件 codec 对照原完整实现 **5/5 pytest PASS**（3.15 秒），覆盖读取、业务事件身份验证、产品求解和完整输出。
- 首轮活动目录增量构建的四项旧完整 fixture 调用 SIGSEGV 保留在 `registered-ctest.log`；它们在同一冻结输入 fresh 构建的正常和 sanitizer 检查中全部不复现。本批结论以冻结检查为准，没有强行推断旧增量二进制的精确失败原因。

14 个事件源/测试/codec/golden 的冻结清单为同证据根 `frozen-sources.sha256`。纯源、正式 codec、runner 和九项原生测试已登记 CMake；公共 ABI v9 注册仍由主 agent 统一完成，测试端口 counterfactual_fixture 不属于公开 ABI。

## v8 模板/EV 运行中取消错误码修复（2026-11-24）

新增独立公共 C ABI 回归使用合法 20 个目标与最大合法随机档，先确认 pbi_v1_compute 已运行 30 毫秒，再从另一线程取消。修复前模板和 EV 均实际返回 PBI_INTERNAL_ERROR / internal_error，而非 cancelled；`configuration-cancellation-20261124/red-valid.log` 保存两个真实 RED，另一个准备错误的早期输入保留历史日志但没有计为有效复现。

两个自有 codec 现在捕获纯求值器的 runtime_error 后重新检查同一取消令牌，将实际取消转换为既有 RequestError(PBI_CANCELLED_V1)，非取消异常保持原语义。模板输出候选时也检查取消。没有修改 abi.cpp、版本或共享 golden。冻结 fresh 的 103 项正常检查及选定六项 ABI sanitizer 均包含这两个真实运行中取消 GREEN；批次前面已经完成的 hp 结果也整批撤销，不发布部分 results。两 codec 与新 `configuration_cancellation_test.cpp` 的三源清单见该取消证据根 `frozen-sources.sha256`。

## 明确的 reference_static 伤害上下文（2026-11-24，待公共 v9 context 注册）

新增唯一 typed 入口 `CalculateReferenceStaticDamage`，与默认 `CalculateDamage` 共用同一个私有验证和伤害阶段链。默认严格入口继续拒绝 Multiscale/InnerFocus；显式参考静态入口只接受这两种已知能力在原无实时 HP/畏缩 DamageContext 中没有伤害 hook 的语义，未知枚举仍拒绝。它保留输入能力身份，不猜测满 HP，不清空能力，也不复制完整 Pokémon/policy 来绕过严格验证。显式天气、场地、屏障、进化、接地、道具及所有原伤害标志均照原链处理；真实回合动态层没有改动。

模板目标的 StaticPokemon 现在仅投影原快照字段，并改用同一 typed 入口，消除目标与直接静态伤害各自维护两能力归一规则的重复。目标快照原本的 can_evolve=false / grounding=null 语义仍保留。默认伤害、显式参考静态与真实回合是不同调用合同，不能在 Go 清空能力或借模板操作间接计算。

证据根 `reference-static-damage-20261124/`：

- `native.log`：新增 **3/3 GoogleTest PASS**，覆盖两侧两能力组合、原 16 档 99..117 不减半、默认仍拒绝、完整输入不变、其他静态事实保留及未知/知识缺失/变化招式拒绝。
- `differential.log`：**1/1 pytest PASS**（0.31 秒），含 **192** 个原完整静态责任链案例，覆盖全部九种能力的双侧组合、九代际、全部天气/场地、道具、进化/接地、屏障/会心/范围/保护/多目标和自定义无序随机档，逐字段比较所有 rolls、trace、基础伤害与精确 KO。
- `all-native.log` / `all-san.log`：将新 damage/goal 实现与冻结的全部旧纯 Core 测试对象/库重新合链，分别 **85/85 GoogleTest PASS**（42 毫秒）及 **85/85 ASan/UBSan/leak PASS**（1.491 秒）；包含原真实回合六项，确认动态 Multiscale/InnerFocus 仍按原 HP/畏缩机制处理。
- `shared-differential.log`：实际重链模板/EV runner 后，静态伤害一项、模板三项、EV 两项 **6/6 pytest PASS**（24.93 秒），确认目标/搜索复用新入口没有改变任何旧候选或证据。
- 独立 `tests/vectors/reference-static-damage.v1.json` 两项完整 operation 带 context=reference_static。全部 expected 来自原 calculate_damage_rolls、原责任链 trace/base 和原 estimate_ko_chance（16 档概率可精确表示为 Fraction），然后才核对 Core；没有从 Core 输出反推预期。两个合法 Dragonite 静态快照分别覆盖 Multiscale 无实时 HP（OHKO=9/16）以及 InnerFocus/ExpertBelt/Reflect/多目标（OHKO=1/4）。

七个源/测试/golden 文件的最终清单为该证据根 `frozen-sources.sha256`。依主 agent 指示，本批尚未自行修改 CMake、公共 ABI kind/optional context、版本或旧共享 golden；公共注册及 Go/Swift 消费由主 agent 统一接入，不将 typed 结果冒称已完成 HTTP 200 兼容验收。

## 原透明工厂的 Pressure/Pickpocket 兼容（2026-11-24，待统一 v10 注册）

实读并执行原 TransparentPokemonChampionEffectFactory、PokemonSpec 与 DamageAbility.from_identifier：原 pressure、pickpocket、unknown、none 和空能力均投影到同一个 UNKNOWN，SpecKey/StateKey 相同。既有 ABI 的 none 正是该 UNKNOWN 的 wire 拼写，不能为“保守”而改变原等价关系。新增显式 spec.ability_context=transparent_inference 仅对白名单 pressure/pickpocket 保留原始可重放标识，内部仍执行原 UNKNOWN 中性行为；raw 标记不参与 Spec/StateKey，相同图节点依原规则合并。StateJson 保留 raw/context；节点机械展示仍使用原 unknown。覆盖明确返回 missing real_ability_behavior，不实现原本不存在的 PP 加倍或道具偷取。默认严格输入、白名单外能力及未知 context 继续拒绝，原严格任务准入也不放宽。

证据根 `transparent-abilities-20261124/`：新增纯域三项与正式 state codec 两项原生检查全部通过；`all-native.log` 为完整 **90/90 GoogleTest PASS**（51 毫秒），`all-san.log` 为完整 **90/90 ASan/UBSan/leak PASS**（1.718 秒），`contract-san.log` 另有正式 codec **2/2 PASS**。`differential.log` 的两项 pytest 包含原五种 UNKNOWN 别名实际 Key 证明，以及 **48 个真实透明工厂回合展开 + 12 个固定图/节点边回合截断**完整对照，2/2 PASS（2.35 秒）；同一套真实 sanitizer runner 的 `differential-san.log` 2/2 PASS（6.16 秒）。比较包含完整状态、事件、概率、SCC/解，并独立逐个后继/节点核验 raw/context 没有丢失。`strict-differential.log` 为原 transparent/standard 严格准入矩阵 **1/1 pytest PASS**（0.48 秒）。

八个源/测试的清单为该根 `frozen-sources.sha256`。主树尚未登记 P2 提取的唯一 sha256.cpp，常规全测试 target 首次链接因此失败，原日志保留；本批完整测试使用相同 fresh 编译对象/库并显式链接该唯一共享源，没有复制 SHA 实现，也没有把这个链接失败冒称完整 CMake 绿灯。公共 CMake/ABI 及真实 HTTP 接入由主 agent/P2/P3 统一登记验收。

## 原 winning_paths 完整算法链（2026-11-24，待统一公共 ABI/HTTP 注册）

新增唯一 `ListWinningPathGroups` 纯用例，完整迁移原 ListWinningPathGroupsUseCase：按原正式边顺序的有限无重复节点 DFS、回边引用与原 100000 walk 预算、联合行动序列归并、配置/路径/前缀 SHA 身份、最大单 walk 代表路径、全部替代历史离散伤害与关键事件、精确图胜率、稳定 Top-K/分页、当前页前缀及不重归一的返回覆盖率。回合从 source 实际 state 读取，历史数量是各边原替代历史数的任意精度乘积，不是条件概率；主行动先读取整条历史的 MOVE_SELECTED，只有整条完全没有时才回退 MOVE_USED，各侧取首事件。这与节点 projection 的严格双方选招分组不同，未复制 P2 的另一套 groupID/分组器。

配置使用机械 UNKNOWN、原无序招式组排序与原 JSON SHA，透明 raw 特性不偷偷改变配置身份。循环只截断有限 walk 展示，完整 winner_probability 仍复用唯一 Core 精确求解器。保留原传入 CLOSED_CYCLE 的吸收边界；原空 SCC 分类的开放环仍可求解，空分类的封闭环仍是奇异不可用，不能为了补充分类擅自返回零胜率。循环 component_id 使用输入原身份，原空列表保持 null。

正式 `winning_paths_contract` 输入为 graph_id/calculation_revision/winner/limit/cursor/sort 与原完整 nodes/edges/components/truncations（可附 statistics，root 默认 0）；不接受 Go 算出的配置 SHA、offset、动作或胜率。Core 自己校验绑定图/版本/配置/胜者/排序的原 URL-safe base64 cursor，保留原错误文案、Python ensure_ascii 的 Unicode/DEL 字节和超机器整数 offset。JSON 数字词法在边界保留，500 位合法 offset 不经过 double 或 uint64；没有为此扩大原数学查询预算。复用 P2 唯一 ReadProjectionNodeValue / ReadProjectionEdgeValue / ExactProbabilityJson 与原事件 reader、唯一 sha256.cpp；没有复制状态读取、事件身份校验、ties-to-even 展示或 SHA 实现。

证据根 `winning-paths-20261124/`：

- `native.log` / `san-native.log`：新增 **5/5 GoogleTest PASS**（31 毫秒）及 **5/5 ASan/UBSan/leak PASS**（59 毫秒），含已经实际运行 30 毫秒的指数 walk 查询中途取消、原有限循环覆盖与完整吸收概率、缺失封闭 SCC、空根终局、未知截断与超大 offset。
- `final-normal-differential.log`：**4/4 pytest PASS**（10.21 秒）。原两幅固定图与 **64** 随机图的双方、显式预算及全部分页逐字段比较原完整 HTTP DTO；另有 **54** 组全部 9 能力 × 6 道具/招式输入逆序/Unicode 展示名配置身份、**2^70** 历史组合计数、全部关键事件、500 位 offset、UTF8/DEL 精确 cursor、分类/未分类封闭环及 **16** 个原错误文案案例。
- fresh Core/codec 原生输入复制到 `/build/p1-winning-frozen-source` 后独立 sanitizer 编译，`san-differential.log` 同四项完整原差分 **4/4 PASS**（82.70 秒），没有减少原 100000 walk 默认预算。初版 runner 链接遗漏 event reader 的 ReadGraphRequest 依赖曾失败；添加唯一既有 graph_contract.cpp 后完整真实 codec 通过，没有另写读取器。
- 独立 `tests/vectors/winning-paths.v1.json` 三项完整 golden 来自原 ListWinningPathGroupsUseCase 与原 winning_path_groups_response，只有声明的任意精度整数字段做无损文本编码。`golden-normal.log` / `golden-san.log` 分别 **1/1 pytest PASS**（0.69 / 0.74 秒），严格比较完整 wire，包括概率分子分母、decimal/percent、分页 cursor、全部空值、组/前缀/循环身份与计数，不通过 HTTP 整数解析掩盖 wire 差异。

八个成熟源/codec/测试/golden 的清单为该根 `frozen-sources.sha256`。P3 已按唯一 DTO 准备 HTTP adapter；公共 Registry/版本/CMake/Makefile 由主 agent 统一登记。此处证明纯 Core 与正式 codec 可运行且原行为完整等价，尚未将真实 PG/HTTP、Go/Swift 或 Apple CI 验收写成完成。

真实基线完整 JSON 为约 565MB，不能为满足 JSON 通道预算而裁掉图或约 190 万条事件。按主 agent 指定的 frozen-request 按需重算方案，新增真实 `BattleGraph` producer 只读重载，与既有 owned-record 来源在编译期选择 span，同一个算法不复制任何节点状态或事件摘要。`ReadWinningPathQueryValue` 和 `WinningPathGroupsJson` 最窄提升为私有共用 codec，让 P2 的 fixed_graph_query 重建一次原 typed 图后直接查询并输出小 DTO；不通过完整图 JSON 往返，不增加 Core 文件 IO，不让 Go 计算 cursor/分组/概率。

借用入口实际验证 `borrowed-final-native.log` / `borrowed-final-san-native.log` 为 **6/6 正常 PASS**（33 毫秒）与 **6/6 ASan/UBSan/leak PASS**（65 毫秒）。新增项真正运行 InferFixedBattle，再直接借用正式图查询，与同一图的小型 record 入口核对身份/概率/历史/离散值并确认原事件地址不变。`borrowed-differential.log` 完整原差分及严格 wire **5/5 pytest PASS**（10.29 秒）；固定输入 `borrowed-san-differential.log` 同五项 **5/5 PASS**（95.46 秒）。最后将两种原边 ID 都显式提升到同一 Integer 再验证，避免对原 size_t 做负数比较；两个最终原生日志覆盖此同义身份验证改动。八源 SHA 已更新，公共包装与 **841 节点/16095 边真实基线 HTTP** 仍由 P2/P3/主 agent 接入验证，此处没有将小图 native 结果冒称真实基线验收。

## 根行动归因与原任务摘要图语义（2026-11-25，待统一公共注册）

完整性审计发现两个实际任务兼容缺口：旧任务执行端使用 SummaryStateGraphBuilder，而既有 Core 固定入口始终采用完整探索图；Go worker 的 explanation_json 还存入引擎元数据，未保存原根行动业务归因。最小原图实证表明，边预算耗尽时摘要构图必须将当前节点和全部待处理前沿标为 unknown 并停止；完整探索构图仍继续处理其他前沿。两种行为不能互相替代。审计证据为 p1-completeness-audit-20261124/summary-vs-full.json。

新增 BuildSummaryBattleGraph / InferSummaryFixedBattle 与原完整入口共用 BFS、StateKey、SCC 和精确求解器，但按原任务模式清空深层事件与 predecessor，仅独立保存根完整替代历史用于解释。默认完整入口行为保持原状。fixed_battle 显式 graph_mode=configuration_summary 选择原任务摘要语义；include_root_action_explanation=true 才添加 root_action_explanation 对象或 null。调用端需同时选择任务图模式并保存真实业务解释，不能用元数据对象替代。

ExplainRootActionPairs 迁移原实际 MOVE_USED 联合行动桶、根事件覆盖、边绝对概率与历史条件概率、后继精确吸收价值、稳定 Top-K 和全部桶覆盖。归因固定使用攻击方/防守方价值轴，不随 observer 交换；没有以 MOVE_SELECTED 代替被阻断前实际使用的行动。SolveGraphNodes 提取既有唯一求解过程的全部节点价值，不另写矩阵或逐节点重复求解。完整输出保留原 explanation.v1 的概率、条件胜率、贡献、代表节点、path_count、遗漏桶数和实际图规模。

首次原 oracle 因缺少 BattleSide 导入真实 NameError，正常 MOVE_USED 路径被旧 worker 的 catch 转为 None；该独立原基线缺陷 BASE-EXPLANATION-001 只补一行 import，与 Core 迁移分开登记。所有归因差分明确以这唯一修复后的原算法为准，未将旧原文件错误运行冒称通过。最初真实 RED 保留在 root-action-explanation-20261124/differential.log，修复后首轮证据为 corrected-differential.log。

冻结证据根 root-action-explanation-20261124/：combined-ctest.log 为完整 126/126 CTest PASS（48.06 秒），含全部既有公开 ABI、256 次 ownership、并发、运行中取消和 C 头检查；combined-differential.log 为新增归因/摘要及原回合/完整图 8/8 pytest PASS（6.66 秒），包含 12 个合成归因、32 个真实固定图/同次解释与 40 个原摘要图预算/循环/空展开边界。solver-and-original-regression.log 为原图求解、模板、EV 与原 application/solver、stream_configuration 用例 35/35 pytest PASS（35.73 秒）。固定构建输入 san-ctest.log 为完整 126/126 ASan/UBSan/leak CTest PASS（1900.10 秒），其中原 TopologyBudget 检查完整执行 1389.24 秒，没有缩短原保护预算；同一 sanitizer runner 的 san-differential.log 为新增归因/摘要完整原差分 3/3 pytest PASS（11.88 秒）。18 个成熟源/codec/runner/测试清单见 frozen-sources.sha256；新 factory/context 和状态门禁不包含在本批。

本批未自行修改公共 Registry、版本或共享 golden。主 agent 统一登记新 graph_explanation.cpp、graph_explanation_contract.cpp、两组原生测试与专属 runner，并由 worker 明确消费两个 opt-in 字段；此处不是 P1 全部完成声明，独立状态门禁及透明配置 provider 的实际入口迁移仍在推进。

## 原透明配置 provider 与仓库对账上下文（2026-11-25，待后继公共注册）

原 Dragonite 旅程先使用 FactoryReconciledBattleInferenceRepository，再调用 TransparentPokemonChampionEffectFactory 的普通配置 provider；它与 strict admission 的合同不同。透明 Pressure/Pickpocket 的 overall SUPPORTED 可在参考配置中纳入，但 missing real_ability_behavior 仍使严格任务 PARTIAL/拒绝。InnerFocus 工厂整体 PARTIAL 则在普通 provider 中也排除；不能因真实回合支持某子机制就在 Go 放行。新增单侧 factory、repository_mode 两个尾部字段，默认 standard/raw。两侧可各用其原 generator，组合、过滤、成员数、等价归并和权重全部继续在 Core 执行。

ReconcileConfigurationRepository 提取现有严格准入的唯一原装饰器提升与理由逻辑，供 strict 和普通 provider 共用；没有让 provider 直接复用 strict Selectable。招式先核基础可执行事实，纯伤害 NO_EFFECT 允许按原条件提升，变化威力缺基础字段仍保留 unsupported。原始候选集合、原展示名和首代表均保留。新 context 的空维度错误按原 generator 使用 profile.name（不是 attacker/defender），已发布 standard/raw 的既有错误文本不擅改。

configuration-context-20261125/differential.log 为新原 composition 与旧默认空间 4/4 pytest PASS（1.36 秒）：48 组完整双方混合工厂/仓库模式、raw 三态、命令过滤和双权重，另有 9 组原空特性维度/Pressure/Pickpocket 边界及 72 组旧默认空间。原预期真正运行 source repository 装饰器、原 _configuration_profile 与正式 generator/usecase，不在 Python 测试或 Go 实现 reconciliation。native-final.log 为 90/90 GoogleTest PASS（51 毫秒）；首轮两项原生夹具错误是漏指定默认两道具却断言一类，原 native.log 保留，修正为明确无道具输入后全通过。九源清单为同根 frozen-sources.sha256。

该 context 后续已由下节固定 snapshot 的 95 项纯域 sanitizer 和 14 项完整差分覆盖；尚未报告真实 Dragonite HTTP 完成。P2 持有正式配置 codec 的两项可选 side 字段，后继公共注册与真实旅程消费由主 agent/P2 统一完成；本批不改旧默认输出、共享 golden 或默认回合。

## 原五种独立状态门禁与 StatusRules（2026-11-25，待统一纯库登记）

status_gates.hpp/.cpp 迁移原 SleepGate、FreezeGate、ParalysisGate、InfatuationGate、ConfusionGate 及默认/显式有序 ActionGatePipeline。睡眠按 turns_asleep 索引策略表并在末尾复用最后概率，未醒增加计数；解冻招式 flag 在允许 override 时直接解冻且不消费 RNG。麻痹和着迷阻断，混乱返回 replace_with_self_hit。管线保留前序全部事件和新状态，在首个非 allow 决定处短路；全部允许时清空单门禁 reason，保留醒来/解冻事件。混乱剩余计数、畏缩和其他不相关状态均按原函数保持，不补充原本没有的自伤伤害或残余伤害流程。

完整 StatusGateRules 保留原睡眠、冰冻、麻痹速度/不能动、灼伤物理/残余、中毒/剧毒、混乱和着迷策略及其原验证。九个实际代际 profile 复用已有精确麻痹速度事实，其余字段逐项对照原 profile；零伤害/速度倍率和概率端点不被擅自拒绝。StatusChance 保留原 BattleRandom.chance 的随机端口，按原顺序请求精确概率；不发明跨语言随机种子算法，也不把测试 bool 队列注册为公共 ABI。原默认回合未调用这些独立门禁，因此本迁移同样不注入默认回合，既有覆盖声明保持该入口的真实语义。

state_contract.hpp/.cpp 最窄提升唯一 ReadStatusValue / StatusJson 内部帮助函数，既有状态字段、规范顺序、验证与 wire 不变。诊断 runner 直接复用同一 codec，不用另一个状态解析器，亦不为编码状态额外计算速度或伤害。

证据根 status-gates-20261125/：native.log 为新五项门禁与 context 三项加全部旧纯域 95/95 GoogleTest PASS（57 毫秒）；differential-final.log 为 14/14 pytest PASS（2.89 秒）。包含 1520 个原完整单门禁、默认/反序管线、九代际和自定义精确策略案例，以及 20 个原策略/空管线错误、原八项门禁测试、新透明 composition 和旧默认配置空间回归；每例比较完整 decision、状态、reason、events、全部 chance 请求概率、确切消费数量及剩余队列，不只比较能否行动。初次新测试编译的 nodiscard 警告和首轮 Python Enum 到 Literal 投影错误均保留在 build.log / differential.log，修正仅在测试边界，不改算法来匹配测试。

158 个真实构建输入冻结至 /build/p1-status-frozen-source，同根 frozen-build-inputs.sha256 可复核。san-core-ctest.log 为完整 95/95 ASan/UBSan/leak CTest PASS（5.56 秒），san-final-differential.log 为同一 sanitizer runner 的 14/14 pytest PASS（5.39 秒），两者均使用 UBSAN halt_on_error=1。首个 wrapper 根目录没有 CTest 注册的 san-ctest.log 保留为 No tests were found 历史，不计成功；最终明确从实际 core 子目录运行并要求 --no-tests=error。此固定 sanitizer 同时覆盖前述 context 九源，未重复归因批已通过的原长公开预算检查。

七个门禁/唯一 reader/runner/测试文件清单为 frozen-sources.sha256；context 九源清单与之前冻结值一致。主 agent 统一登记纯源、原生测试和 runner，生产接口仍为独立 typed Core API，不新增 C 回调或随机 ABI，不将本局部证据单独表述为完整 P1 或整个迁移交付完成。
