# P4 原生应用阶段验收

当前状态：IN_PROGRESS，工程估算90%。以下逐项区分已完成的b797c19验证和本轮新增断言，不能用用例数量替代行为标准。双真机最终验收保持HUMAN_PENDING，用户暂停后续安装的要求不变。

## 固定证据

[Apple run45535685587](https://github.com/mental1104/PokemonBattleInference/actions/runs/45535685587)已完整成功。head为b797c19530ccec9729660d7184da5ffab1849789，实际PR测试合并树797cefdee91df10e4cdacfaf376c918f73e31896。macOS149/149 CTest，112差分/委托PASS、247外部环境SKIP；双SDK库和未签名device App实际构建成功。独立真实Swift→Go/PG/daemon27/27零SKIP，耗时6.923秒。

iPhone9/9零失败625.391秒，iPad9/9零失败478.275秒，两个xcodebuild退出码均0。任务从02:49:37运行到03:33:52 UTC，原先45分钟取消的问题在75分钟总预算下完整复验成功，没有减少用例、修改数据或放宽单项断言。

官方artifact14989082234共63,013,028字节；ZIP SHA-256为`e4e512527610884def4e39856fbc5ab1de0f44d9dec784fa8d9729a55be8641e`，本机下载完整匹配。原日志、两个xcresult、导出截图/无障碍树、时间线、SDK库和构建日志均保存在`Backup/PokemonBattleInference/apple-b797c19-20261125/`。临时下载配置已删除，无Apple登录/证书/安装操作。

## 原标准核对

补充[Apple run45543244271](https://github.com/mental1104/PokemonBattleInference/actions/runs/45543244271)，head为6bd30c9、实际测试树f01d137：两端各执行10项，均仅首装招式威力断言失败（9通过/1失败，xcodebuild退出65）。保存/杀进程/重启后的实际离线重算在iPhone48.744秒、iPad55.016秒通过，99–117与123/128保持严格核对，因此补齐重启重算证据。

官方artifact14992530124共282,032,375字节，下载SHA `36457b30eba022dfaf38eacd31575f08fdbb5dd795c643730f6bb4cd51f0a32f`与官方一致，保存在`Backup/PokemonBattleInference/apple-6bd30c9-20261125/`。两端原始无障碍树分别为iPhone附件D91D91F6、iPad附件135B2676，真实字段均为`label: '威力, 40'`，并不存在独立`40`节点。本轮按SwiftUI实际合并语义精确核对完整字段，保留40的严格预期、不修改应用或数据；修正后需重新运行双模拟器，尚未计PASS。

| 标准 | 状态 | 依据及限制 |
| --- | --- | --- |
| SwiftUI原生及iPhone/iPad布局 | PASS | 真实双模拟器9/9，`testSaveRestartAndEditConfiguration`含iPad横屏尺寸检查；真机手感仍需Human。 |
| 图鉴及招式查询 | IN_PROGRESS | 首装宝可梦中文查询UI已通过；`KnowledgeStoreTests.testBundledLookupAndRestart`验证完整SQLite和418子弹拳字段。新增`testFirstInstallChineseMoveSearch`补首装招式详情UI，待新CI。 |
| 六项能力、速度、伤害、精确KO离线计算 | PASS | `testOfflineCalculationUsesRealKnowledgeAndCore`核对攻击182、HP202、16档99–117、KO123/128、速度85/80及麻痹42；双UI核对伤害/KO/麻痹输入实际绑定。 |
| 不在Swift重复C++规则 | PASS | `CalculationService`从知识快照构造正式C ABI请求，调用`Engine.calculateAsync`，无Swift计算引擎；42共享样本和实际在线离线一致另有桥接验证。 |
| 配置编辑、保存、重启恢复 | PASS | 双UI保存后杀进程/重新启动，完整名称与编辑表单恢复；真实独立SQLite测试核对全部配置、稳定ID、编辑、删除和队列事务。 |
| 首装离线可用且重启后仍能计算 | PASS | 随包1,350/937资料、重启SQLite和离线Core已通过；6bd30c9两端保存/重启后实际计算99–117和123/128通过，未用名称恢复代替重算。 |
| 在线计算、任务提交/进度/结果/取消 | PASS | 两端真实Go/PG/独立Worker UI用例及27项真实Swift测试；实际来源/引擎/规则/知识版本有严格断言，运行中取消及最终结果有正式任务ID。 |
| 服务地址与引擎/数据版本 | PASS | 地址/账户保存和进程重启通过，在线计算UI严格核对三个实际版本，不把失败在线请求标成离线成功。 |
| 重计算不阻塞主线程 | PASS | `AppModel`仅管理MainActor交互；知识/SQLite由actor处理，首次加载及`Engine.calculateAsync`使用Task.detached。真实并发/取消测试及双模拟器计算通过，真机流畅度由Human F验收。 |
| 真机安装及固定验收手册 | PASS | `iphone-ipad-acceptance.md`含A–F、固定212/700/418输入、明确预期及PASS/FAIL依据；实际双设备安装/体验未代填。 |
| Human双真机体验及最终授权 | HUMAN_PENDING | 安装暂停；保持既有iPhone版本，尚未安装iPad或执行最终体验验收。 |

本轮只新增上述第10项查询用例和重启重算断言，不修改应用、Core或知识包。新用例必须实际通过两个模拟器后才能补齐这两项P4自动化缺口。用户数据同步、冲突及知识更新的完整独立标准仍见P5记录，不用本表的UI通过数量替代它们。
