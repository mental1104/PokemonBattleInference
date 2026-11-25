# 架构迁移进度

本文件是长程迁移的恢复入口。目标保持P0–P6全部范围；任何Linux验证均不能替代macOS、Xcode或双设备人工验收。顶部状态表与最新检查点反映当前范围，下方早期记录保留当时结果与限制，不作为新提交已通过的证据。

## 当前状态（2026-11-25）

用户要求后续串行迭代，每轮以表格和百分比报告实际进展。当前整体工程估算约 **96%**；下表百分比包含剩余平台/交付验收工作量，不是测试通过率，也不等于剩余时间的线性比例。手机后续安装、更新和启动继续暂停。

2026-11-24 用户调整本轮交付优先级：**P1–P3、P5 按原标准完成；P4、P6 达到基本可用**。P4 基本范围为 iPhone/iPad 可构建、查询/离线计算/保存/同步与最简在线任务操作；P6 为四角色启动、数据初始化、核心 Web、基本备份恢复和回滚。真机签名/安装/人工体验保持 HUMAN_PENDING，完整原目标未凭阶段切片宣告完成。

| 阶段 | 状态 | 工程估算 | 当前证据与剩余工作 |
| --- | --- | --- | --- |
| P0 基线 | PASS | 100% | `migration-baseline.md`、41 项 HTTP/185 表快照、原测试结果及真实有界 benchmark 已记录；Web 既有一项失败单独登记。 |
| P1 C++ Core | PASS | 100% | .11 Linux149/149及111差分/委托、macOS149/149及112差分/委托通过；外部SKIP单列。12组同语义benchmark精确对照通过，原规则缺口及基线修复明确。完整产物已保存，逐项依据见migration-core-bindings-acceptance.md。 |
| P2 跨语言集成 | PASS | 100% | 版本化C ABI及42共享样本；Linux和macOS真实Go/Swift服务各27/27零SKIP，所有权/错误/并发/取消实测，设备/模拟器静态库及未签名device App实际构建成功。产物SHA与官方记录一致，阶段审查已记录。 |
| P3 Go 服务端 | PASS | 100% | 原41/41 API、任务/恢复/取消、race/vet及原库非破坏性接管通过。新HDD模式Go/PG 76通过/2专用SKIP、恢复10/10；全部1,374份正文独立SHA核验、真实Vue任务/取消/图片、四角色和PG重启、元数据备份/恢复均通过。正式NAS上线并逐个验证1,374个HTTPS图片URL，正文长度/SHA全部匹配；28.7GB全来源正文不在当前部署范围。 |
| P4 iOS/iPadOS | IN_PROGRESS | 95% | 原9eac125两端各10/10已完整通过；新增全图鉴图标的17a5fda逐文件SPM校验通过，Apple45572741348已通过Core、跨语言和双SDK，11项App双模拟器用例仍在运行。旧版PASS不代替新图标UI结果；双真机HUMAN_PENDING、安装暂停。 |
| P5 数据同步 | PASS | 90% | 自动化标准已逐项核对：.9真实Swift→Go/PG整包25/25零SKIP，后续真实双SQLite补齐keepRemote后同步4/4零SKIP；幂等、两种冲突恢复、删除、重启收敛、中断更新保护及在线离线一致均有实测。c0双模拟器各9/9含跨设备同步通过；此PASS限自动化标准，双真机人工体验仍HUMAN_PENDING。 |
| P6 部署与回归 | IN_PROGRESS | 95% | 完整HDD栈及NAS三角色升级通过，全部图片HTTPS校验与原库备份恢复一致。2036989已归位legacy，集成后原Python/PG577、布局/知识6、迁移差分126通过；247外部SKIP单列。覆盖率入口461项/84%，实际Python兼容镜像构建及镜像内3项通过。新App CI、知识更新人工下载源和最终审批仍待。 |

## 已确认的边界与决策

- 用户已明确要求服务端部署到NAS，并以`pokemon.mental1104.xyz`提供最终反向代理入口。本次新Go服务的NAS部署及该域名接入已授权；沿用现有DSM证书/DNS/入口管理，先核实实际配置与App访问方式，不改动其他服务。此授权不等于恢复手机安装、自动合并PR或切换无关生产业务。

- Apple45548203813正式成功：9eac125/实际测试树77e00c1，iPhone10/10（601.470秒）、iPad10/10（649.435秒），退出码均0；macOS149/149、112PASS/247外部SKIP，双SDK/未签名device App及真实Swift→Go/PG27/27零SKIP（6.325秒）。artifact14994448373为67,513,856字节，下载SHA3270d84a8e6ef891985e747f1c65cb18ac8253331f1d97cfb22cbaf2ad2eb112与官方一致；完整报告和产物私有保存，下载配置已删除。P4逐项自动化PASS，工程估算90%→95%，整体约93%→94%；Human双真机验收仍未执行。到a3f0ff7的Core/contracts/ios/Apple入口与该已验版本无差异。

- 登记的部署验证工作树已从d3fbb97推进到干净a3f0ff7，common同步9624d2a并保留本地旧引用回退，pokeapi仍1567d530。三种独立候选镜像p6-a3f0ff7构建成功，实际镜像中的Core子进程0.11完整比较42共享响应通过，实例/专属网络已回收。镜像ID及源码/子模块版本清单保存在runtime-full-20261125/candidate-a3f0ff7/。完整图库运行尚未开始。

- legacy参考归位在独立登记工作树`legacy-reference-layout`/分支`codex/legacy-reference-layout`准备，主迁移分支仍保留原参考入口。已调整CSV软链、common/素材根定位、Python镜像COPY路径及根pokeop兼容软链；原Python/真实自有PG577/577、布局/知识包6/6通过，均零SKIP。首次576通过/1旧DockerCOPY断言失败保留，新断言仍严格排除整个仓库和前端噪声、核对真实新路径及兼容链接。Ruff/strict mypy通过，自有PG已清理。完整Go替代验收后再纳入该重排。

- `sprite-metadata-full-20261125/`全来源路径验收PASS：固定c0542f7/子树ec56a5f，105,947条唯一资源，Go与原Python全部14项元数据/NULL/false/MIME一致。race全路径6.53秒、既有边界/manifest两项和knowledge vet通过；导出及新增Python测试Ruff0.17.6/strict mypy2.4.1通过。首次Go对照明确发现WebP MIME差异，保留原始105,947条参考和失败，独立提交e8b2f6b修复原Python类型表缺项，新27项资产/SQLite/API/视图/MIME回归通过（0.69秒），不改Go预期。修正后参考另存；独立cmp证明全部元数据和所有非WebP记录逐字节不变，仅16,526条WebP MIME修正。清单/参考SHA与代码原文归档。P3工程估算98%→99%，这不证明正文导入或全量PG恢复已通过。实际图片检出仍在同一原进程中推进，当前Apple run45548203813仍处于App/双模拟器步骤。

- `web-live-snapshot-20261125/`完整入口PASS：通过原首页“打开实时树状图”实际请求step，ROOT 1组192条outcome/1/1；正式cursor前进node10000/1/256，节点卡与战报精确一致。12条实际事件折叠/展开后数量不变，ROOT回退清空事件和后继列；全部既有业务/健康/回退/恢复继续通过，原始请求响应/截图/trace/工具SHA归档，自有实例/网络已清理。README更新实际Monorepo和四角色入口，修正BASE-DOC-001不存在的sprites submodule初始化命令，与当前.gitmodules核对；不伪称legacy目录已完成搬迁。P6工程估算83%→84%。完整图片检出进程仍活跃、持续写入HDD；Apple45548203813仍在App/双模拟器步骤，不据等待状态算通过。

- `web-branch-revisit-20261125-r3/`最终脚本完整入口PASS，实际node1的1/256→ROOT仅一列1/1→改选node2的1/128，聚合/原始视图切换通过；完整outcomes稳定、cursor/edge_id及节点卡严格核对，原全部配置/求解/任务/取消/健康/回退/恢复也通过。首次构建固定pgx依赖下载EOF，原失败保留，相同源码重试成功；新三镜像r2实际ID及工具SHA归档。生产PG健康探针同步改为正式TCP SELECT 1，`preflight-health-ready/`Docker探针healthy/输出1及完整运行预检退出0；前一次Nginx首连接reset保留，有界代理就绪等待经r3复验。项目Skill映射补齐Canonical Make→CTest/pytest→Go/Swift、真实PG与Apple/人工边界，引用文件逐项存在。P6工程估算82%→83%，全量图库模式仍未执行。当前9eac125 Apple run45548203813在App/双模拟器步骤，未推送取消该run。

- `runtime-full-20261125/preflight-ready/`真实运行配置预检退出0：独占PG目录、正式TCP目标库SQL就绪、内置SHA与宿主相同、API健康、Nginx回环发布、42共享Core全响应cmp及npm固定缓存离线安装通过。修复internal网络下前端未发布端口、显式PGDATA及initdb临时socket提前就绪竞态；失败原始记录分别保留。新验收模式使用实际运行Compose叠加maintenance overlay，增加PG真实重启/复用、全部图片正文SHA及独立恢复库同等核验，完整模式尚未运行。普通模式已在`base-regression/`固定d3fbb97完整复验通过。P6工程估算80%→82%，不标PASS。Apple修正提交9eac125已推送，run45548203813已实际启动，待结果。

- Apple45543244271（6bd30c9）已终态失败：双模拟器各9/10，仅新增首装招式详情查找独立40失败；保存/进程重启后的实际离线重算均通过。官方artifact14992530124完整下载SHA36457b30eba022dfaf38eacd31575f08fdbb5dd795c643730f6bb4cd51f0a32f匹配，两端原始无障碍树均显示完整字段“威力, 40”。本轮只修正测试为完整字段精确匹配，不修改数据或放宽预期，双模拟器重跑待完成；P4保持90%。common升级已作为733196d推送，后续失败不得倒因归于其之前尚未升级的6bd30c9。完整图片对象清单85,799项已无缺失，固定c0542f7完整目录正在展开；实际导入尚未完成，不计P6通过。

- 用户明确要求更新清理后的common并回归。迁移分支gitlink已从39e85858改为远端main9624d2a，子模块内容干净、origin规范为GitHub。原业务/真实PG571/571零SKIP，迁移111 PASS/248环境SKIP、两套工具链各149/149、Vue95/95及生产构建通过。Swift本地21 PASS/6在线SKIP后，真实Go/PG/daemon联调27/27零SKIP（15.662秒）补齐。无兼容补丁；原P0/benchmark历史不改写。完整证据及外层会话143/继续完成其余检查的说明见common-compatibility.md。当前Apple45543244271仍执行6bd30c9的新增10项UI验收，后续提交待其终态后统一推送，避免取消在跑的实际验证。

