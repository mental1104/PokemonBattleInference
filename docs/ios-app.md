# iPhone / iPad 原生应用

双真机完整人工操作与逐项PASS/FAIL标准见[验收手册](iphone-ipad-acceptance.md)。该手册明确区分已验证预期、待准备的设备测试服务和HUMAN_PENDING记录。

## 2026-11-25 当前串行检查点

`serial-resume-20261125/swift-live-abi11/`已使用主工作树的正式Core **0.11.0 / calculation-rules.v11**、独占空PG/完整CSV、Go API/独立daemon以及真实Swift客户端，**27/27 PASS、零SKIP（7.971秒）**。42共享样本、离线/在线相同输入、任务提交/精确结果/运行取消、来源HTTP读取及同步均实跑。来源HTTP的独占PG race测试通过（1.096秒），实际版本与独立Core探针一致，不从业务解释或本地SDK猜测。

Swift使用同源码独立构建的GCC13兼容库`/build/root-summary-swift11`，Go使用冻结GCC14库`/build/root-summary-abi11`；新Swift链接缓存按archive SHA隔离。App工程版本已更新0.11.0（2），Apple App/UI及双SDK待本批Ready PR CI实际验证。下文.10及旧Apple结果均为历史证据，不代替本版平台通过。

用户要求继续串行迭代并暂停后续手机操作；本批没有物理设备安装、更新、启动、签名授权或证书修改。既有iPhone 0.8.0（2）保持原状，双真机人工验收仍HUMAN_PENDING。

`ios/App` 是 SwiftUI 应用，`ios/project.yml` 是 XcodeGen 工程源。图鉴读取随 Swift Package 交付的真实 SQLite，首次运行校验并安装到 Application Support。用户配置、计算档案与知识库分别保存；更换知识包不会覆盖用户库。

应用已有四个入口：图鉴、计算、配置、设置。图鉴支持中文/英文/编号搜索及宝可梦、招式详情。计算页可修改双方等级、IV、EV、性格、已实现的特性/道具、麻痹状态、世代、天气、场地和要害；实际调用 Core 得到能力、速度、离散伤害、一击/两击精确分数。配置支持保存、另存、打开与删除。设置显示实际引擎和知识版本；服务器地址为空时所有查询和离线计算均可使用，填写后可调用真实在线计算接口。

目前直接伤害规则的特性/道具选择明确限制为已实现列表；知识图鉴收录的名称不表示所有机制均支持。特殊威力、变化招式等由引擎明确拒绝。离线/在线结果显示实际来源和引擎、规则、知识版本；在线失败不会回退成离线成功，取消或网络错误明确显示。

配置页的“同步配置”展示真实待提交项，提供手动同步/取消及冲突比较。先在设置中保存服务器和服务端分配的同步账户；两台设备使用同一账户和服务器。连接设置以 SQLite 事务保存，已绑定空间禁止改成其他用户/服务器，失败不会清空资料。同步失败可重试；冲突不自动覆盖，比较页面展示双方参数、删除状态和版本，明确选择此设备或服务器版本后恢复。底层真实双 SQLite + Go HTTP + PostgreSQL 收敛已验证，新增 App 同步界面仍待本轮模拟器/真机验证。

## 最简在线任务

配置页的“在线推演任务”使用原 `POST /v1/inference/configuration-jobs` 合同，提供提交、查询既有任务、真实状态/资源计数轮询、服务器取消和分页结果。双方使用同一等级、原推演允许的七种能力模板（或服务配置快照）、PokeAPI特性/道具标识和候选招式ID；默认是巨钳螳螂/技术高手/满物攻增强/十字剪与快龙/多重鳞片/满生命物防增强/龙爪，双方50级且无道具。`no_investment` 等静态calculator专有模板不能当作原任务已支持。表单独立于离线直接伤害编辑器，不会把用户IV/EV偷偷替换成模板，也不发送Core operations冒充原任务。

HTTP202只表示接收，完成/失败/截断/取消全部来自服务，计数和图资源不随时间伪造。结果保留任意精度分子/分母、期望回合和错误语义，失败或截断不显示成零胜率。网络失败保留任务ID和本次提交键，原参数直接重试复用同一幂等键；修改命令或开始另一个任务会使用新键。离开页面只停止查询，后台任务继续，用户可复制任务ID后查询。任务页尚不提供持久化的本地任务历史。

