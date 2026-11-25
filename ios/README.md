# iPhone/iPad 原生应用与 Core 桥接

`App/`是SwiftUI应用，提供离线图鉴/招式、计算、完整配置编辑保存、在线推演、同步及设置。`PokemonAppSupport`负责真实知识SQLite、独立用户SQLite、版本化更新、变更队列和HTTP客户端；`PokemonCore`直接导入唯一`contracts/c/pbi_core.h`，调用同一C++静态库。Swift不复制计算规则。能力、伤害、速度及精确KO均来自Core，在线与离线结果保留实际来源和三个版本。

首装包含固定来源的1,350个宝可梦、937个招式、25个性格和324个属性关系。知识包校验后原子切换，用户库独立保留配置、队列、冲突和计算快照。首次知识校验、SQLite打开和Core重计算离开MainActor；任务取消传递到实际原生令牌或URLSession。

最新完整[Apple CI 45535685587](https://github.com/mental1104/PokemonBattleInference/actions/runs/45535685587)对应b797c19及PR测试合并树797cefd：macOS149/149原生测试、112差分/委托通过（247外部环境SKIP单列），iPhoneOS/Simulator静态库和未签名device App构建通过，真实Swift→Go/PG/daemon27/27零SKIP。iPhone与iPad模拟器分别9/9通过，包含真实在线计算来源/版本、任务完成/取消、两模拟器同步、保存/重启及iPad横屏。官方产物已下载核验SHA并私有保存。

阶段逐项依据及未完成项见[原生应用验收](../docs/migration-ios-acceptance.md)。6bd30c9的Apple45543244271两端均9/10：保存/重启后实际离线重算通过，新增招式查询的独立`40`节点断言失败。两端原始附件均显示合并字段`威力, 40`；测试改为精确核对完整字段，等待新CI，不把未复验的修正计为通过。P4保持IN_PROGRESS。

本地在同环境构建Core后，使用`make test-native`或`bash tools/migration/test-swift.sh "$PWD/build/core"`。桥接脚本按两个archive的SHA隔离Swift scratch，避免链接过期Core。Apple库构建由`tools/migration/build-apple-core.sh`负责；实际App和双模拟器验证由`tools/migration/validate-apple-app.sh`负责，不需要Apple Account或真机签名。

真机安装与A–F固定输入/预期值见[双设备人工验收手册](../docs/iphone-ipad-acceptance.md)。当前用户要求继续迭代、暂停安装，既有iPhone0.8.0(2)不更新、不启动；双真机体验、iPad物理安装、生产地址和最终审批保持HUMAN_PENDING。构建与诊断由Agent执行，Human只负责必要授权和真实使用体验。