- Apple run45535685587已取回完整成功结果：iPhone9/9（625.391秒）、iPad9/9（478.275秒）、退出码均0；macOS149/149、112PASS/247外部SKIP，真实Swift27/27零SKIP。官方artifact14989082234为63,013,028字节，下载SHA e4e512527610884def4e39856fbc5ab1de0f44d9dec784fa8d9729a55be8641e与官方一致。日志/xcresult/截图/时间线私有归档，下载配置已删除。P4逐项审查见migration-ios-acceptance.md；新增首装招式详情及重启后实际离线重算断言尚待新CI，不拿旧9/9冒充新增已通过。ios/README已更新实际应用状态，移除“尚未实现”的过期描述。

- 全量Git检出真实终止128：约5.9GiB传输后early EOF/invalid index-pack，非观察超时。保留原始中断pack的reflink副本，正在离线unpack恢复完整对象，再补缺失项；未直接重复下载整个大包。新运行配置的maintenance overlay及真实PG重启、全部BYTEA SHA核对、独立恢复库核对已编写，Compose2.40.3解析通过，完整图库尚未就绪因此未实跑，不算P6通过。

- 最新`legacy-adoption-20261125/full-server/`完整入口PASS：不可变正式.11 archive、当前Go源码强制重链，全Go/PG **68 PASS / 1专用Swift serve夹具SKIP**、额外停机恢复 **10/10 PASS**，race/vet、API实际构建和六个公开HTTP读取均200。新接管/实际运行取消场景61.20秒通过；未改Core/ABI，不重复覆盖不可变archive。gofmt、bash语法和diff检查通过。Swift夹具SKIP不算本轮跨语言通过，既有真实Swift27/27证据另列。完整输入下载继续使用原Git进程，未因状态观察失败重启下载或Apple CI。

- 本轮补齐明确发现的历史库接管缺口：显式AdoptLegacy逐表固定schema/全部字段和重复行核对，默认未知非空仍拒绝。`legacy-adoption-20261125/knowledge-cancellation/`race/vet及原Python解析/知识差分PASS，晚序types核验锁实际等待后取消并完整回滚。`python-first/`由原Python实际创建/导入全部177 CSV及五图样本，加入原用户配置和任务；默认拒绝、显式接管、正常复用通过。历史已有raw/runtime表和序列的35MB导出前/后/复用三份逐字节相同，SHA e7bed0bac2e45a6cf494f6db1d6afde015d013e001859ed81e77862fc41284d8。报告/工具源码私有归档；完整图库仍在HDD下载，不把五图保留实验当全量导入。完整服务使用不可变.11 archive重新回归中。GitHub连接工具连续传输失败，未因此重启Apple run45535685587或推送取消它；最终结果待取回。

- `web-mixed-goals-first/`完整入口PASS：原Vue构造攻防与速度三目标，114×3=342/HP330、防御4/HP145、速度85/75均满足；删速度后纯伤害证据完整相同，编辑攻击次数1后真实不可达及失败UI通过。保留既有全部浏览器及健康/回退/恢复断言。本轮新增独立Go运行Compose和Make入口，原配置约束3/3通过，Compose2.20解析及Make dry-run通过；尚未启动新入口，完整运行验收仍待做。审查确认知识初始化会拒绝Python未知非空库，安全接管是明确剩余开发项，不能把空库初始化/两个Go镜像回退冒充完成此项。

- `web-solver-first/`新增速度preset/spread及候选保存后完整入口再次PASS：85对75、margin10、1个preset候选、10个满足速度目标的spread候选；从实际页面保存第一候选201，212/both及EV/IV完整核对通过。此前配置CRUD/刷新、真实图沿边前进、运行取消、健康/回退/恢复均再次PASS。node --check、bash -n、diff检查通过。全量图片Git进程已复核存活且持续写入HDD；尚未检出完成，不启动全图库导入。最新空间快照NAS SSD100GiB可用/77%，Mac数据卷16GiB可用/92%；未据此追加清理。

- 本轮`web-config-graph/`完整入口PASS：配置创建201、编辑200、刷新后UI与独立列表完整一致、删除204；图真实outcomes/advance200、一步cursor与目标节点核对、STEP1渲染。归档浏览器工具原文/SHA、截图/trace、请求/响应及回退/恢复。`web-config-first/`保留精确label选择器未匹配失败；只改验收选择器。五图`missing-steel-diagnostics/`为明确预期失败实验，212/242两图实际96×96解码，钢图缺失严格失败，不能作为完整图库PASS。新b797的Main Gate45535685582已PASS，Apple45535685587原生与双SDK步骤PASS，App/模拟器仍在运行。

- 已保存Apple run45528710141原始日志及官方artifact14986970123（56,309,347字节），SHA-256完整匹配c8cec59dc2293f5cbd9594867dc86e34fbad12ff07a2add3784dde23e5a5356a。macOS149/149、112差分/委托及247外部SKIP、真实Swift服务27/27、双SDK和device App构建证明P1/P2标准已满足；阶段审查单独记录。iPhone9/9（650.923秒），iPad7项通过后job取消；开跑01:50:53、取消02:36:06与45分钟配置吻合。仅提高job总限额75，不删用例、不放宽单项断言。完整Goal仍未完成。

- 完整sprites来源处理中：固定c0542f7的整包超过初设15分钟下载时限，已保留前缀checkpoint并终止自动从头重传，改用blob:none浅取固定提交、完整检出sprites目录，未缩减到5图样本。完整图片导入及页面解码断言代码尚待实跑；Compose2.20配置已验证，完整图库PGDATA使用本次新建SSD目录，保持素材只读。Mac空间检查只清理无编译进程/打开文件的549MiB模块缓存，剩余2.6GiB；NAS SSD仍101GiB可用，HDD素材下载未占用Mac盘。

- 最新`web-task-cancel/`整个栈入口PASS。`web-task-red/`保留45秒pending失败：验收Worker此前使用go-stack-validation.v1，不匹配原业务revision。仅修正Compose实际命令为battle-inference.summary-exploration.v2后复验；真实成功任务221/576、完整业务归因、按需Full图及root渲染通过。另四招任务先实际running后由页面取消，终态cancelled。静态bash/diff检查、完整浏览器运行及同轮回退/恢复通过，源码SHA与实际命令归档。图片及其余Web交互尚未覆盖，不据此宣告P3/P6完成。

- 本轮登记干净`stack-abi11-verification`，固定4885932的基础栈以及5529a82许可补充后的完整复验均PASS；证据在`stack-abi11-20261125/base/`与`licenses/`。当前镜像和已验证旧镜像不同，配置完整JSON在回退/恢复后保持一致。脚本新增从实际运行容器取回许可证cmp，不仅检查COPY声明。Apple run45528710141已确认阶段8/9成功，当前阶段10 App/双模拟器验收仍活跃；没有因日志暂不可取而重启该run。本地新提交等待该run结束后统一推送。

- 本轮串行补齐benchmark余下5组，`configuration-benchmark-20261125/final-comparison.log`整体PASS。原500节点/2000边/8回合预算及全局分母44100未改变；每组测量两case，Full与Summary独立比较，未外推PG/HTTP或全空间吞吐。12原始报告、冻结输入及测量源码已归档；随后三项测量工具类型修正通过strict mypy及真实Go Summary复跑，额外样本不混入原表。新增`iphone-ipad-acceptance.md`提供A–F逐步人工验收、固定212/700/418输入和明确预期，所有人工状态仍HUMAN_PENDING；设备可访问的测试服务/知识更新源须在恢复安装验收后准备，不能拿已结束的临时容器冒充现成服务。

