# common 清理后版本兼容回归

2026-11-25用户明确要求更新旧子模块引用并做兼容回归。迁移分支把`submodules/common`从`39e85858e7b1cefe0a5916b01b6bbf5a59f6d0a1`更新到远端main的`9624d2a860ff39eb39b4a972a624c36fde986097`，规范远端地址仍为`git@github.com:mental1104/common.git`。HEAD与origin/main完整SHA相同，子模块内部没有未提交改动，没有修改common上游代码或重写远端历史。

原571项Python业务及数据库用例没有修改；更新后直接加载`/source/submodules/common/python/mental1104/db/__init__.py`。原DAO、连接注册及事务公开入口仍能使用，不需要兼容补丁。Core、Go和Swift计算规则没有因这次依赖升级而变化。

## 实际结果

证据根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/common-9624-compat-20261125/`。

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| GNU14工具链Core | 149/149 PASS | `python-regression.log`中的CTest结果。 |
| 原Python及真实临时PG业务 | 571 PASS、零SKIP、零失败 | 完整`python-regression.xml`按非migration类核对；数据库为本次自有实例。 |
| 迁移差分/Go绑定等 | 111 PASS、248环境SKIP、零失败 | 同一JUnit共930项，682通过；未提供的独立服务环境仍明确跳过，不计为通过。 |
| Vue | 31文件95/95 PASS | `web-regression.log`；生产类型检查/构建也通过，`web-build.log`。 |
| GNU13/Swift工具链Core | 149/149 PASS | `swift-regression.log`，没有将GNU14 archive链接进Swift容器。 |
| Swift离线/本地 | 21 PASS、6在线环境SKIP | 27项套件零失败；跳过为在线计算2项、真实任务2项、真实同步2项。 |
| Swift→Go→PG/独立daemon | 27/27 PASS、零SKIP | `swift-live/swift-live.log`，15.662秒；补齐上一行全部6项环境需求。 |
| 结果来源HTTP/PG | PASS | 同一真实联调中的metadata接口race/vet通过，当前源码API/Worker/Core真实构建、全部固定CSV初始化及独立HTTP客户端通过。 |

统一入口`validate-nas.sh all`的外层执行会话返回143，但测试容器完整生成JUnit；没有将外层中断写成统一脚本成功。保存该轮原始日志后，独立完成其余Web/Swift命令；实际联调再用`accept-swift-jobs.sh`，显式连接本轮GNU14 `/build/core`及GNU13 `/build/swift-core`，补齐全部在线用例。没有重跑或覆盖已通过的Python结果。

Python测试后已归档并停止其精确临时PG ID；Swift真实联调也通过脚本退出清理。没有连接生产库、切换生产服务或执行手机安装。

## 历史与空间说明

原P0基线与benchmark仍以当时的39e85858及环境为准，不把历史结果改写成新依赖的测量。旧引用仍可通过原提交和留存工作树追溯。

新main完整历史已导出`common-main-9624.bundle`并通过`git bundle verify`，约1.9MiB。该数字只表示新main完整历史包，不表示本机旧对象已经释放；旧pack仍有六处硬链接共享，且保留回退依据。没有使用全局prune、批量删除引用或force push来处理空间。
