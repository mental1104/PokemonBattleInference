# iPhone / iPad 原生应用

`ios/App` 是 SwiftUI 应用，`ios/project.yml` 是 XcodeGen 工程源。图鉴读取随 Swift Package 交付的真实 SQLite，首次运行校验并安装到 Application Support。用户配置、计算档案与知识库分别保存；更换知识包不会覆盖用户库。

应用已有四个入口：图鉴、计算、配置、设置。图鉴支持中文/英文/编号搜索及宝可梦、招式详情。计算页可修改双方等级、IV、EV、性格、已实现的特性/道具、麻痹状态、世代、天气、场地和要害；实际调用 Core 得到能力、速度、离散伤害、一击/两击精确分数。配置支持保存、另存、打开与删除。设置显示实际引擎和知识版本；服务器地址为空时所有查询和离线计算均可使用，填写后可调用真实在线计算接口。

目前直接伤害规则的特性/道具选择明确限制为已实现列表；知识图鉴收录的名称不表示所有机制均支持。特殊威力、变化招式等由引擎明确拒绝。复杂在线任务和跨设备同步需对应真实服务 API 完成后接入。

## 自动验收

GitHub 的 `Native Core - macOS and iOS` 仅在 Ready PR 上运行。Apple SDK 静态库构建后，`tools/migration/validate-apple-app.sh` 生成工程，先构建未签名的 iOS App，再从 runner 的实际可用设备中选择 iPhone/iPad，分别执行 XCUITest。

验收覆盖首装中文查询真实条目、默认伤害 `99–117`、两击 KO `123/128`、麻痹后的速度 `42`、编辑保存后杀进程重启恢复，以及 iPad 横屏。测试使用独立的 `PokemonBattleInference-UITesting` 子目录；只有显式测试参数可以清理该目录，不触碰正常用户数据。xcresult 内保留各步骤截图，最终模拟器截图、设备选择、完整构建和测试日志在 CI artifact 的 `build/reports/app/` 中。没有通过实际运行前不将脚本存在当作验收通过。

## Mac 与设备安装

Mac 需要已安装 Xcode、iOS Simulator Runtime、XcodeGen、CMake、Boost、nlohmann-json。构建入口先生成 `build/apple/iphoneos` 和 `build/apple/iphonesimulator` 中的静态库，再由 XcodeGen 生成 `ios/PokemonBattleInference.xcodeproj`。工程把 `build/apple/$(PLATFORM_NAME)` 作为库搜索路径，同时完整编译本地 Swift Package 和资源。

CI 不签名、不生成发布证书、不安装到物理设备。真机安装还需要用户 Mac 上的 Apple 身份/Team、设备物理连接与信任以及 Developer Mode；这些交互不能由 Linux CI 代替。完成这些必要身份和物理步骤后，可选择本工程的 App scheme 与实际设备进行构建安装。Bundle ID 是 `com.mental1104.PokemonBattleInference`，需要时可在 Mac 的本地签名配置中调整。