- a4bc9f4的[Main Gate 45528710117](https://github.com/mental1104/PokemonBattleInference/actions/runs/45528710117)已通过：后端575 PASS/355环境SKIP（39.43秒）、Vue 31文件95/95 PASS，类型/生产构建通过。SKIP不计迁移验收，真实Core/Go/Swift证据仍以上述独占环境为准；此CI的Web单测/构建不代替连接Go后端的完整浏览器操作。[Apple 45528710141](https://github.com/mental1104/PokemonBattleInference/actions/runs/45528710141)仍在执行。当前串行补齐benchmark剩余5组；先核对旧测量所用archive及Core源码SHA与正式.11完全相同，保留已完成7组，未重启已确认活跃的CI。

- 2026-11-25串行检查点：`6d12312`保存正式Core 0.11（149原生/111差分委托、42共享样本），`165dfff`保存任务业务归因/诊断兼容，`6e9cd8c`保存41项API覆盖。`serial-resume-20261125/dragonite/`真实原HTTP8/8通过（2.66秒），原fake-out-pressure实际因moves维度为空返回422，测试完整比较原错误JSON；没有通过Go提升机制支持。新测试ruff/strict mypy通过。`job-results-final2/`实际公开任务20/20通过（39.79秒），之前两批17/20失败均保留，差异只在原诊断文本。`go-all-abi11/`正式.11及独占PG完整Go **66 PASS / 1专用Swift serve夹具SKIP**，额外恢复 **10/10 PASS**；race/vet、全CSV首次/复用、独立HTTP读取均通过。`swift-live-abi11/`同源码独立GCC13/Swift与GCC14/Go/PG/daemon **27/27零SKIP通过（7.971秒）**，含42共享样本、新任务来源与同步；新版Apple/App UI尚未复验。

- 分支 `codex/monorepo-migration`；工作树 `/volume2/workflow/code/worktrees/PokemonBattleInference/monorepo-migration`。不合并、不切换生产。2026-11-24 用户明确要求“先拿 github CI 测”，已授权推送本分支并开 Ready PR 以运行 CI；不启用自动合并。
- 主工作树 Makefile 有用户原有路径修正，未带入或覆盖。迁移工作树从干净的 `10c422e` 开始。
- 用户完成iPhone15Pro首版安装与开发者信任后，明确要求“先不装，先继续迭代”。保留已有App，后续只进行代码/CI工作，不自动更新、安装或启动手机；这不暂停原重构Goal。
- 初始common/pokeapi分别固定39e85858、1567d530；2026-11-25用户明确授权后common更新为9624d2a并完成兼容回归，pokeapi版本保留。旧基线和数据来源仍可追溯。
- Python实体已在完整Go替代/HDD/NAS验收后归入`legacy/pokeop/`，根`pokeop`保留兼容软链；原Python业务和测试不删除，固定CSV/common及静态资源路径已调整并复验。
- PostgreSQL 测试会删除测试 schema，因此只允许连接本次创建的临时 PostgreSQL；禁止填入生产 URL。验证服务不发布数据库端口。
- NAS 宿主 Python 为 3.8.15，未发现宿主 C++/CMake/Go/Swift；用声明的 `maintenance` 服务执行一次性 Python 3.11/C++ 验证，源码只读、输出路径独立。

## 人工及平台事项

| 项目 | 状态 | 后续操作 |
| --- | --- | --- |
| macOS / Xcode 构建 | PASS | 9eac125完整Apple CI原生149/149、双SDK/未签名device App、两模拟器各10/10及真实Swift27/27通过，官方产物SHA已匹配；用户Mac此前已签名安装的旧版保留。 |
| Apple 登录、Team、签名 | PASS | 复用用户Mac已有有效开发身份与Team；SSH签名失败后在已登录GUI会话正常构建成功，未修改Keychain ACL或读取密码。 |
| iPhone/iPad 安装及验收 | HUMAN_PENDING | iPhone15Pro已真实安装并启动，用户已亲自完成开发者信任；图标版也已安装启动。双设备完整人工验收、iPad物理安装和体验仍待完成。 |
| NAS新Go服务及域名反代 | PASS | pokemon.mental1104.xyz已提供Web、API和知识包；HDD图标版本已升级，1,374个图片URL逐一SHA校验及真实浏览器通过。 |
| 正式备份、最终合并及其他生产切换 | HUMAN_PENDING | 正式备份已获授权并完成隔离恢复验证；最终合并审批仍待，新服务部署授权不包含自动合并或切换其他业务。 |

## 验证记录

原始报告：`/volume1/homes/mental1104/Backup/PokemonBattleInference/migration-20261124/`。

- 原 Python：`python -m pytest tests --ignore=tests/migration -q`：565 passed，6 个数据库 fixture 因 `compose run` 无服务 DNS alias 失败（76.55 秒）。修正容器 URL 后，`python -m pytest tests/persistence/battle_inference/test_job_repository_postgres.py -q`：6 passed（5.81 秒），均使用专用临时库。
- 原 Web：`npm ci` 后 `npm test -- --maxWorkers=2 --minWorkers=1`；NAS Node 段错误，Linux Node 22 容器完整执行为 94 passed / 1 failed（9.85 秒）。失败原因与独立修正范围见 `BASE-WEB-001`。
- `npm run build`：类型检查与 Vite 生产构建通过。
- 原 benchmark：`python -m pokeop.benchmarks.configuration_space --workload budget-stop-10x10 --workers 1,2 --max-pairs 2 --progress-every 1 --output-dir /reports/legacy-benchmark`；单/双 worker 分别 270.777 / 140.881 秒，概率摘要一致，均两个预算截断结果，零失败。完整报告在 `docs/benchmarks/`；未测试全空间或 PostgreSQL 写入耗时。
- `python tools/migration/capture_baseline.py --output-dir /reports/contracts`：41 HTTP operations、185 tables；未连接数据库，快照已保存并附 SHA-256。

## 首批 Core 实现与最终回归

- `make test` 成为 macOS/Linux 共用后端入口：先 `make test-core`，再全部 pytest。Core 是 C++20 静态库，Boost headers 明确声明；GoogleTest/CTest 不需要数据库或 Docker。NAS 宿主借用一次性工具容器，不改变这个库的依赖。
- 共享向量：`tests/vectors/calculations.v1.json`。四组真实进程差分覆盖 13 个冻结向量、4,096 配置的 HP/非 HP（8,192 项）、91 个能力等级、144 组精确 KO，以及错误后继续执行。尚不覆盖伤害规则/完整速度效果/回合/状态图。
- `Rational = boost::rational<cpp_int>`；200 位分母、规范零值与相消为零验证通过。初次 `cpp_rational` 零概率不约分问题由原测试捕获，替换数值类型后保留精确相等断言。
- `bash tools/migration/validate-nas.sh all`：**PASS**，日志在上述报告根的 `final-regression/`。`make test CORE_BUILD_DIR=/build/core`：CTest **6/6**，pytest **575 passed / 0 skipped**（含原 571 项与四组差分、真实 PostgreSQL，20.83 秒）；Web **95/95**（31 文件，10.11 秒），生产类型检查/构建 PASS（1.49 秒）。脚本的专用 PostgreSQL 退出清理已核对，不挂载生产数据。
- 后续仅将 C++ 测试中的预期异常调用显式丢弃返回值，并将所有自有 C++ target 的警告按错误处理。`bash tools/migration/validate-nas.sh core` 再验证：**CTest 6/6、差分 4/4**（0.20 秒），无 C++ 编译警告；日志 `core-final/`。CMake 当前 FindBoost policy 有开发提示，未影响构建。
- 新批次 benchmark：`python tools/migration/benchmark_calculations.py --runner /build/core/pbi_core_vectors --output /reports/core-calculations-benchmark.json`；20,000 非 HP 配置，5 次采样，全部结果逐字一致。Python 中位数 **7.221 ms**，C++ 进程 **33.210 ms**（含进程/文本/IO）。原始 JSON 已保存到 `docs/benchmarks/core-calculations-20261124.json`；共享 NAS 有其他负载，未测 C ABI 直接调用或完整战斗性能，不声称提速。
- 原 Python 计算、所有业务表、原部署定义和 submodule revision 保留。新增 Boost/GoogleTest 许可已登记。不更新 CI、不自动推送或合并。

## C ABI 与双语言实际调用（2026-11-24）

本节覆盖的新工作在原报告旁保存：`/volume1/homes/mental1104/Backup/PokemonBattleInference/abi-20261124/`。上节“不更新 CI/不推送”描述的是首批历史检查点，现已被用户明确 CI 授权更新，仍不合并/不切换生产。

- `contracts/c/pbi_core.h` 为唯一 C 头，JSON 批次先转换成 typed C++ variant，再复用现有计算库。明确 malloc/release 所有权、异常/错误码、版本、单向原子取消、并发和整批原子结果；无新增计算规则实现。
- 实测 C/C++ **13/13**；含 C 编译器、字段/整数/未知规则、8 MiB/操作/伤害槽位/深度/结果溢出预算、反复释放、32 并发和已确认运行中的取消。最终 ASan/UBSan/leak **13/13 PASS**（14.20 秒），日志 `sanitizer-final.log`。
- Go **4 项测试 PASS**（bridge 3 + 真实回环 HTTP 1），`-race`、`go vet`、实际服务构建通过；Go 1.24.4。首次执行因容器 `/tmp` 为 noexec 失败，改用专用 `GOTMPDIR=/build/go-tmp` 后通过，未调整通用模板权限。
- Swift **4 项 XCTest PASS**（Swift 6.0.3 Linux），实际导入同一 C 头并链接 Core 静态库；完整五操作共享向量、版本、错误、32 并发与运行中 Task 取消通过。首次 manifest 受 noexec 影响，改为专用可执行构建临时目录。日志 `swift-test-fixed.log`、`bindings-final/swift-regression.log`。
- `bash tools/migration/validate-nas.sh all`：CTest **13/13**、pytest **576 passed / 1 skipped**（22.09 秒）；唯一跳过为 Python 工具镜像没有 Swift，随后专用 Swift maintenance 实际 **4/4 PASS**。Web **95/95** 和生产构建通过。原始证据在 `unified/`，不将 SKIP 伪装成 PASS。
- 为解决外部静态库缓存问题，Go 委托测试/交付构建使用 `-a`；Swift scratch 使用两个 archive 的 SHA-256。修正后 `validate-nas.sh bindings` 再次通过：CTest **13/13**、Python/Go 委托 **5 passed / 1 skipped**（12.42 秒）及 Swift **4/4**（1.223 秒）。
- 独立 curl 在 NAS 进程访问一次性 Go 服务容器：**HTTP 200** 与完整冻结响应一致（202、200、73、1/3 与 5/9、231 及版本），未知操作 **422** 且无部分 results；请求、响应头/状态/正文和服务日志在 `http/`。实例与随机回环端口已清理，不涉及生产。
- SwiftUI、知识/用户 SQLite、旧 API/Worker/PG、同步和生产切换尚未实现。当前 Go 同步入口不隔离 SIGSEGV/abort，复杂推演后续必须放在独立 Worker 进程。

### 用户授权的 GitHub CI

新增 `.github/workflows/native-core.yml`：只响应 main 目标 PR 的 opened/ready_for_review/reopened/synchronize，所有 job 以 `draft == false` 保护；没有新增 push/schedule/manual 触发器。计划实际验证 macOS C++/Go/Swift/差分，并用现有 Xcode SDK 构建 arm64 iPhoneOS + Simulator 静态库、Swift 模块和 C ABI XCFramework；无 Apple 登录、Team、签名或设备安装。当前尚未取得 CI 结果，不能标记 Apple PASS。

已推送 `425c9b8` 并建立 Ready PR [#138](https://github.com/mental1104/PokemonBattleInference/pull/138)。使用现有 GitHub SSH 认证推送，未新增凭据。首次 CI：

- Main Gate [45342676060](https://github.com/mental1104/PokemonBattleInference/actions/runs/45342676060)：PASS；原 Python **571 passed / 6 skipped**（未在该旧 job 构建的 native 用例），Web **95/95**、生产构建通过，日志已归档到本次 Backup。
- Native Core [45342676029](https://github.com/mental1104/PokemonBattleInference/actions/runs/45342676029)：macOS 原生步骤 PASS，CTest **13/13**、Python 差分和 Go/Swift 委托 **6/6**（77.66 秒，无跳过）。iOS 配置失败：`Could NOT find Boost (missing: Boost_INCLUDE_DIR)`；同机 macOS 已成功发现依赖，不能把它误记为未安装。
- 修正位置：`build-apple-core.sh`，为 iOS 交叉编译显式提供已安装、平台无关的 Boost headers 和 nlohmann_json CMake package 路径，继续由实际 SDK 编译 C++。没有跳过 Apple 步骤或降低断言；等待修正后的 CI。

修正提交 **`738919aa0ea5900d1de852d864630a6a22e01dc9`** 的实际 CI 结果：

- Native Core [45343368822](https://github.com/mental1104/PokemonBattleInference/actions/runs/45343368822)：**PASS**，包括 native tests、iPhoneOS/Simulator 编译与 XCFramework 打包；macOS CTest **13/13**，差分/Go/Swift 委托 **6/6，无跳过**（60.80 秒）。实际工具链为 Xcode **16.4 (16F6)**、Swift **6.1.2**、AppleClang **17.0.0**、Go **1.23.12**、CMake **4.5.0**。
- Main Gate [45343368873](https://github.com/mental1104/PokemonBattleInference/actions/runs/45343368873)：**PASS**，包括原后端、Web 测试及生产构建。
- 已下载并核对 [Apple 产物 14896444554](https://github.com/mental1104/PokemonBattleInference/actions/runs/45343368822/artifacts/14896444554)：ZIP SHA-256 **`7fb8c6fabeb9809873108a579c418df9e00081c295df605e7b885052a2ab5f86`** 与 GitHub digest 完全一致。永久保存在上述 Backup 根的 `native-apple-738919a.zip`，最终 job 日志为 `github-apple-45343368822.log`，失败首次 ZIP/日志也保留，未用成功文件覆盖。
- 独立读取 ZIP 的 `Info.plist`：同时存在 **ios-arm64** 和 **ios-arm64-simulator**，平台均为 ios，后者明确标为 simulator；两个静态库均为实际 ar archive；两个平台的 C 头与本仓库完全一致，均有 `_pbi_v1_compute` 导出与非空 `PokemonCore.swiftmodule`。JUnit 确认为 6 tests / 0 failure / 0 error / 0 skipped。
- 以上仅证明首批 Core/Swift 桥接的真实编译和 macOS 调用；尚无 SwiftUI App 或模拟器运行测试、设备安装、离线包/用户库及同步，因此 P1–P6 整体依然未通过，Goal 未完成。今晚 Mac 的身份/签名/物理设备操作仍按 Human 边界，工具可执行事项由 Agent 承担。

## 直接伤害与规则切片（2026-11-24）

证据根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/damage-20261124/`。

- 新增 `core/include/pbi/damage.hpp` 与 `core/src/damage.cpp`：纯 typed 输入、原策略全部字段、18 属性标识、知识快照注入、1…9 兼容 profile、1…31 版本组映射，保留完整直接链顺序和 trace。未知标识/缺失知识明确失败。完整动态战斗状态/效果尚未迁移；multiscale/inner_focus 在该入口显式 UNSUPPORTED，不冒充已支持。
- 概率仍为 `boost::rational<cpp_int>`。原 Python 的直接伤害倍率本来使用 binary64，此处保留原 floor 与乘法顺序；int/int 采用任意精度正确舍入到 binary64，避免先转分子的双重舍入。边界测试捕获了 scaled 超出 int64 而最终伤害合法的情况，已保留任意精度中间 floor，没有缩小测试输入。
- 直接计算结果经 `damage` C ABI 操作接入既有 Go/Swift；共享向量扩为六操作，新增全部 16 档 **99…117**、二击率 **123/128**、trace/版本的完整冻结响应。引擎 `0.2.0`，规则集合 `calculation-rules.v2`，C ABI/schema 仍 v1，单独 `damage_ruleset_id=python-compatible.genN.v1` 标记原部分 profile，不宣称完整官方历代机制。
- 内部 KO 档位扩为 int64 以直接接受伤害输出；门槛差值和两击保证判定用任意精度，覆盖 INT64_MIN/MAX 混合边界。既有 v1 `ko` JSON 输入仍按原 int32 合同验证。
- 新 Python 差分通过真实 `pbi_v1_compute` 入口，覆盖 **4,540** 输入：冻结样本、全部 **18×18** 配对、**3,072** 组组合、九代际 **1,134** 个自定义策略组合及 **9** 个大整数边界；逐个比较全部 **61,300** 档位、base、完整 trace 的 key/stage/source/reason/倍率和精确 KO，无浮点容差放宽。
- `validate-nas.sh all`：C/C++ **18/18**；完整 Python **579 passed / 1 skipped**（32.13 秒，跳过为 Python 镜像没有 Swift），临时真实 PostgreSQL 回归通过；Go race/vet PASS；专用 Swift **4/4 PASS**，包含完整伤害共享向量；Web **95/95** 和生产构建 PASS。原始日志在 `final/`。
- ASan/UBSan/leak **18/18 PASS**（21.14 秒），含新伤害错误/预算/快照与并发、取消、循环释放，日志 `sanitizer.log`。
- 独立 NAS curl 验收当前实际 Go 服务：HTTP **200** 完整六操作响应一致；未知操作 **422** 无部分结果。证据在 `http/`，自有容器与随机回环端口退出清理，不触碰生产。
- 新实测：`python -m tests.migration.test_core_damage --runner /build/core/pbi_abi_vectors --count 10000 --repeats 5 --output /reports/damage-benchmark.json`，每次全部结果核对后记录。Python 中位 **0.468292 秒**；C++ 进程 **0.528825 秒**，后者额外包含 JSON、精确 KO、进程与 IPC；不宣称纯函数/全引擎提速。报告在 `docs/benchmarks/core-damage-20261124.json`，原始在 `final/`。
- 本批代码提交 **`7b9f4a4bfacc896ea98cd47c59c3aca2957feaec`**，已推送 Ready PR #138；[Native Core 45349703813](https://github.com/mental1104/PokemonBattleInference/actions/runs/45349703813) **PASS**：macOS CTest **18/18**，差分/Go/Swift 委托 **9/9、无跳过**（66.66 秒）；iPhoneOS/Simulator archive、Swift module、XCFramework 实际构建成功。工具链仍为 Xcode 16.4/Swift 6.1.2/AppleClang 17/Go 1.23.12/CMake 4.5.0。
- [Main Gate 45349703635](https://github.com/mental1104/PokemonBattleInference/actions/runs/45349703635) **PASS**：原 Python **571 passed / 9 skipped**（该旧 job 不构建 native，三个新增伤害差分也跳过；均已在上项 native job 实际执行），Web **95/95**、构建 PASS。两个实际 job 的完整日志分别保存在证据根 `github-apple-45349703813.log`、`github-main-45349703635.log`。
- 已下载并独立核验 [Apple 产物 14899787064](https://github.com/mental1104/PokemonBattleInference/actions/runs/45349703813/artifacts/14899787064)：ZIP SHA-256 **`14b2eef09d7891876c643314178fbd2eeb17fa74db87fc1791f4f752d069fe99`** 与 GitHub digest 一致；每个平台 archive 含 calculations/damage/ABI 三个实际 arm64 Mach-O 对象，其 LC_BUILD_VERSION 分别为 **2（iOS）**、**7（iOS Simulator）**。共享 C 头与当前仓库完全一致，均含 compute 导出；Swift 模块分别 22,236/22,256 字节；JUnit 9 tests、零错误/失败/跳过。ZIP、工具链与可复跑核验脚本/JSON 保存在同一证据根。
- 以上仍只证明 Core/桥接及 SDK 构建，不代表 SwiftUI App、模拟器运行、双设备使用、离线库或同步已实现。P1–P6 的完整目标与 Human 验收要求保持不变，Goal 继续 active。

## 不可变状态与独立状态修正（2026-11-24）

证据根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/state-20261124/`。

- 新增纯 Core `status.hpp/.cpp`、`state.hpp/.cpp`：完整主/临时状态、StatStages、MoveSlotState、MoveSpec/PokemonSpec、推演规则与执行策略、BattlerState/BattleState；所有外部视图只读，更新返回新快照并验证 HP/PP/槽位/讲究锁招不变量。祖先/兄弟节点不受更新影响。
- StateKey 排除名称和绝对回合号，完整保存其余未来相关字段，包括策略和运行时 slot_id；临时状态规范为集合。内部有长度前缀的完整语义编码避免分隔符碰撞，标准库哈希只用于进程内索引；实际 unordered_set 去重与浮点 +0/-0 一致性已测试。键不是网络/同步 ID。
- 独立麻痹 helper 保留原 1…6 代 1/4、7…9 代 1/2；灼伤倍率为精确分数。原行动排序仍只使用能力等级，未悄悄叠加独立麻痹 helper。原切换清理仅清除混乱/迷恋，保留主状态和畏缩，也按参考行为保留。
- 新增 `battle_state` 和 `status_modifiers` C ABI 操作，复用同一 JSON 字段/整数/策略边界与完整伤害编码。状态更新后可通过实际 PP/禁用/锁招检查、方向/屏障和已消耗道具转换执行同一伤害 Core；不复制计算规则。完整协议在 `contracts/c/state.v1.md`。
- 引擎 `0.3.0` / `calculation-rules.v3`，ABI/schema 仍 v1。共享向量扩为八操作，新增 Python 参考生成的独立状态修正及完整状态更新冻结响应；Go/Swift 实际链接调用并比较全部字段。
- Python/C++ 差分：1,024 组生成状态更新、全静态/动态字段/策略的键敏感性矩阵、完整状态更新后实际伤害，以及 1,146 个独立状态修正样本（含自定义 200 位分母）。预期来自旧 Python 公开模型/StateKey/行动排序/状态 helper；不复制 C++ 键编码，不放宽精确断言。
- `validate-nas.sh all` PASS：C/C++ **27/27**；Python **583 passed / 1 skipped**（34.45 秒，缺 Swift 的工具镜像明确跳过），真实临时 PostgreSQL 回归通过；Go race/vet PASS；专用 Swift **4/4 PASS**（1.176 秒），Web **95/95** 和构建通过。日志 `final/`。
- ASan/UBSan/leak **27/27 PASS**（31.45 秒），日志 `sanitizer.log`；独立 NAS curl 访问实际 Go 服务，八操作 HTTP **200** 与冻结响应完整一致，未知操作 **422** 无部分结果，证据 `http/`，实例退出清理。
- 边界测试曾捕获负分母输入导致 INTERNAL_ERROR（`vectors/core-regression.log`）；在交给有理数构造前统一分母符号后，原 **0001/-0003 → -1/3** 精确断言通过。分数输入每个分子/分母最多 1024 位；每状态最多 256 更新，所有原始/参考/更新策略槽位共同计入批次预算，超限显式失败。
- 已知边界：effect 标识支持原 ASCII 规范化，非 ASCII 机制标识明确 UNSUPPORTED；中文展示名/来源正常保留。multiscale/inner_focus 可完整存入状态，动态效果执行仍待迁移，直接伤害入口保持明确 UNSUPPORTED。完整回合、状态图与 App/同步尚未完成。
- 提交 **`e8a8b2749c9148eaa9ba44107e57db702cda79ed`** 的 [Native Core 45356308995](https://github.com/mental1104/PokemonBattleInference/actions/runs/45356308995) **PASS**：macOS CTest **27/27**、迁移/Go/Swift 委托 **13/13，无跳过**（73.87 秒）；[Main Gate 45356308957](https://github.com/mental1104/PokemonBattleInference/actions/runs/45356308957) **PASS**。iPhoneOS/Simulator SDK 库均实际构建成功，尚未运行 App。
- 已独立核验 [Apple 产物 14902881683](https://github.com/mental1104/PokemonBattleInference/actions/runs/45356308995/artifacts/14902881683)：ZIP SHA-256 **`4a90a8ac8c41407065ad35bfc202761329854e40b976ff937347405a16e935ca`** 与 GitHub digest 一致；两个平台各含六个实际 arm64 Mach-O 对象，LC_BUILD_VERSION 分别为 iOS **2** 与 Simulator **7**，共享 C 头与仓库相同、含 compute 导出、Swift module 非空，JUnit 无失败/错误/跳过。ZIP、完整 job 日志与核验脚本/JSON 在本节证据根。

## 离线知识与 AppSupport 检查点（2026-11-24）

证据根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/app-20261124/`。

- 新纯 Core `profile` 操作统一处理完整六项能力和性格轴，客户端仅投影输入，未在 Swift 重写公式；引擎 **0.4.0** / **calculation-rules.v4**，ABI/schema 仍 v1。新增冻结共享 profile；全部 **25×64=1,600** 配置的 **9,600** 能力字段与原 Python `NATURES`/`calculate_actual_stats` 精确一致。
- `data/knowledge/schema.v1.sql` 与 `tools/data/build_knowledge_pack.py` 从固定 PokeAPI `1567d53073a069b6c96e1c393c5c490f602e3ab5` 投影真实离线知识；15 个 CSV 与 schema 摘要计入版本。已捆绑 **413,696 bytes** SQLite，版本 **pokeapi-1567d53073a0-7e4be433ddb6**，SHA-256 **97077d1074f39a83e89aa3b0f7b0dff9bb6db7b89821e502e497bf924d86d44f**，含 1,350 宝可梦、937 招式、25 性格及 324 属性关系，并保留来源许可。
- 实际验证完整摘要/外键/表数量，全部属性关系与原知识一致；固定 CSV 重建得到相同逻辑版本与来源，重复构建字节一致；源缺失时原产物未被覆盖。`profile-data-final/core-regression.log`：C/C++ **28/28**，迁移 pytest **16 passed / 1 skipped**（17.44 秒，跳过为 Python 工具镜像缺 Swift）。这些结果不代表后续并行编辑的 Go/同步文件已经通过。
- Swift `KnowledgeStore` 使用只读 SQLite 与独立目录，先验证候选包再提交原子版本指针，保留旧文件；`ConfigurationStore` 独立用户库，事务内同时保存配置/稳定 ID/本地队列，软删除与重启恢复；`CalculationService` 调用同一个 C ABI，在线入口使用相同请求、不静默回退。Linux **10/10 XCTest PASS**（1.698 秒，含既有 4 个桥接测试），日志 `swift-app/swift-regression.log`。覆盖真实中文查询、99…117 伤害/123/128 二击率、85/80 速度与麻痹 42、知识更新失败/恢复、用户数据保留及注入队列失败后的事务回滚。
- 当前只证明 Linux AppSupport 与本机 Core 闭环；在线 Swift 计算客户端、SwiftUI App 编译/模拟器运行、复杂推演及真实双设备仍未验收。检查点 **11bbedc9bc2e07dd9f2a3d1729af4dbb1b1eaa4c** 已推送 Ready PR；[Native/App CI 45362670690](https://github.com/mental1104/PokemonBattleInference/actions/runs/45362670690) 与 [Main Gate 45362670582](https://github.com/mental1104/PokemonBattleInference/actions/runs/45362670582) 已启动，尚未确认结果。
- P5 首批同步底层已独立实测：Go 真实隔离 PostgreSQL 三个业务测试 `-race` PASS、`go vet` PASS；实际 HTTP 服务 fixture PASS（131.71 秒），两个独立 Swift SQLite 客户端完成丢 ack 重试、重启、离线冲突/显式恢复、版本保留和删除传播，最终 cursor 均为 4；Swift **13/13、零失败/跳过**（1.797 秒）。证据在 `Backup/PokemonBattleInference/migration-p5-sync-20261124/`，详见 `migration-sync.md`。这不代表 App 同步 UI 或真机验收通过。
- 用户要求 P1/P2 也由专属 agent 处理；最初系统四线程上限拒绝新建。在 P4/P5 首批交接释放名额后，已分别实际启动 **p1_core**（合法行动/回合/图/SCC/搜索）与 **p2_bridge**（C ABI、Go/Swift、新能力接入、真实在线/离线一致验收）。当前并行的是 P1/P2/P3 加 root；root 负责统一提交/CI、App/同步 UI 整合。P4/P5 后续按需轮换，不声称五条子任务同时运行。

## 并行迁移与首轮 App 反馈（2026-11-24）

- 服务端检查点 **60d9fe9**：原 **16/41** 配置/知识/图片 API、非破坏运行表初始化、持久化同步及原生子进程边界；真实全量 CSV/八个原 MV + 自有 PostgreSQL 的 Go race **11 PASS / 1 专用 Swift 服务 fixture SKIP**，独立 curl 五个 HTTP 200。子进程向量/错误/取消和真实 SIGKILL 隔离 **2 PASS**。首次 512 MiB tmpfs DiskFull 证据保留，专属 2 GiB tmpfs 重跑通过；未改通用维护模板或生产。详见 `migration-server.md`。
- Core/在线验收检查点 **01a5db5**：纯合法行动（PP/禁用/讲究锁招/濒死/挣扎及两种精确策略）、有限图 SCC/精确 DAG 与循环求解、预算/未知截断/无限期望/取消。Linux CTest **36/36**，原 Python 真实拓扑差分 **3/3**（288 随机图、边界和 2,500 深链），ASan/UBSan/leak **36/36 PASS**（32.52 秒），证据 `Backup/PokemonBattleInference/core-graph-20261124/`。这不代表完整战斗回合器已迁移。
- 真实 Swift → 独立 Go HTTP → C++ 对三组完整配置验证逐字段及请求/响应字节一致；在线 **2/2 PASS**，实际 404 明确失败无离线回退。该次 Swift **15 tests / 1 skipped**（缺 P5 专用服务 URL，P5 已另测真实收敛），证据 `Backup/PokemonBattleInference/migration-p2-online-20261124-fixed2/`。正式图/行动 ABI 的 .5 版本由 P2 后续统一交接。
- **11bbedc** [首轮 App CI 45362670690](https://github.com/mental1104/PokemonBattleInference/actions/runs/45362670690) 最终 **FAIL**：macOS CTest **28/28**、迁移 pytest **17/17**（54.90 秒）、两 SDK 库及未签名 device App 构建成功。iPhone 三个 XCUITest 中中文知识首装查询 PASS；伤害断言拿到合并无障碍标签 `伤害, 99–117`，保存测试未找到成功提示，故两项 FAIL，iPad 尚未执行。Main Gate **PASS**。
- 首轮产物 [14905627832](https://github.com/mental1104/PokemonBattleInference/actions/runs/45362670690/artifacts/14905627832) ZIP SHA-256 **01ab38260cb4f812b1e9030c2e5f921139c3684e789aa80891e77d5b1f70d3d2** 与 GitHub digest 一致；完整日志、xcresult/ZIP 在 `Backup/PokemonBattleInference/app-20261124/`。测试结束的 final screenshot 是主屏幕，不能用来证明失败时 App 内状态。
- 已将指标改成明确无障碍名称/精确值并保持原冻结数值断言；保存测试增加懒加载行滚动，仍待下一轮验证其失败原因。测试脚本即使某机型失败也继续独立执行另一机型，并导出 xcresult 附件，最终仍返回失败。
- 新增 App 手动同步/取消、真实待提交项、完整冲突双方参数/删除状态/版本比较和明确选择。连接设置在 SQLite 事务保存，禁止沿用其他服务器/用户的同步空间；注入身份写失败时 URL/账户一起回滚，重启、非法地址和范围保护实测。修改后的 AppSupport **4/4 PASS**（0.179 秒），UI/UITest Swift 语法与 shell 检查通过；Apple UI 运行未验证，证据 `Backup/PokemonBattleInference/app-sync-20261124/`。
- **8049ddc**：图/合法行动正式 C ABI 及 Go/Swift 冻结向量已扩展至十一操作，引擎 **0.5.0 / calculation-rules.v5**，ABI/schema 仍 v1。纯域新增结构化事件/条件权重、分支合并与注入回合转移器的不可变 BFS 图构建；完整旧回合器尚未迁完，不以自定义回调测试代替。新域/runner **14/14 CTest**、图与 builder **5/5 Python 差分**（1.41 秒，新增 106 组），新纯域 ASan/UBSan/leak **32/32 PASS**（1.58 秒）。P2 图 ABI 另有 50 拓扑、行动 ABI 256 情况的精确差分；全量 CTest **46/46 PASS**。全量 ASan/UBSan/leak 原进程最终 **46/46 PASS**（455.88 秒，其中大批次节点预算 347.41 秒、图运行中取消 40.43 秒），日志 `migration-p2-online-20261124-fixed2/sanitizer.log`；未重启、未删减断言，临时容器已清理。
- **f04a552**：新增旧通用任务列表/详情/幂等取消，进度 **19/41**；真实 PG 仓库验证稳定 fingerprint/重复提交、租约/心跳/过期恢复、进度守恒、取消和结果分页。独立重建 .5 Core 后 CTest **46/46**，Go 所有包 **18 PASS / 1 专用 Swift 服务 fixture SKIP**、race/vet 通过，外部 curl 六条 HTTP 200；测试实例已清理。证据 `p3-server-20261124/jobs-final/`。任务创建/复杂推演/完整 coordinator 仍未完成，原生 CSV 初始化正在另批开发，未纳入该检查点。
- **e248d3b**：计算通过一个 actor 调用读取宝可梦/招式/性格/属性表及 manifest 的不可变快照，避免知识安装插入多次 await 导致混用版本。两个真实 SQLite 包、16 次安装和 64 次读取竞争，所有输入字段与版本保持整版一致，旧快照不变。实际 Swift→Go HTTP 完整 .5 请求/响应仍一致，整包 **17 tests / 1 skipped**（仅未配置 P5 专用服务 URL），零失败（2.721 秒）；证据 `migration-p2-snapshot-online-20261124/`。
- 上述代码统一推至 **e60eb2dd5d23c57632d015ea5fe56075ca86ca0d**；[Native/App 45366954912](https://github.com/mental1104/PokemonBattleInference/actions/runs/45366954912) 最终 **FAIL**，[Main Gate 45366955174](https://github.com/mental1104/PokemonBattleInference/actions/runs/45366955174) **PASS**。新失败发生在 macOS Core 编译：AppleClang 17/Xcode 16.4 libc++ 未提供新代码使用的 `std::stop_token`，报错位于 `graph.hpp:92/99` 及 `graph.cpp`；Apple SDK/App/UI 步骤未执行，不能称为上一轮 UI 失败重现。完整真实日志已保存 `app-sync-20261124/github-native-45366954912.log`。
- P1 当前优先修正可移植取消令牌/源，保持单向原子取消、共享生命周期、空令牌及 C ABI v1 语义，不降 C++ 标准或移除取消断言；稳定后再继续旧回合器。P2 完成本轮切片后释放名额，P4 已重新接手 App CI 及知识下载/中断恢复；P3 继续 Go 原生 CSV/物化视图初始化，未提交的 importer 尚未验收。root 负责 P6 与统一整合，当前可自动化工作不被 Human 事项阻塞。

## 0.6 检查点与最新 Apple 反馈（2026-11-24）

- **76a40a0** 保存正式 `battle_turn`、`fixed_battle`、兼容 C ABI v1 的 typed 进度回调及有界 NDJSON child。引擎 **0.6.0 / calculation-rules.v6**，共享完整向量为 13 操作。`turn-abi-20261124/` 已实际 **58/58 CTest PASS**、正式 turn/fixed ABI 差分 **2/2 PASS**、Go bridge **6/6** 和 workerprocess **8/8** `-race`/vet PASS。迁移 pytest **28 passed / 8 skipped**（27.70 秒）：七项当时未登记的候选 runner、一项缺 Swift 工具环境，未把跳过当成通过。P2 使用 Git 注册的独立 detached `abi6-verification` 验证树，固定 SHA 的 ASan/Swift 结果另行记录。
- 正式回合与固定战斗的完整差分、动态覆盖边界及五个真实小图 benchmark 详见 `migration-core.md`。固定战斗默认 20,000 节点/80,000 边、原生成图上限 2,000,000 节点/8,000,000 边/10,000 回合仍保留；显式图继续使用其独立边界。缺省/null 分支和方程预算保留原不设限语义，结果传输预算单独明确失败；没有用缩小原任务范围换测试通过。
- **0c10056** 接入真实 fixed_battle 与进度落库，`nativeworker-20261124/progress6/` **7/7 PG/child/daemon 测试 PASS**（3.943 秒），race/vet 通过。两个攻守视角得到同一旧结果合同；一节点预算真实截断保留 NULL 概率。租约、取消、SIGTERM 停机恢复及独立 daemon 均实际运行，详见 `native-worker.md`。
- **a755043** 纯 Go db-init：179 raw 表、177 CSV、八个原 MV；全部 1,051,800 条来源记录逐字段 Python 语义摘要一致，主键去重后 1,051,052 行，六项真实 PG race 测试与 vet 通过。**a74d98e** 的 HTTP 0.6 完整向量与生命周期测试通过，实际 30 秒 504/运行中 SIGTERM 408 后 child 均已回收；scratch API/数据镜像分别 46,786,282 / 82,609,776 字节，六条目录/配置/任务 API 和 13-op Core 响应实测通过。详见 `migration-server.md`；Docker 健康周期和完整部署不在该验收范围内。
- **89b7db9** 保存 Swift 知识更新客户端、来源设置和界面，严格下载预算、校验与 Range 续传使用真实 HTTP 夹具；安装失败/取消保留旧包及用户库。工具镜像 Swift **20 tests / 3 explicit skip / 0 failure**（17 项实跑，缺独立在线/同步 URL 的三项明确跳过）；此前双 SQLite/Go/PG 的同步 13/13 仍是独立实测证据。
- 最近已推送 **fc068e3** 的 [Main Gate 45369481139](https://github.com/mental1104/PokemonBattleInference/actions/runs/45369481139) **PASS**，[Native/App 45369481161](https://github.com/mental1104/PokemonBattleInference/actions/runs/45369481161) **FAIL**。可移植取消修复使 macOS CTest **49/49**、两个 SDK 库与未签名 device App 构建通过；iPhone 查询、保存重启、同步设置 **3/4 PASS**，麻痹开关仍为 0、速度 85 而非 42；iPad 四项均在旧 TabBar 入口定位失败。不能写成数学计算错误或 App 启动失败。
- 产物 **14912441828** 已下载独立验 SHA-256 **bfa53a53334acb55c0711fcf804e66df3141e51deafd334441f5e415489b8fba**，ZIP/完整日志在 `app-sync-20261124/`。实际截图/无障碍层级显示 iPhone 命中整行而非内层 UISwitch，iPad 正常启动并使用顶部浮动按钮。修复保留严格 `0→1→42`、全入口可见中文标签和横屏断言，增加层级/阶段时间及只关闭自启模拟器；Swift parse、bash syntax、diff 检查通过，修复结果以新 CI 为准。
- **63f4d8e** 已将四维候选登记为真实 Core/CTest/runner：完整 **70/70 CTest PASS**（2.27 秒）及配置差分 **7/7 PASS**（1.31 秒），冻结 17 文件摘要匹配。保留默认四招选择、raw 成员预算、精确权重、覆盖字段及 Python 代表标签；标签格式已避免比当前 iOS/macOS 最低版本更新的浮点 `to_chars` 依赖。该空间的等价类代表不冒充旧 job-v1 的全部具体 case/canonical 身份，后者单独迁移。
- 固定 **76a40a0** 的完整 ASan/UBSan/leak **58/58 PASS**（139.75 秒），Go `-count=1 -race` **14/14** 与 vet PASS，GCC13 **58/58**、Swift **17 PASS / 3 SKIP**。固定 **a74d98e** 的独立 Swift→HTTP→child 计算 **2/2 PASS**，但整套为 **18 PASS / 1 FAIL / 1 SKIP**：取消更新方法中两条失败记录，包含一次 invalidEndpoint。原无审计日志已被 fixture 清理，不能声称确认根因；带审计重复 12 轮 **36/36 PASS**。已明确修复代码中 ready 文件非原子发布/空串可成为相对 URL 的窗口，并补始终保存 ready/启动状态/HTTP 审计；没有延长等待或降低 8192 字节/取消/续传断言。
- **4637deb** 新 `/v1/calculator/damage` 通过同 PG 原 FastAPI 的 **14/14** 验收（1.50 秒），其中 **12 项完全等价、两项明确记录已知差异**：旧静态入口的 InnerFocus/Multiscale 为 200，新静态 Core 为 unsupported 422。因此记 **19 个完整 API + 1 个受限 API**，不称 20 个完整迁移。实际 hp/stat→stage→damage 三批独立 child、不可变配置软删快照、原错误和全部 JSON/null 字段已对照；11 个严格输入子场景 race 与 vet 通过。
- 已推 **4995551** 的 [Main Gate 45380518072](https://github.com/mental1104/PokemonBattleInference/actions/runs/45380518072) **PASS**；[Native 45380518035](https://github.com/mental1104/PokemonBattleInference/actions/runs/45380518035) **FAIL**：macOS Core **58/58 PASS**（6.44 秒）、迁移 pytest **28 PASS / 1 FAIL**，三个 Swift 知识 HTTP fixture 均未就绪且 stderr 为空，SDK/device App/模拟器未执行。产物 **14914260663** ZIP SHA-256 **39e50c2d92e902e060cfbdb1668300a5b13deae6baa7cbc77aba3dda862f9d9e** 已独立匹配，原日志/ZIP 在 `knowledge-ready-20261124/`。Linux 的 ready 窗口不作为本次 Mac 启动失败已证实原因；补丁额外直接选择父测试的真实 Python、去除回环夹具反向 DNS 依赖并记录启动阶段，等待 Apple 实证。修后 Linux Swift **17 PASS / 3 explicit SKIP**（2.270 秒），三个实际更新测试均通过。
- **4a4f0c0** 保存完整推演知识只读端口；七只 Pokémon 的全字段 416,820 字节快照与原 repository 同 PG 差分通过，Go **7/7 race、零跳过**及 vet 通过，详见 `migration-server.md`。新 **b040471** 的 [Main Gate 45382143497](https://github.com/mental1104/PokemonBattleInference/actions/runs/45382143497) **FAIL** 于收集新 calculator 测试：`ModuleNotFoundError: httpx`。原因是 0.28.1 只在工具 Dockerfile 安装，未进入 CI 使用的公共 requirements。已将相同实测版本加入 `requirements.txt`、移除工具层重复来源；从空 venv 仅安装公共依赖后 **624 项测试完整收集成功**（2.66 秒），不是宣称这 624 项已经执行。证据 `main-dependencies-20261124/`，后续由新 Main/Native CI 验证。
- **74c75e1** 的 [Main Gate 45383272271](https://github.com/mental1104/PokemonBattleInference/actions/runs/45383272271) **PASS**，缺失 httpx 修复已由实际 CI 验证。[Native 45383272152](https://github.com/mental1104/PokemonBattleInference/actions/runs/45383272152) **FAIL**：macOS **70/70 CTest PASS**（6.83 秒），HTTP fixture 已正常启动，Swift 三个更新方法中取消/边界通过，首次截断没有实际收到字节，故 Range 续传三条严格断言失败。产物 **14914788001** ZIP SHA-256 **4871c342d90eb03a170c37b333a1931c50c9e6ad485d24a9b8578f8e1e2aae34** 已匹配，证据 `drop-control-20261124/`。**1534d5f** 让测试在观察到真实至少 8192 字节后，经独立 HTTP 控制请求断开 TCP，再验证磁盘前缀/206/重启/旧数据；未改生产下载算法或放宽断言。同时 Makefile 显式传递已经注册的配置 runner，避免其七项纯域差分在统一 Native 入口因缺环境被跳过。
- 四角色验收 `stack-20261124/explicit-network/` **PASS**：原 Vue/Nginx→Go→Core 真实浏览器计算 **114–135**、390px 布局无溢出、13-op 完整向量；Docker STOP 后 unhealthy/CONT 后 healthy；公开 HTTP 配置经两个不同 Go image 回退和 PG dump→独立库恢复后完整 JSON 不变。详细 image/备份摘要及作用边界见 `go-stack-validation.md`。Worker 在栈中启动但本场景没有伪造缺失的任务创建接口；截图暴露的图片缺失与原 BYTEA sprite 初始化明确列入剩余范围。所有自有实例/网络均已精确清理。
- **fc03956**：正式 **0.7.0 / calculation-rules.v7**，统一19操作向量，原13项输入/数学结果不变；新配置stats/moves/space、两模式coverage及严格job_move_pool均通过真实C ABI。最终 **77/77 CTest**（3.20秒）、新增ABI **8/8差分**（5.97秒，含完整44,100身份/关联准入/32MiB分页边界）、Go bridge/process **14项race/vet**；Swift **17 PASS / 3 explicit SKIP**。新ABI、19golden、真实配置运行取消及ownership/concurrent选定 **5/5 ASan/UBSan/leak PASS**（39.62秒），这是新路径选择集，不是77项全量。P1纯域完整58项sanitizer证据另列。报告与20个P2冻结源摘要在 `configuration-abi-20261124/`，九个P1纯源摘要在 `job-move-pool-20261124/`。
- **79c325e**：原四个configuration-jobs查询/取消/results/issues真实同PG差分 **36/36 PASS**（30完整JSON+6 schema状态），支持过滤前分页、last query值、历史非JSON说明、原Python创建而无GoDefinition的任务。API计数 **23/41完整+1受限calculator**。全部Go包 **46 PASS / 1专用Swift服务fixture SKIP**、race/vet通过；另Daemon父取消恢复 **10/10 PASS**（24.198秒），包含root对取消/SQL Commit竞态的明确错误归一。原负cursor导致500按已记录缺陷单独修为422。报告在 `p3-server-20261124/configuration-jobs-final3/`、`configuration-jobs-go-all7/`，早期真实失败均保留。
- **1534d5f** 固定树最终 `make test-native CORE_BUILD_DIR=/build/root-fixture-core6`：**70 CTest、35 pytest PASS / 16 SKIP**（52.71秒），七个已登记配置差分现全部实际执行。跳过是14个未提供独立calculator URL的场景、一个未提供PG快照和一个工具镜像无Swift；独立Swift **17 PASS / 3 SKIP**已实跑，不能把环境缺失称通过。
- 正式任务创建联调修复原受控道具 `item_identifier:"none"`：关联事实为无效果，原 canonical 字符串及其与 null 不同的身份完整保留，不在Go改写。独立新库 `/build/root-job-none7` **77/77 CTest PASS**（1.92秒），正式job ABI **5/5差分 PASS**（3.90秒），新增断言直接对照原case/side SHA身份。首次手动命令漏runner变量导致五项明确SKIP，记录保留；补齐变量后只重跑相关差分得到上述实际PASS，未重复无变化的C++全构建。

## 0.8 检查点与实际在线闭环（2026-11-24 21:00）

- **aa498cb** 的 [Main Gate 45386798790](https://github.com/mental1104/PokemonBattleInference/actions/runs/45386798790) 与 [Native/Core/App 45386798406](https://github.com/mental1104/PokemonBattleInference/actions/runs/45386798406) **均PASS**。Native首次attempt的job尚无steps即被取消；终态后重试的attempt2真实完成。macOS Core、Go/Swift、两SDK及未签名device App通过，iPhone **5/5 UI PASS**（206.387秒）、iPad **5/5 UI PASS**（197.272秒），包含中文查询、严格伤害/麻痹速度、保存重启和设置入口。新增在线任务UI不在该提交内，不能套用此结果。
- 已归档实际attempt2完整日志及 [artifact 14921070881](https://github.com/mental1104/PokemonBattleInference/actions/runs/45386798406/artifacts/14921070881) 到 `apple-abi7-success-20261124/`；ZIP实测SHA-256 **cb886803ab45bf0f6e416e44ce2ab86e55e77f6d9527dc8df6d20f694dbcb69f** 与GitHub digest一致。
- **58d04d7 / 1d73d65**：正式 **0.8.0 / calculation-rules.v8**，登记完整WithSpeed模板目标、EV搜索及纯结果聚合；公共新增 `configuration_templates`、`configuration_spread_search` 使用扁平操作快照。三语言共享冻结向量为25操作：原19项数学输入/输出保持不变，新增3个原模板与3个原EV oracle。目标阈值、严格速度大于、原排序/去重/提前停止及精确概率均由Core执行，不在Go/Swift复制。
- `templates-abi8-20261124/native-spreads.log`：完整 **92/92 CTest PASS**（2.77秒），迁移pytest **52 PASS / 52 SKIP**（65.08秒）。跳过为36个未设置独立任务查询服务URL、14个calculator URL、1个PG快照及工具镜像缺Swift；相应真实服务均另有独立证据，不把SKIP计为通过。`swift-spreads.log`为 **17 PASS / 3无服务URL SKIP**（2.921秒）；`abi-sanitizer.log`的共享25操作、ownership/release、并发及取消选定 **4/4 ASan/UBSan/leak PASS**（20.94秒），不是92项全量ASan。正在修复另外发现的模板/EV运行中取消异常错误映射，不能据通用取消通过宣称这些新路径已完备。
- **427dc15 / bce5d6f / 87c7c28**：真实HTTP任务创建通过strict Core准入，按case保存规范身份，完整战斗模板仅冻结一次，worker每次认领后投影对应招式/slot；不将44,100份完整快照物化进定义。最终原合法7类job preset实测：**44,100 case HTTP202耗时8.536307秒，定义25,824,669字节**，运行中取消及终态守恒已验。原`no_investment`/`max_spatk_*`属于静态calculator而非job preset；任务仍按原202后逐case准备失败，零资源/NULL概率，全部失败头为completed_with_failures，无伪造数值。
- `p3-server-20261124/preparation-final/`：两个真实原/新coordinator、各自新库的准备合同 **16/16 PASS**（10.30秒），14项完整等价、2项原未捕获500修为显式422已记录；旧失败日志保留。全部Go包 **50 PASS / 1专用Swift serve测试SKIP**、race/vet通过。Root nativeworker实际PG/child/daemon **9项加1个投影单测PASS**（4.096秒），另父取消/Commit恢复 **10/10 PASS**。**7354a7f**实际候选API同PG原Python完整字段差分 **13/13 PASS**（1.94秒）。
- **f3d6e98** 新增原生在线任务表单、typed客户端、实际提交/进度/幂等取消/分页结果与来源版本；Mac脚本启动独占本地Go/PG/daemon服务，Swift真实联网后继续iPhone/iPad UI与跨模拟器同步，等待新CI。`p4-jobs-75-legacy7-20261124/`已实测完整Swift **25/25 PASS，零SKIP**（6.330秒）：合法原7类preset单case实际完成2.782秒，win=0/loss=1/draw=0、expected_turns=5/1、841nodes/16095edges；合法5×6招式池产生75case，运行中取消0.541秒后75个均取消并完成计数。旧no_investment成功执行记录不再当成原job兼容证明。
- 21:00仍未达到本轮P1–P3/P5全完成门槛。三条并行任务继续收口事件/反事实、fixed/graph领域投影、solver/search真实HTTP；P4/P6基本链已形成，新增App UI及上述新代码仍须实际CI。总体Goal保持active，原全目标/Human要求不变。

## 下一步

### 0.9公共集成与稳定移动端验收基线（22:00）

22:22终态补充：`.9` selected public ASan/UBSan/leak **6/6 PASS（1512.29秒）**，其中大规模节点配额用例1409.69秒；包含整个33例、256ownership、32并发、两类事件公共入口的真正运行中取消和静态上下文边界。原handle完整结束，未缩短/重启。下文“仍在运行”保留22:00检查点当时状态，以本终态为准。

`efc95d1`保存旧/现代damage HTTP：自有空PG最终 **33/33零SKIP**（4.62秒），现代14个全部完整JSON等价，两特性兼容缺口消失；旧故障入口按历史原构造和原责任链恢复为实际200，随机字段按原支持集核对，不声称逐次随机值一样。`e6a7c95`保存原fixed-job及move-set-combinations，最终 **24/24零SKIP**（23完整对照3.63秒+daemon后终态重提1项1.60秒），真实单case841/16095、0/1/0、期望5/1；未知profile仍原202后异步失败，旧Python先创建无Go definition也可幂等返回/取消。两批race/vet、ruff/strict mypy与bash/diff检查通过；P3现32/41。

下一`.10`使用登记的abi10-verification、Core缓存`root-projection-abi10`；从efc95d1固定基线加入已冻结14个projection/SHA/代表路径源与8个透明UNKNOWN源，未混Go图草稿。正式新kind、36共享样本、32MiB请求边界已在隔离树编译，尚未保存/发布。另已识别第1000层snapshot ID超旧1024十进制位解析上限的真实可能边界，正在原oracle复现修复，不靠第200层通过就宣称所有长路径已支持。

固定 **c0b048e1c49de9483692c77788498267049ac135** 的[Main Gate 45404217710](https://github.com/mental1104/PokemonBattleInference/actions/runs/45404217710)与[Native/App 45404217482](https://github.com/mental1104/PokemonBattleInference/actions/runs/45404217482) **全PASS**：原生Core/Go/Swift、两SDK、未签名device App及iPhone **9/9 UI**（445.511秒）/iPad **9/9 UI**（485.084秒），两端均真实完成任务提交/精确结果/运行中取消、在线离线一致、iPhone上传→iPad拉取与同步重启。此前两处Form结果行定位已由实际UI复验修复，原严格99–117/123/128/85→42断言不变。该提交是可固定的阶段验收基线；真机签名/物理安装仍HUMAN_PENDING。完整日志在`apple-results-c0b048e-20261124/`。

Root在Git登记的`abi9-verification`固定a8806ec基线上整合 **0.9.0 / calculation-rules.v9**，没有混入后续透明假设/graph编辑。新增正式event_analysis/configuration_event_analysis/legacy_damage及damage的显式reference_static context；原25数学样本逐字段不变，8个原Python oracle追加后共享33例。直接伤害默认strict仍拒绝两动态特性，显式静态入口不改能力身份或通过Go清空效果。事件组/普通graph共用批次原拓扑配额，取消撤销整批；反事实测试端口未伪装公开重新推演。

`event-abi9-20261124/`：完整 **111/111 CTest PASS**；迁移pytest **60 PASS / 140明确外部环境SKIP**（114.49秒），其中全部纯Core新旧差分与Go33共享调用实跑。专用Swift先独立 **20 PASS / 5无服务URL SKIP**，随后`swift-live/`真实Swift→Go→PG→daemon/Core **25/25 PASS、零SKIP**（16.613秒），覆盖33共享样本、实际在线/同步与旧任务完成/运行取消。selected public ASan/UBSan/leak仍在运行：完整33例、256次ownership和32并发已PASS，大规模节点配额边界仍活跃（只报告真实进程，未重启/缩小断言）；不能将当前状态称111全ASan。

Release首轮失败是新legacy Exact原地Boost移位在GCC14 -O3触发stringop-overflow，修为有界53位bit_set构造后，同-O3/-Werror的369原oracle通过，重新全量111也通过。首次Swift及Python/Go严格版本断言仍为0.8导致失败，已同步0.9后重验；没有删除/放宽数学和错误断言。三种失败日志全部保留。源码冻结与保留工作区审计见publication-sources.json；后续Core透明/图投影及HTTP草稿不混入本批。

### 21:30后的稳定提交与Apple反馈

`ac206b9`保存原solver/search40/40；`06d471a`保存真实RED→GREEN的模板/EV运行中取消；`d8f6779`保存同一工厂完整capability事实（默认25操作输出不变）；`cfb83fd`保存事件/配置加权/真实双runner反事实纯域；`a8806ec`保存原fixed摘要19/19。Root只保存已冻结文件，P2后续SHA抽取/graph、P1静态damage及P3旧damage未成熟编辑不混入这些提交。

`5dc4dad`的Main Gate **PASS**；[Native/App 45399177231](https://github.com/mental1104/PokemonBattleInference/actions/runs/45399177231) **FAIL**：macOS Core/Go/Swift、两SDK与未签名device App成功，iPhone/iPad各 **8/9 UI PASS**。两端真实任务提交/精确结果/运行中取消、跨模拟器同步和设置重启通过；iPhone在线对照缺two-hit结果元素，iPad离线缺attacker-speed元素，各自另一机型相同数学断言通过。原日志保存`apple-abi8-ui-20261124/`，artifact14924002576约241MB。`250f0b3`逐个滚动显露独立Form懒加载结果行，未改数值断言；Swift parse通过，后续CI复验。

`99c2d12`把事件runner导出到统一Make入口，避免5项真实差分因环境变量缺失而跳过。`3dcb0fc`保存纯Go图片导入、显式只读Compose来源及真实PG/原Python/HTTP验收：完整知识/race/vet通过，五张上游真PNG6/6差分通过；初轮精简镜像MIME缺失已修，Pythonruff/strict mypy、gofmt、bash syntax与Compose config通过。验收五图不能代替全量sprites导入，尚未重跑带图完整Web栈。

`BASE-WEB-001` 已独立修正并通过上述完整 Web 回归：将 Pokémon/招式选择限定在防守目标弹窗，并增加保存按钮可用断言，未改业务代码或删减原断言。

推送已验证的0.8公共能力、真实任务创建与App在线/双模拟器同步批次，执行新Apple CI；修复新搜索运行中取消错误码，继续事件/反事实公共接入、Go solver/fixed/graph及其余API、原BYTEA图片初始化和完整Web回归。P1–P6全部要求和Human双设备验收均仍保留，不能因当前切片通过而标记阶段PASS。

## 恢复提示

最近三个已提交基线检查点：`12d9c10`（P0/合同/隔离环境）、`aef5b9d`（生成 SQL 空白规范化）、`6a94e88`（Web 测试定位修正）。之后的 Core 提交以分支 `git log` 为准。

跨语言检查点：`c42acac`（C ABI/Go/Swift 实际闭环）、`425c9b8`（用户授权 Ready-PR CI）、`738919a`（Apple 交叉编译依赖发现修复；远端完整 CI 全绿）。后续纯记录提交不改变这些已经验证的代码；不为文档状态更新重复运行整套 SDK 构建，下一次代码变更再推送并运行 CI。

先查看顶部最新状态、本轮检查点与 `git status --short`，再核对实际 agent/容器/CI 状态；不要凭历史“已结束”判断当前验证进程。仅对新行为、真实失败或未解决风险追加必要验证，不重复无变化的长 benchmark。root 统一提交和推送，独立 agent 不提交未冻结批。

## NAS部署检查点：备份与PG17接管验证

用户已授权NAS部署及`pokemon.mental1104.xyz`反代，并明确批准现有库备份/恢复验证/保留。`nas-deployment-20261125/database/`保存155MiB现有库的一致性归档及校验，隔离PG17完整恢复成功；181张业务表的行数与完整有序行摘要逐字一致。恢复副本显式Go接管验证177个CSV表、1,051,052行成功，维护实例/网络已回收。无活动客户端后准备受限连接文件，原角色凭据另存私有回退文件；没有改变角色权限/HBA。

完整sprites检出已完成：commit c0542f7c51215d9672439012838c99f520596cbd、树ec56a5fae60f2a6363083d7d0581271744673695、105,947实际文件、目录28,665,709,131字节，Git状态干净。`runtime-full-20261125/full-a3f0ff7/`已启动真正运行Compose全量导入/重启/回退/恢复，尚未终态，不能标PASS。NAS配置复用home/shared PG17，应用三服务、回环41110及版本化知识包；部署与HTTPS仍在准备，详见nas-deployment.md。最新b3b344d的Main Gate45555819043通过，Native45555819025仍在运行，未重启或取消。

NAS实际部署推进：恢复验证通过后，真实PG17原库显式接管成功，源177 CSV共1,051,052行，原181张表完整有序行摘要逐字保留。home只定向启动pokemon-backend/worker/frontend，三个服务restart always，共享PG没有重建。`https://pokemon.mental1104.xyz/`已启用，App地址为同域`/api`。证书链+域名验证0、curl正常TLS、健康及42项Core全响应通过，DSM其他代理规则未变。真实知识包SHA、206 Range64字节及未知版本404通过。版本化包为真实现有数据，不冒充人工新版本更新验收。完整图片仍等待独立运行验证；手机继续不操作。

## NAS HTTPS完整业务与大图库初始化时限

`nas-deployment-20261125/browser-preflight/`通过真实HTTPS执行原Vue完整业务，最终acceptance.json为PASS：114–135完整伤害、390px无溢出、配置增改/重载/删除、preset/spread/混合目标求解与候选保存、221节点576边任务真实完成、running后取消达到cancelled、图ROOT/改选分支与实时快照12事件战报通过，0 JavaScript错误。本轮未启用图片完整性断言，不能冒充完整图库通过。NAS三个应用服务实际重启后健康，完整配置列表逐字一致；没有重启共享PG。其他DSM反代与证书绑定的前后规范化比较均一致。

原完整图库验证`runtime-full-20261125/full-a3f0ff7/`在初始化20分钟截止时真实失败：generation-ix/scarlet-violet/back/59.webp处context deadline exceeded，图片事务回滚；未导入正式NAS图片库。增加显式正值`--timeout`，默认仍20m，仅控制初始化，不改变Core计算资源预算。真实新二进制构建/vet通过；0和-1s返回2，1ns返回context deadline exceeded，2h合法且无DSN时明确拒绝，全部检查退出0。完整重跑将显式选择2h，首次失败不覆盖。

已通过专用、无网络维护服务精确清理该失败验证PGDATA：控制文件实际shut down且无postmaster.pid，源码SHA/超时证据均匹配才清理。释放14,976,337,841字节物理目录，源素材、原库备份和全部失败日志保留，SSD回到94GiB可用。首次维护配置相对挂载解析错误原文保留；改为已登记绝对源码路径后成功。旧Python迁移legacy分支仍独立未集成，577/577原回归和6/6布局/知识包回归已通过，等待替代能力验收后再归并。

最新b3b344d的Main Gate45555819043和Native45555819025全部success，apple-core139007480479所有实际步骤成功。部署配置/初始化CLI后续提交尚待最新CI，不把旧绿灯当作新代码验证。

## 最新范围：HDD正文、全图鉴朱紫优先图标

用户明确批准正文存HDD、PG仅存元数据、URL兼容，且Swift与服务端都要全图鉴；朱紫缺图用其他游戏菜单小图补齐。先前27只范围已撤销，105,947文件/28.7GB全部正文导入也已撤出当前部署范围，不继续把全量源挂入运行服务。

全1,350条记录已找到同ID真实菜单PNG，缺图0。朱紫869，其余Champions140、Z-A88、阿尔宙斯39、BDSP60、剑盾132、第七世代22。另5道具+19朱紫属性，共1,374张20,079,618字节。两端资源逐字节相同，来源和SHA清单完整，未加入动画/大立绘。全量HDD试制快照已移到Backup的full-source-snapshot-not-deployed，应用快照目录不含它；原输入保留。

新Go文件存储代码及r2已通过76 PASS/2专用SKIP、race/vet，恢复10/10。实际PG证明正文NULL、稳定ID、幂等、拒绝隐式回灌BYTEA、DDL及旧正文失败回滚；原三图片URL/ETag、缺失和同长度损坏、朱紫属性优先与剑盾兼容均验证。Python四文件Ruff/strict mypy通过，13测试PASS。SwiftSPM原字节复制后真实1374文件SHA/PNG/尺寸/总量核验2/2，71.96秒；App界面与新11用例待Apple CI。P4旧自动化PASS证据保留，但新图标版本尚未PASS。

新版本真实运行栈、NAS升级及Apple CI仍待；NAS当前a3f0ff7服务健康。详见asset-storage.md。整体95%是原工程估算，不能把新路径实现或资源生成算成已部署/人工验收。

本轮源码检查点：全图鉴新包Ruff/strict mypy及13项Python测试通过，Swift2/2逐项核验1374份PNG通过，Go类型朱紫优先后的r2整入口PASS（76+恢复10，2专用SKIP）。新建图标支持API与实际SwiftUI接入，增加首装宝可梦详情图像断言及道具选择图像用例，Apple实际11项尚待。历史全量/27只记录只表示早期尝试，最新范围以本节和asset-storage.md为准。

## HDD全图鉴正式部署检查点

17a5fdac3567c4da0f855fe69efe29935a5a8087已提交并推送，Main Gate45572741424成功；Apple45572741348仍在App双模拟器步骤，没有因等待而重推或取消。nas-shared通过固定OCI工具链构建server/data/frontend三个p6-sv-filesystem-r1镜像，真实ID见nas-deployment.md。验证和NAS发布工作树均固定该提交，图片快照版本也固定该SHA。

filesystem-assets-20261125/runtime-r1完整入口退出0。PG独立导出1,374条记录，正文非NULL为0，登记20,079,618字节，独立无网络客户端逐个读取HDD正文且全部SHA匹配。严格图片浏览器核对实际PNG/尺寸/ETag并完成原业务、221节点576边任务、运行中取消、分支回访、12事件实时战报，0JS错误。全部角色及PG停止重启后配置/清单保持一致；备份恢复到独立库后配置、图片清单和图片正文相同。真实旧BYTEA-only候选虽健康却返回错误图片，被图片验收拒绝，随后返回已验证HDD版本，未声称旧镜像支持外置正文。

NAS已定向升级三个应用角色，未重启共享PG或调整其他服务/DSM规则。正式原知识/配置保持；全表摘要只改变预期的图片资产、导入批次和两张图片物化视图。原库复用CSV不重新导入，新增1,374图片元数据。正式HDD再次逐文件核验通过；browser-filesystem-r1正常TLS严格图片浏览器PASS。额外独立curl逐个请求全部1,374个公开图片URL，返回SHA/长度与Git清单逐项相同，包括全部1,350条宝可梦记录、5道具和19属性。三个应用真实重启后完整配置JSON及212图片逐字保留；新正式备份已生成。P3达到PASS/100%，P6估算87%→93%，整体95%→96%；新App UI和Human事项仍未算通过。

新正式备份SHA清单通过，recovery-r3隔离PG17完整恢复退出0，全部表完整摘要及1,374条图片元数据逐字相同。前两轮临时恢复分别缺原对象所有者espeon、以及没有复现其源库superuser读表权限而失败；原始日志保留。第三轮仅在无宿主端口的自有tmpfs实例建立NOLOGIN/SUPERUSER所有者角色后成功，未改生产权限。全部自有恢复实例/网络已回收，HDD正文不在PG归档中，Git资源包和固定HDD快照另行保留。

## 完整替代验收后的Python参考归位

在Go/HDD/NAS完整替代验收通过后，将已准备的4265989以2036989纳入迁移分支。Python实体归入legacy/pokeop，根pokeop仅为兼容软链；原业务/测试保留。CSV软链、common根、历史素材根和Docker COPY按真实层级调整，README和项目Skill同步更新；NAS仍运行固定17a5fda镜像，未重新切换生产。

legacy-layout-20261125/integrated-r2实际回归：原Python/自有PG577/577通过（20.17秒），布局/知识包6/6通过（2.35秒），均零SKIP；Ruff/strict mypy通过。首轮因NAS ACL使新测试文件可执行而触发EXE002，按Git原100644权限修正后复验，失败日志保留。make coverage改为legacy实体路径，领域/应用层461项通过（32.10秒），84%覆盖率；未修改阈值或数学断言。

固定.11 Core产物未经重编译/覆盖，通过Makefile正式导出的所有runner再次执行迁移参考测试：126 PASS、247明确外部SKIP，96.06秒。独立Go/Swift原生委托未在此轮重复，相关源码与17a5fda无变化，原实测保留。Python兼容镜像pokemon-python-reference:legacy-2036989由nas-shared完整构建，实际ID sha256:618f72e3c851adea8f29ad507b3ad73f0d8e1ce3bf90dee395ae09a129f34f41，682,614,903字节；无网络/只读/仅挂测试文件且不挂源码，镜像内部3/3布局、静态资源和新解释器common来源测试通过（2.33秒）。声明入口为deploy/compose.legacy-image-validation.yaml，镜像不部署到NAS业务。P6工程估算93%→95%。