任务结果详情另行读取 `GET /v1/inference/configuration-jobs/{job_id}/results/{configuration_pair_id}/metadata`。响应为 `{"schema_version":1,"metadata":...}`；`metadata` 记录真实子进程 `engine_version`/`rules_version`、最终请求字节的 `input_sha256`、输入 schema、operation 和 observer。完整 canonical 配置ID作为单个转义路径段发送；不会从当前表单重建身份。该接口独立于原 results/explanation，不增加或改写原业务解释字段。

case存在但没有来源时明确返回 `metadata:null`；有输入摘要但未取得合法子进程版本信封时，两版本均为null。详情显示“未知（未记录）”，不借用本地SDK、提交准入资料或旧explanation里的版本。读取期间、网络/协议失败分别显示“读取中”“读取失败”，失败可重试。不存在的case返回404 `battle_inference_case_not_found`，辅助记录损坏返回503；二者都不能伪装成旧资料未知。详情沿用任务提交/查询时绑定的服务器，后续更改设置不会把旧任务发往另一服务。

2026-11-25 来源读取链使用登记的 `metadata-abi10-verification` 工作树（`e4d8d1a` 基线加本批改动）及已验证的 `.10` GCC14/GCC13静态库，真实Swift→Go→PG/daemon/Core最终 **27/27 PASS、零SKIP**（12.865秒），包括真实取消后未执行case的metadata空值和缺case 404。实际任务来源为 `0.10.0` / `calculation-rules.v10`，与同服务独立Core响应一致；原文及SHA在 `Backup/PokemonBattleInference/p4-execution-metadata-final-20261125/`，首轮27项证据另存 `p4-execution-metadata-20261124/`。独占PG HTTP测试另以race模式通过旧成功记录null、未知实际版本、中文/斜线/问号/百分号完整身份、404、损坏503和原explanation不变，httpapi vet通过。该测试中的存储版本标签只验证来源映射，不冒充原生执行。新增详情UI的异步版本等待仍保留严格服务版本断言，需后续Apple CI实际验收；本批没有设备安装、更新、启动或证书操作。

`tools/migration/accept-swift-jobs.sh` 在声明的维护环境中启动独占Go API/真实PG/正式daemon/Core，纯Go导入固定CSV后由另一Swift容器调用正式接口。2026-11-24 `.7`/none修复双工具链以原七模板合法输入验收 **25/25 PASS、零SKIP**（6.330秒），包含原任务202→幂等同ID→completed→完整精确结果、真实75case任务running→cancelled、在线/离线全字段一致及双SQLite同步。最终证据在 `Backup/PokemonBattleInference/p4-jobs-75-legacy7-20261124/`，先前合法单case取消证据在 `p4-jobs-legacy-presets7-20261124/`。更早的 `p4-jobs-final-none7-20261124/`、`p4-jobs-p3-none7-20261124/` 执行与原始响应仍保留，但其中no_investment任务超出原worker七模板范围，不能作为原任务兼容通过证据。这些Linux结果不能替代实际UIKit操作，新App页面仍待下一轮Apple CI。

## 网络知识更新

设置 → 更新离线知识中，先保存用户提供的完整 `manifest.json` 地址，再点击“下载并更新知识”。保存来源不会自动下载。地址限 HTTP(S)，不允许凭据、查询参数、片段及重定向；数据库固定读取清单同目录的 `knowledge.sqlite`。清单最多1 MiB，数据库最多64 MiB。来源保存在独立 SQLite 设置键，重启后恢复，不改变配置同步空间。

客户端把收到的真实字节流式写入 SHA 命名的持久暂存文件。网络断线或主动取消保留前缀；下次先重新读取清单，版本未变时发送 `Range` 从已落盘长度续传。服务器忽略 Range 返回200时清空旧前缀从头下载，不能把两份正文拼接。进度来自真实已写字节；读取清单、校验、安装阶段显示不定进度。没有自动后台更新或定时器伪造进度。

完整下载后校验字节数、SHA-256，再调用既有 `KnowledgeStore.install` 校验数据库 schema/元数据/表行数并原子切换 `current.json`。失败不切换旧指针，旧版本文件保留，独立用户数据库及同步队列不参与替换。取消发生在原子提交之前时保留旧版本；已提交成功则返回实际新版本。

`KnowledgeUpdateTests` 使用真实回环 HTTP 故障服务和 SQLite，覆盖截断后206续传、正文到达后取消、重试时服务器返回完整200、损坏校验、404、清单超限和重定向拒绝，核对失败旧知识/用户配置/队列保留，以及成功后重启、旧文件保留。`PBI_KNOWLEDGE_HTTP_REPORT_DIRECTORY` 指定独立证据目录，保存每次请求的 Range/status、候选清单、实际当前指针和测试用户库。Swift 验证镜像安装 Python 仅用于启动这一真实 HTTP 夹具。

