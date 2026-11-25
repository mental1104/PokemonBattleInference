# Go 四角色隔离验收

## 2026-11-25 图祖先回退、聚合视图与改选分支

`web-branch-revisit-20261125-r3/`完整入口退出0。仍以干净d3fbb97应用源码为准，新工具镜像重建的三种运行镜像为`p6-d3fbb97-r2`；实际image ID和工具源码SHA分别归档，不能只凭可变标签追认旧运行。首次构建在下载固定pgx/v5 v5.7.5时遇到proxy.golang.org EOF，失败原文保留在不带r后缀的报告；相同源码重试构建成功，无依赖版本替换。

在原221节点576边真实任务图中，浏览器选择第一条边到node1，HTTP与节点卡精确概率均为1/256。点击ROOT祖先后旧列被截断，只剩node0，卡片恢复1/1；再次展开得到的完整outcomes与原响应相同。通过实际按钮切到聚合视图，结果簇出现且原始边隐藏；再切回原始视图选择第二条边，HTTP cursor只含一项、edge_id与该边相同，节点为node2，HTTP与卡片均为1/128。截图包含同步变化的逐回合战报，没有复用旧分支概率或注入客户端状态。

配置CRUD/刷新、速度与攻防组合求解、候选保存和不可达编辑、任务完成/图重算、运行取消、许可、42项Core完整响应、健康故障恢复、回退已验证5529a82镜像及独立PG恢复同轮通过，无JavaScript异常。r2在加入有界代理就绪等待前也整轮通过，r3是最终脚本复验；没有把未执行的修改计入旧结果。完整图片模式仍待源目录展开完成，普通模式截图中的缺图不计图片验收成功。

## 2026-11-25 接管开发后的当前源码回归

`runtime-full-20261125/base-regression/`固定d3fbb97干净工作树与三种`p6-d3fbb97`镜像，普通模式完整入口再次PASS：42项Core HTTP全响应、Vue配置CRUD/刷新、速度及攻防组合求解/候选保存、不可达编辑、221节点576边实际任务与图前进、运行取消、许可逐字节核对、健康故障恢复、回退已验证5529a82镜像及独立PG恢复均通过。镜像ID、原始请求/响应、截图/trace、工具源码SHA和精确清理日志已保存。本轮没有完整图片输入，不能据此宣告图片模式通过。

新运行配置实际预检另见`go-runtime.md`。完整素材模式新增PG持久化重启、全部BYTEA SHA及独立恢复库校验；原普通模式仍可独立运行，不要求外部图库。

## 2026-11-25 攻防与速度组合目标

`stack-abi11-20261125/web-mixed-goals-first/`整个入口PASS，仍固定5529a82应用，并归档本轮实际浏览器工具及SHA。页面在212无投入配置下加入242无投入攻击/防御目标：子弹拳418最低档三次，拍击1最高档一次，同时保留速度目标。真实求解返回1个候选：攻击114×3=342，对方HP330；防御最高4，己方HP145；速度85对75，三目标均满足。页面实际显示相应证据并截图。

随后从页面删除速度目标，再次求解，完整攻防证据与组合目标一致，请求不含speed_goals字段。再从可见编辑入口把击倒次数改成1，真实响应reachable=false/candidates空，攻击证据114×1且satisfied=false，页面“当前不可达”和失败证据行实际出现。没有改断言让不可达输入返回成功。

配置CRUD、速度preset/spread与候选保存、任务完成、真实图沿边前进、运行取消、许可、健康故障恢复、旧镜像回退和独立PG恢复同轮再次通过，JavaScript错误为空。完整图片、其余图查询及生产升级仍不据此标为完成。

## 2026-11-25 求解页面与候选保存

`stack-abi11-20261125/web-solver-first/`新增实际求解场景后整个入口再次PASS，仍固定5529a82应用、42共享Core响应及原221节点/576边任务；配置CRUD、图分支前进、运行取消、故障恢复、回退和独立数据库恢复全部保留并通过。实际工具原文与SHA、请求、响应、截图和trace均归档。

