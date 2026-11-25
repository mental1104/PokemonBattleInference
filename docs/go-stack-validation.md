# Go 四角色隔离验收

## 2026-11-25 Core 0.11 当前版本复验

登记的`stack-abi11-verification`干净工作树先固定4885932，再固定许可补充提交5529a82，两轮入口均完整PASS。最终证据在`Backup/PokemonBattleInference/stack-abi11-20261125/licenses/`，`base/`保留首次当前版本结果。使用独立临时PG、已核对空闲的10.245.24.48/28及随机回环端口，没有修改生产网络或数据库。

正式镜像实际包含当前Core 0.11；独立HTTP完整比较42操作共享请求/响应。Chromium通过原Vue选择212/242和子弹拳418，真实Nginx→Go→独立Core返回114–135并显示在页面；390px视口的实际文档宽度为390px，没有JavaScript异常。桌面/手机PNG及trace完整归档。

健康检查实际经历healthy→暂停API后unhealthy→恢复healthy。当前镜像与已验证74c75e1旧镜像ID不同，用户配置在真实镜像回退和独立恢复库中完整JSON一致。最终API镜像为88e5d12abd91e001945f60d1d85b3ef3db6d412bfa52c62e776c4d74bdfc51cf，53,909,368字节；独立备份SHA为0306fa24e3f7a7e41caeff7e99ade171a56f86c326560b30613ce32066746bb5。结束后精确清理专属实例与网络。

5529a82补齐runtime层的项目LICENSE及仓库完整THIRD_PARTY_LICENSES.md，API和db-init共享该runtime层。脚本从真正运行的当前API容器复制两文件并与源码逐字节cmp通过；原PokeAPI许可继续保留。该修复后完整栈演练再次通过。

本轮Worker存活检查通过，仍未通过该浏览器场景投递业务任务；其验收revision仍为go-stack-validation.v1。复杂任务提交/结果/取消、带完整图片的页面及正式旧生产库接管仍是后续范围。独立PG/daemon任务测试的既有成功不代替这轮Web操作验证。

`tools/migration/validate-go-stack.sh` 用独立 Compose 项目实际运行原 Vue/Nginx、Go API、独立 PG Worker 和 PostgreSQL，另有一次性纯 Go db-init 与 Chromium 客户端。应用运行镜像不携带 Python；Python、npm 和浏览器仅在验收端使用。所有容器通过已声明的 maintenance `run --rm` 启动，数据库只在本次 tmpfs，宿主只发布随机回环端口；不使用生产连接或宿主数据库目录。

源码必须来自干净的已提交 checkout。并行开发时用 Git 注册的 detached worktree 固定具体 SHA，避免半成品进入构建。`PBI_STACK_SOURCE_ROOT` 指向该 checkout，脚本自身及浏览器 harness 可以来自当前验证工作树；报告分别记录应用源码 SHA 和真实镜像 ID。

## 实际验收范围

2026-11-24，应用源码固定 **74c75e122d21172a3f3f5681ec32fbbb87b6ba7d**，完整入口终态 **PASS**：

- 真实三阶段构建产生独立 API、数据和原 Vue/Nginx 镜像。API image `bfef9240a74d…` 为 **46,864,170 bytes**，数据 image `00f686064966…` 为 **82,687,664 bytes**，前端 image `5a3cef7394f1…` 为 **48,551,604 bytes**。
- 空 PG 由 Go 导入全部固定 CSV/八个原 MV 并建立运行表；API 的完整 13-op 0.6 Core 请求/响应与冻结向量一致。
- Chromium 通过实际 Vue 搜索并选择巨钳螳螂 **212**、幸福蛋 **242** 和子弹拳 **418**，经 Nginx→Go→独立 Core 返回 **114–135**。页面实际显示该结果，16 档齐全，无 JavaScript 异常；桌面/390px 手机截图和浏览器 trace 保留，手机文档宽度与 viewport 均 **390px**。
- 实际 Docker 健康检查先 healthy，暂停 API PID1 后连续三次探针失败得到 unhealthy，恢复 PID1 后重新 healthy。没有用静态配置或容器 running 代替探针执行证据。
- 通过公开 HTTP 创建用户配置并保存完整读取结果；从新 API 回退到先前验证的独立 image `b64cc41af490…` 后，完整用户 JSON 不变。两个 image ID 不同，脚本拒绝用同一 image 冒充回退。
- 对自有 PG 实际 `pg_dump -Fc`，恢复到独立 `recovered` 数据库，以新 API 读取后完整用户 JSON 仍与回退前一致。备份 SHA-256 为 **737a7a7c94aa712541727b4d9b1ae94b4958e333976ad54066b8b1695585d878**。
- Worker daemon 在四角色网络中实际启动并保持运行；本场景没有通过尚未完成的 HTTP 任务创建链投递工作。Worker 实际计算/取消/恢复另由 `native-worker.md` 的七项 PG/child/daemon 测试证明。

证据根为 `/volume1/homes/mental1104/Backup/PokemonBattleInference/stack-20261124/explicit-network/`，包含原始 HTTP、浏览器 PNG/trace、健康历史、初始化回执、镜像元数据、备份/恢复和各实例日志。结束后自有四角色实例和专属网络均已清理，镜像与私有证据保留。

## 复跑条件

已有通过验证的旧 API 镜像通过 `PBI_STACK_PREVIOUS_IMAGE` 明确传入；构建输出可分别由 `PBI_STACK_SERVER_IMAGE`、`PBI_STACK_DATA_IMAGE`、`PBI_STACK_FRONTEND_IMAGE` 设置。源码、SSD 构建和 HDD 报告沿用 `PBI_STACK_SOURCE_ROOT`、`POKEOP_BUILD_ROOT`、`POKEOP_REPORT_ROOT`。

`PBI_STACK_SUBNET` 必须先与宿主路由和已有 Docker IPAM 核对。首次真实运行发现 NAS 默认 IPv4 地址池已用尽，未清理未知网络或修改 Docker 全局配置；改用已核对空闲的本次专属 `/28` 后完整通过。脚本退出只删除自己项目的网络；若该网段后来被占用，应重新选择，而不是回收其他应用。

原始失败日志分别保存在 `stack-first-run.log`（新 clone 的 NAS 文件权限噪声）和 `stack-build-first-run.log`（默认地址池耗尽）。前者检查确认只有 `100644→100755` 模式变化且内容完全一致后，仅对该新 submodule 设置 `core.filemode=false`，没有 reset 或改写来源内容。

## 尚未覆盖

本次只证明上述已实现切片及两个 Go 暂存版本的兼容回退，不代表正式生产升级、原 Python 生产库接管、完整复杂任务提交、全部 Web 功能或 P6 整体 PASS。浏览器实际截图仍有缺失的 Pokémon/属性图片：目前空库 Go 初始化尚未导入原 BYTEA sprite 资产，这是明确剩余项，不能以计算可用代替完整图片验收。

正式上线还需当前完整版本重新验收、非破坏数据库升级/备份确认、完整任务及 Web 回归，以及 Human 的生产地址和切换批准。旧实现继续保留。