## 自动验收

GitHub 的 `Native Core - macOS and iOS` 仅在 Ready PR 上运行。Apple SDK 静态库构建后，`tools/migration/validate-apple-app.sh` 在build自有目录初始化仅监听回环的独立PostgreSQL，纯Go导入固定CSV，启动正式Go API、Core child与持久daemon（完整revision `battle-inference.summary-exploration.v2`）。先让Swift正式在线/同步/任务测试连接同一真实服务，再生成工程、构建未签名iOS App、分别执行iPhone/iPad XCUITest。只清理本脚本的PID、PG目录对应实例和自启模拟器；不接触现有数据库或生产地址。

动态endpoint、测试同步账户和实际Core探测版本作为独立UITest资源，不进入App产品。UI测试必须通过实际设置控件写入SQLite，再验证在线/离线 `99–117`/`123/128` 及版本一致；iPhone上传的配置由iPad真实拉取，之后各自保存同步并重启。原任务UI提交默认单配置对后核对 `0/1/0` 和期望回合 `5/1`，并通过服务已实际准入的75case候选池操作服务器取消，不依靠注入延迟制造取消窗口。缺少真实服务资源会失败，不会静默SKIP或使用假传输；新UI结果以实际Apple CI为准。

验收覆盖首装中文查询真实条目、默认伤害 `99–117`、两击 KO `123/128`、麻痹后的速度 `42`、编辑保存后杀进程重启恢复、同步待提交项/连接设置重启保留，以及 iPad 横屏。测试使用独立的 `PokemonBattleInference-UITesting` 子目录；只有显式测试参数可以清理该目录，不触碰正常用户数据。xcresult 内保留各步骤截图并尝试导出独立附件，最终模拟器截图、设备选择、完整构建和测试日志在 CI artifact 的 `build/reports/app/` 中。任一机型失败仍独立运行另一机型，最终退出状态保留失败。没有通过实际运行前不将脚本存在当作验收通过。

入口测试按可见按钮标签定位，同时覆盖 iPhone 底部栏和 iPad 顶部浮动导航；iPad 图鉴列表折叠时，测试点击实际侧栏按钮再搜索。麻痹测试明确点击内层原生开关，核对真实状态 `0→1` 后才重算并严格要求速度 `42`。截图同时附带完整无障碍层级；运行脚本记录构建/启动/测试/导出阶段时间和内存信息，并在每个机型完成后关闭仅由本脚本启动的模拟器，避免同时驻留。旧的长时间安装/runner 启动间隔仍需下一轮实际日志确认改善，不能归因于导出附件或将排队/环境耗时当作业务测试通过。