在Vue选择212无投入配置，添加242无投入速度目标，通过实际按钮求解：preset API返回1个候选，速度85对75、margin10且satisfied；页面证据行显示相同值。随后切换反推模式，实际search-spreads返回10个候选，每个候选的速度证据均满足严格大于目标。页面点击第一候选“添加到专属配置”，创建201、绑定212且role为both，EV/IV逐字段等于该真实候选，按钮进入“已添加到专属配置”。没有mock求解响应或直接提交HTTP替代界面操作。本场景只覆盖速度目标；攻击/防御目标的页面编辑、组合目标等仍待补充，已有HTTP差分不能替代这些交互。

## 2026-11-25 配置管理、图分支与图片负向验收

`stack-abi11-20261125/web-config-graph/`整个入口PASS，应用仍固定5529a82，实际浏览器工具原文及SHA分别归档为`accept-web-go.mjs`和`validation-sources.sha256`。此前的计算、任务完成/取消、运行许可、健康故障恢复、不同旧镜像回退及独立库恢复均再次通过；没有JavaScript异常。

- 原Vue页面创建212的专属配置，HP EV252、Attack EV100，再在同一表单改名、性格adamant、Attack EV252。创建201、更新200；身份不变而快照变化。真实刷新页面后重新选择212，管理页仍显示修改内容，独立公开列表逐字段等于更新响应。最后页面确认删除204，列表和侧栏均消失。原始请求、响应、刷新后的截图均保留。
- 完成任务的Full图ROOT加载后，实际点击行动组，请求outcomes HTTP200；切换原始边并选择第一条，advance HTTP200、cursor恰好增加一步、目标node ID与所选正式边一致，STEP1真实渲染后截图。没有直接注入cursor或伪造前端状态。
- `web-config-first/`保留第一轮失败：原label包含select选项，精确getByLabel未匹配“适用 Pokémon”；只修正验收选择器定位同一可见label下的select。没有改产品行为或跳过配置操作。独立Playwright上下文显式限定动作30秒、导航45秒，失败仍归档截图/trace。

图片验证还未完成全量导入。`missing-steel-diagnostics/`仅用固定上游的五图样本作为**预期失败**实验：实际导入5/5，212与242两张图片均解码为96×96，独立HTTP正文为PNG且SHA-256与ETag一致；钢属性图缺失时严格失败，报告点名`button[aria-label="steel 属性"] img`。这证明占位图不能冒充成功，不能将该实验写为完整图库通过。无论后续操作是否失败，已成功图片的尺寸、图源、摘要均写入`images.json`，失败还保存DOM图源和解码状态。

显式传入`PBI_STACK_SPRITES_ROOT`时，脚本叠加`compose.go-stack-sprites.yaml`并启用图片断言；`PBI_STACK_POSTGRES_DATA_ROOT`必须是不存在的新目录。完整BYTEA库及WAL使用这个独占SSD目录，素材保持只读HDD挂载；默认无图验收仍使用原tmpfs。退出先停止自有容器再清理专属网络，完整图库数据库目录保留供复核，不自动删除或复用。Compose2.20保留基础tmpfs但PGDATA指向独占盘，不依赖新版本的`!reset`语法。

## 2026-11-25 Web任务完成、图与运行取消

`stack-abi11-20261125/web-task-red/`首次新增浏览器任务断言后实际失败：Web提交得到202，但公开查询45秒始终pending。原验收Worker固定`go-stack-validation.v1`，与实际业务任务revision不匹配；此前只证明Worker存活，不证明消费。

验收Compose改用原公开`battle-inference.summary-exploration.v2`，没有改服务准入、任务过滤或超时。`web-task-first/`实际完成任务及结果页；截图仍停在ROOT加载中，因此进一步要求真实explore HTTP200及ROOT节点渲染，不能仅凭图创建200和标题出现判定完成。

