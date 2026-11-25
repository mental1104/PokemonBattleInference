# P1 / P2 阶段验收（Core 0.11）

结论：**P1、P2 按迁移原参考实现的范围为PASS**。源码基线为6d12312，后续a4bc9f4保留相同Core与ABI；本地后续提交只增加部署验收及文档。此结论独立于P4模拟器剩余用例、双真机验收和生产审批，不表示整个Goal完成，也不表示实现了原来未支持的官方规则。

## P1逐项证据

| 要求 | 拥有源与验收依据 | 结果 |
| --- | --- | --- |
| 能力、速度、伤害与规则 | calculations/profile/damage/status及原oracle差分；精确有理数、世代及静态/实时效果边界保留 | PASS |
| 状态、效果与正式回合 | state/actions/turn/status_gates、原状态键/PP/阶段/条件事件；独立门禁不擅自接入原默认链 | PASS |
| 概率转移、图、SCC与求解 | transitions/battle_graph/graph、Full与原Summary独立构图、预算未知与截断、精确求解 | PASS |
| 配置空间及搜索 | configuration_stats/moves/space/admission、job_move_pool、goals/aggregate/spread_search，含44100具体case与精确权重 | PASS |
| 事件分析与业务归因 | event_analysis及batch、graph_explanation、投影/获胜路径/快照；原完整DTO与错误边界差分 | PASS |
| 无平台服务依赖 | core/CMakeLists.txt的pbi_core只链接Boost headers；知识为拥有快照，无DB、HTTP、SwiftUI或平台服务 | PASS |
| Linux/macOS独立构建与纯测试 | Linux149/149 CTest及111差分/委托；macOS149/149 CTest及112差分/委托，均实际构建；外部环境SKIP分别207/247单列 | PASS |
| 可解释差异 | migration-baseline.md记录BASE-EXPLANATION-001等独立基线修复；unsupported_aspects保留原缺口，完整诊断兼容由Go边界映射 | PASS |
| 实际benchmark | configuration-graph-20261125.md及原始证据包：两模式×三后端×workers1/2的12组精确结果/权重/展开数一致，原预算和分母未变 | PASS |

行为证据和命令由migration-core.md、contracts/c各合同及各专项报告逐项展开；测试总数不是这些范围的替代证据。旧文档中的“尚未接入”是历史切片状态，正式0.11注册、组合验证和真实消费者结果以最新检查点为准。

## P2逐项证据

| 要求 | 实际证据 | 结果 |
| --- | --- | --- |
| 单一版本化C ABI | contracts/c/pbi_core.h；schema1、0.11.0/calculation-rules.v11；42共享原实现样本 | PASS |
| 所有权、异常、错误及批次原子性 | 最新149项中OwnershipAndRepeatedRelease、正式错误/资源/批次检查；C++异常不跨ABI，release重复安全 | PASS |
| 并发、进度及取消 | 最新ABI并发、ActualProgressBorrowingAndCancellation、RunningGraphCancellation、RunningConfigurationCancellation、CancellationBeforeAndDuringBatch；Go race及Swift Task取消 | PASS |
| Go/Swift调用同一Core | Linux分别以同源码GCC14/GCC13 archive构建，真实Swift→Go→PG/daemon 27/27零SKIP；macOS真实HTTP链亦27/27零SKIP | PASS |
| Linux/macOS目标 | 上述Linux与GitHub macos-15实际构建/执行，Darwin实际工具链为AppleClang17、Swift6.1.2、Xcode16.4 | PASS |
| iOS设备/模拟器静态库 | artifact/apple/iphoneos及iphonesimulator均有libpbi_core.a、libpbi_abi.a；实际SDK构建和未签名device App构建成功 | PASS |

## 可独立复查的证据

Linux：`summary-snapshot-abi11-20261125/native-first.log`、`serial-resume-20261125/swift-live-abi11/`、`go-all-abi11/`。早期与当前领域sanitizer分别在各专项原始目录保留；没有将149项全部声称为最新全套sanitizer。

macOS/iOS：GitHub run45528710141，head a4bc9f4，实际PR合并测试树6ad12f56；原始job日志、报告及双SDK产物保存到`Backup/PokemonBattleInference/apple-a4bc9f4-20261125/`。官方artifact14986970123的SHA-256为`c8cec59dc2293f5cbd9594867dc86e34fbad12ff07a2add3784dde23e5a5356a`，下载后完整校验相同。

该run的P1/P2阶段均成功；随后iPhone9/9通过，iPad7项通过时job在约45分钟被取消。原job设置45分钟，取消时间与该限额吻合，日志没有已完成用例断言失败。P4整套仍未完成；只将job上限改为75分钟，保留原用例、数据及每项断言，下一次CI仍需完整运行。
