# iPhone / iPad 原生应用

`ios/App` 是 SwiftUI 应用，`ios/project.yml` 是 XcodeGen 工程源。图鉴读取随 Swift Package 交付的真实 SQLite，首次运行校验并安装到 Application Support。用户配置、计算档案与知识库分别保存；更换知识包不会覆盖用户库。

应用已有四个入口：图鉴、计算、配置、设置。图鉴支持中文/英文/编号搜索及宝可梦、招式详情。计算页可修改双方等级、IV、EV、性格、已实现的特性/道具、麻痹状态、世代、天气、场地和要害；实际调用 Core 得到能力、速度、离散伤害、一击/两击精确分数。配置支持保存、另存、打开与删除。设置显示实际引擎和知识版本；服务器地址为空时所有查询和离线计算均可使用，填写后可调用真实在线计算接口。

目前直接伤害规则的特性/道具选择明确限制为已实现列表；知识图鉴收录的名称不表示所有机制均支持。特殊威力、变化招式等由引擎明确拒绝。复杂在线任务仍待完整 Core 与任务 API 接入。

配置页的“同步配置”展示真实待提交项，提供手动同步/取消及冲突比较。先在设置中保存服务器和服务端分配的同步账户；两台设备使用同一账户和服务器。连接设置以 SQLite 事务保存，已绑定空间禁止改成其他用户/服务器，失败不会清空资料。同步失败可重试；冲突不自动覆盖，比较页面展示双方参数、删除状态和版本，明确选择此设备或服务器版本后恢复。底层真实双 SQLite + Go HTTP + PostgreSQL 收敛已验证，新增 App 同步界面仍待本轮模拟器/真机验证。

## 网络知识更新

设置 → 更新离线知识中，先保存用户提供的完整 `manifest.json` 地址，再点击“下载并更新知识”。保存来源不会自动下载。地址限 HTTP(S)，不允许凭据、查询参数、片段及重定向；数据库固定读取清单同目录的 `knowledge.sqlite`。清单最多1 MiB，数据库最多64 MiB。来源保存在独立 SQLite 设置键，重启后恢复，不改变配置同步空间。

客户端把收到的真实字节流式写入 SHA 命名的持久暂存文件。网络断线或主动取消保留前缀；下次先重新读取清单，版本未变时发送 `Range` 从已落盘长度续传。服务器忽略 Range 返回200时清空旧前缀从头下载，不能把两份正文拼接。进度来自真实已写字节；读取清单、校验、安装阶段显示不定进度。没有自动后台更新或定时器伪造进度。

完整下载后校验字节数、SHA-256，再调用既有 `KnowledgeStore.install` 校验数据库 schema/元数据/表行数并原子切换 `current.json`。失败不切换旧指针，旧版本文件保留，独立用户数据库及同步队列不参与替换。取消发生在原子提交之前时保留旧版本；已提交成功则返回实际新版本。

`KnowledgeUpdateTests` 使用真实回环 HTTP 故障服务和 SQLite，覆盖截断后206续传、正文到达后取消、重试时服务器返回完整200、损坏校验、404、清单超限和重定向拒绝，核对失败旧知识/用户配置/队列保留，以及成功后重启、旧文件保留。`PBI_KNOWLEDGE_HTTP_REPORT_DIRECTORY` 指定独立证据目录，保存每次请求的 Range/status、候选清单、实际当前指针和测试用户库。Swift 验证镜像安装 Python 仅用于启动这一真实 HTTP 夹具。

## 自动验收

GitHub 的 `Native Core - macOS and iOS` 仅在 Ready PR 上运行。Apple SDK 静态库构建后，`tools/migration/validate-apple-app.sh` 生成工程，先构建未签名的 iOS App，再从 runner 的实际可用设备中选择 iPhone/iPad，分别执行 XCUITest。

验收覆盖首装中文查询真实条目、默认伤害 `99–117`、两击 KO `123/128`、麻痹后的速度 `42`、编辑保存后杀进程重启恢复、同步待提交项/连接设置重启保留，以及 iPad 横屏。测试使用独立的 `PokemonBattleInference-UITesting` 子目录；只有显式测试参数可以清理该目录，不触碰正常用户数据。xcresult 内保留各步骤截图并尝试导出独立附件，最终模拟器截图、设备选择、完整构建和测试日志在 CI artifact 的 `build/reports/app/` 中。任一机型失败仍独立运行另一机型，最终退出状态保留失败。没有通过实际运行前不将脚本存在当作验收通过。

入口测试按可见按钮标签定位，同时覆盖 iPhone 底部栏和 iPad 顶部浮动导航；iPad 图鉴列表折叠时，测试点击实际侧栏按钮再搜索。麻痹测试明确点击内层原生开关，核对真实状态 `0→1` 后才重算并严格要求速度 `42`。截图同时附带完整无障碍层级；运行脚本记录构建/启动/测试/导出阶段时间和内存信息，并在每个机型完成后关闭仅由本脚本启动的模拟器，避免同时驻留。旧的长时间安装/runner 启动间隔仍需下一轮实际日志确认改善，不能归因于导出附件或将排队/环境耗时当作业务测试通过。

## Mac 与设备安装

Mac 需要已安装 Xcode、iOS Simulator Runtime、XcodeGen、CMake、Boost、nlohmann-json。构建入口先生成 `build/apple/iphoneos` 和 `build/apple/iphonesimulator` 中的静态库，再由 XcodeGen 生成 `ios/PokemonBattleInference.xcodeproj`。工程把 `build/apple/$(PLATFORM_NAME)` 作为库搜索路径，同时完整编译本地 Swift Package 和资源。

CI 不签名、不生成发布证书、不安装到物理设备。真机安装还需要用户 Mac 上的 Apple 身份/Team、设备物理连接与信任以及 Developer Mode；这些交互不能由 Linux CI 代替。完成这些必要身份和物理步骤后，可选择本工程的 App scheme 与实际设备进行构建安装。Bundle ID 是 `com.mental1104.PokemonBattleInference`，需要时可在 Mac 的本地签名配置中调整。