最终`web-task-cancel/`整个栈入口PASS，应用镜像源固定5529a82，验证工具源码SHA在`validation-sources.sha256`：

- 原Vue载入双快龙龙爪示例，实际生成组合/选择双方技能组/提交固定任务，真实daemon产生succeeded，221节点/576边。详情显示完整概率和`battle-inference.explanation.v1`归因；原请求、逐次状态及结果全部归档。
- 从实际结果页打开树状图，真实按需Full重算HTTP200、随后真实root explore HTTP200，ROOT节点和行动分组实际渲染后截图。完整原始两份响应均保留。
- 另在两侧候选控件各选择337、17、21、56四招，重新枚举及提交。公开查询先观察到running/solving_probabilities，才点击页面对应任务的取消按钮；实际取消HTTP200，终态cancelled且页面显示已取消。没有注入延迟或直接写入取消结果。
- 之前的计算114–135/390px适配、运行许可cmp、健康故障恢复、不同旧镜像回退和独立数据库恢复均再次通过；专属实例、网络已清理。没有JavaScript异常。

实际Worker命令保存为`worker-command.json`，值为`["-revision","battle-inference.summary-exploration.v2"]`。图片仍有明确缺口，尚未覆盖所有solver/配置编辑等浏览器交互及正式生产接管；本批不将整个P6标PASS。

## 2026-11-25 Core 0.11 当前版本复验

登记的`stack-abi11-verification`干净工作树先固定4885932，再固定许可补充提交5529a82，两轮入口均完整PASS。最终证据在`Backup/PokemonBattleInference/stack-abi11-20261125/licenses/`，`base/`保留首次当前版本结果。使用独立临时PG、已核对空闲的10.245.24.48/28及随机回环端口，没有修改生产网络或数据库。

正式镜像实际包含当前Core 0.11；独立HTTP完整比较42操作共享请求/响应。Chromium通过原Vue选择212/242和子弹拳418，真实Nginx→Go→独立Core返回114–135并显示在页面；390px视口的实际文档宽度为390px，没有JavaScript异常。桌面/手机PNG及trace完整归档。

健康检查实际经历healthy→暂停API后unhealthy→恢复healthy。当前镜像与已验证74c75e1旧镜像ID不同，用户配置在真实镜像回退和独立恢复库中完整JSON一致。最终API镜像为88e5d12abd91e001945f60d1d85b3ef3db6d412bfa52c62e776c4d74bdfc51cf，53,909,368字节；独立备份SHA为0306fa24e3f7a7e41caeff7e99ade171a56f86c326560b30613ce32066746bb5。结束后精确清理专属实例与网络。

5529a82补齐runtime层的项目LICENSE及仓库完整THIRD_PARTY_LICENSES.md，API和db-init共享该runtime层。脚本从真正运行的当前API容器复制两文件并与源码逐字节cmp通过；原PokeAPI许可继续保留。该修复后完整栈演练再次通过。

本轮Worker存活检查通过，仍未通过该浏览器场景投递业务任务；其验收revision仍为go-stack-validation.v1。复杂任务提交/结果/取消、带完整图片的页面及正式旧生产库接管仍是后续范围。独立PG/daemon任务测试的既有成功不代替这轮Web操作验证。

`tools/migration/validate-go-stack.sh` 用独立 Compose 项目实际运行原 Vue/Nginx、Go API、独立 PG Worker 和 PostgreSQL，另有一次性纯 Go db-init 与 Chromium 客户端。应用运行镜像不携带 Python；Python、npm 和浏览器仅在验收端使用。所有容器通过已声明的 maintenance `run --rm` 启动，默认数据库只在本次 tmpfs；显式图片模式使用上述独占SSD目录。宿主只发布随机回环端口，不使用生产连接或生产数据库目录。

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
