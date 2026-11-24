# 原生 Core 桥接模块（应用尚未实现）

`PokemonCore` 是 Swift Package，直接导入 `contracts/c/pbi_core.h` 并调用 C++ 静态库。`Engine.calculate` 同步返回复制后的 JSON，`Engine.calculateAsync` 在 detached task 计算并把 Task 取消传到原生令牌；Swift 不实现计算规则。

Linux Swift 6.0.3 已完成实际构建和 4 项 XCTest：完整共享结果/版本、错误/取消、32 并发和实际大批次 Task 取消。Linux 通过不能替代 Apple SDK、SwiftUI、模拟器或真机验收。

本地在同环境构建 Core 后，用 `make test-native` 或 `bash tools/migration/test-swift.sh "$PWD/build/core"`。脚本把所有可执行临时文件及缓存放在构建目录旁，并按静态库校验值隔离 scratch，保证链接当前 Core。

用户已授权使用 GitHub macOS CI 自动验证 Apple 目标。`build-apple-core.sh` 在 Mac 的现有 Xcode 环境中构建 arm64 iPhoneOS/Simulator Core、Swift module 和 C ABI XCFramework；不需要 Apple 登录、Team 或签名。实际状态以 CI 记录为准。

当前尚无 SwiftUI App、SQLite 图鉴/用户数据、配置编辑、在线任务及数据同步，因此 P4/P5 不能标记 PASS。晚上接通用户 Mac 后可继续本地构建和后续应用安装；Apple 登录/Team、设备信任、Developer Mode 和真机安装授权仍由 Human 完成。可通过工具执行的构建和诊断由 Agent 完成，不要求 Human 代跑终端命令。