`a959962` 的 [Apple CI 45422337224](https://github.com/mental1104/PokemonBattleInference/actions/runs/45422337224) 已完成：iPad 9/9，iPhone 8/9。唯一失败的iPhone在线比较附件显示仍为本机离线结果；同一时刻AX中的在线按钮范围y=50.7…94.7，其中心落在y=56.3…100.3的NavigationBar下，`isHittable` 未排除遮挡。UITest的滚动辅助现要求完整控件处于实际NavBar/TabBar之间，按超出方向继续真实滚动；没有改变timeout、来源或99–117/123/128断言，也没有添加网络重试。下次CI额外保留点击在线前的截图/层级；修复仍待Apple实跑。原失败PNG/AX及日志在 `Backup/PokemonBattleInference/apple-a959962-20261125/p4-evidence/`。

## 5dc4dad 的实际 Apple 结果

[Native/App 45399177231](https://github.com/mental1104/PokemonBattleInference/actions/runs/45399177231) 的macOS Core、Go/Swift、两SDK与未签名device App构建全部通过；Mac独占Go/PG/daemon真实服务也完成Swift在线/同步/任务测试。iPhone、iPad分别 **8/9 UI通过**：两端都完成原在线任务提交、精确结果、真实运行中取消、跨模拟器同步/重启，查询/保存/设置也通过。

本轮仍为FAIL：iPhone在线/离线比较在读取two-hit-probability时找不到元素，iPad离线计算在读取attacker-speed时找不到元素；各自对应的另一机型相同数值断言通过。失败点是Form结果行的无障碍查询，不是数值不一致。UITest现对每个独立懒加载结果行先实际滚动显示，严格99–117、123/128、85/42断言不变；Swift语法检查通过，修复效果仍须后续Apple实跑。完整原日志/产物在 `Backup/PokemonBattleInference/apple-abi8-ui-20261124/`。上一版全绿的aa498cb仍是较早的阶段验收基线。

## Mac 与设备安装

Mac 需要已安装 Xcode、iOS Simulator Runtime、XcodeGen、CMake、Boost、nlohmann-json；真实UI验收另需Go、Python、jq和完整PostgreSQL工具。CI优先探测已有PG工具，缺少时安装postgresql@16。构建入口先生成 `build/core` 原生Mac库与 `build/apple/iphoneos` / `build/apple/iphonesimulator` 静态库，再由XcodeGen生成工程。App把 `build/apple/$(PLATFORM_NAME)` 作为库搜索路径，同时完整编译本地Swift Package和资源。

CI 不签名、不生成发布证书、不安装到物理设备。真机安装还需要用户 Mac 上的 Apple 身份/Team、设备物理连接与信任以及 Developer Mode；这些交互不能由 Linux CI 代替。完成这些必要身份和物理步骤后，可选择本工程的 App scheme 与实际设备进行构建安装。Bundle ID 是 `com.mental1104.PokemonBattleInference`，需要时可在 Mac 的本地签名配置中调整。

## .9 Apple 复验与输入修复

`2885c41`对应[Native/App 45413559200](https://github.com/mental1104/PokemonBattleInference/actions/runs/45413559200)的macOS Core、Go/Swift、两SDK和未签名App构建通过；iPhone **9/9**（481.450秒）、iPad **8/9**（471.265秒）。iPad取消用例在提交任务之前失败，招式控件实际值仅为`404,17,806,`，严格预期仍为`404,17,806,814,851`；没有证据说明该次已执行服务端取消。iPhone同项通过，其余任务精确结果、同步和计算两机均通过。

测试现按原顺序逐个输入完整招式ID，每一项都等待真实控件值严格匹配后再继续；末尾仍核对两侧完整候选池，提交相同75case任务并要求真实cancelled终态。不改产品输入、不注入值、不缩小工作量。Mac Xcode27.2 Swift语法解析通过，修复效果须下一轮Apple CI；原失败日志保存在`Backup/PokemonBattleInference/apple-abi9-20261124/github-native-45413559200.log`。

## 2026-11-24 iPhone 15 Pro 实际安装

用户Mac实测为M1/macOS26.7.3、Xcode27.2，已配对的iPhone15Pro运行iOS27.3 Beta，Developer Mode已开启。固定验收源码为已获Main/Apple全绿、双模拟器各9/9的`c0b048e1c49de9483692c77788498267049ac135`，本次只增加App Icon及安装版本元数据；没有把尚在迁移的完整图接口混入手机验收版。

复用同一CI产物中的arm64设备Core静态库，传输前后SHA一致；Mac本地完整编译Swift/App并使用已有开发身份签名。SSH会话最初在CodeSign返回`errSecInternalComponent`，改在已登录用户的GUI launchd会话执行一次性构建后真实成功；未修改Keychain ACL、读取密码或创建额外证书。一次性job在完成后卸载。

首次安装后iOS拒绝启动，用户亲自完成开发者信任；随后`devicectl`启动成功，独立进程清单确认App仍在运行。最终图标版为 **0.8.0（2）**，签名校验、实际安装、启动及独立进程核验全部通过；同一1024不透明图标已生成iPhone/iPad资源。XcodeGen的版本属性也已改为读取正式构建设置，避免默认常量把实际安装版本留在1.0/1。

Mac源码在`/Users/espeonblue/code/apps/PokemonBattleInference-c0b048e/`，日志在`~/Library/Logs/PokemonBattleInference/iphone15pro-c0b048e/`；签名App及完整本次证据保存于NAS私有`Backup/PokemonBattleInference/iphone15pro-c0b048e-20261124/`。用户另授权清理缓存后，只移除闲置Remmich DerivedData和Homebrew下载缓存；保留源码、签名资料及当前设备符号，回收约3.3GB。

本次只证明上述真机构建、安装及启动；iPhone完整功能体验、iPad物理安装、双真机同步和最终人工验收仍为HUMAN_PENDING。手机可先验断网图鉴与默认计算，预期伤害`99–117`、两击KO`123/128`；在线任务和跨设备同步需要实际验收服务端及另一设备，不能把App成功启动当作这些项目已经通过。
