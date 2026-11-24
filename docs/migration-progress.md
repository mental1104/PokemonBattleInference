# 架构迁移进度

本文件是长程迁移的恢复入口。目标保持 P0–P6 全部范围；任何 Linux 验证均不能替代 macOS、Xcode 或双设备人工验收。

## 当前状态（2026-11-24）

| 阶段 | 状态 | 当前证据与剩余工作 |
| --- | --- | --- |
| P0 基线 | PASS | `migration-baseline.md`、41 项 HTTP/185 表快照、原测试结果及真实有界 benchmark 已记录；Web 既有一项失败单独登记。 |
| P1 C++ Core | IN_PROGRESS | 能力值/直接伤害/精确 KO、不可变状态/StateKey/PP/锁招及独立状态修正已通过 Linux/macOS/Apple SDK；新增完整性格 profile 已通过 Linux 差分。完整回合/动态效果/图推演仍待迁移。 |
| P2 跨语言集成 | IN_PROGRESS | 首批 C ABI/Go/Swift 在 Linux/macOS 实际调用通过；arm64 iPhoneOS/Simulator 静态库、Swift 模块及 XCFramework 已由 CI 构建并核验。完整 Core 能力仍待迁移和接入。 |
| P3 Go 服务端 | IN_PROGRESS | 原 19/41 API、原物化视图、任务仓库和独立原生子进程已真实 PG/HTTP 验证；完整推演/coordinator 和其余 API 继续迁移，生产仍为 Python。 |
| P4 iOS/iPadOS | IN_PROGRESS | 首批未签名 device App 构建成功，iPhone 中文查询通过；其余 UI 测试存在首轮失败，已修后待重跑。新增同步界面仍待 Apple 实测，真机未验收。 |
| P5 数据同步 | IN_PROGRESS | 版本化知识 SQLite 与失败恢复已有真实验证；独立用户库/本地队列已实测，PG/双设备同步仍在开发，尚未验证收敛。 |
| P6 部署与回归 | IN_PROGRESS | 已加入统一原生测试入口与隔离验证；用户已授权 GitHub macOS/iOS CI。旧部署/数据库保持原状，未切换生产。 |

## 已确认的边界与决策

- 分支 `codex/monorepo-migration`；工作树 `/volume2/workflow/code/worktrees/PokemonBattleInference/monorepo-migration`。不合并、不切换生产。2026-11-24 用户明确要求“先拿 github CI 测”，已授权推送本分支并开 Ready PR 以运行 CI；不启用自动合并。
- 主工作树 Makefile 有用户原有路径修正，未带入或覆盖。迁移工作树从干净的 `10c422e` 开始。
- `common` 与 `pokeapi` 从现有本地 submodule 初始化，分别固定于 `39e85858`、`1567d530`；没有更新上游版本。
- Python 的 `pokeop/` 暂时保留原路径，避免在替代能力验证前破坏导入、CSV symlink、测试或部署；最终迁往 `legacy/`。
- PostgreSQL 测试会删除测试 schema，因此只允许连接本次创建的临时 PostgreSQL；禁止填入生产 URL。验证服务不发布数据库端口。
- NAS 宿主 Python 为 3.8.15，未发现宿主 C++/CMake/Go/Swift；用声明的 `maintenance` 服务执行一次性 Python 3.11/C++ 验证，源码只读、输出路径独立。

## 人工及平台事项

| 项目 | 状态 | 后续操作 |
| --- | --- | --- |
| macOS / Xcode 构建 | PASS | GitHub macOS 15 arm64 / Xcode 16.4 已实测通过首批原生测试和 Apple SDK 构建；不代表 SwiftUI App、模拟器运行或真机验收。 |
| Apple 登录、Team、签名 | HUMAN_PENDING | Human 在 Xcode 登录 Apple Account、选择 Signing Team；不购买资格。 |
| iPhone/iPad 安装及验收 | HUMAN_PENDING | 工程可构建后，由 Human 连接设备、信任、启用 Developer Mode 并按固定向量验收。 |
| HomeLab 生产切换、正式备份、最终合并 | HUMAN_PENDING | 只在替代能力完成验证并获得明确授权后执行。 |

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
- **8049ddc**：图/合法行动正式 C ABI 及 Go/Swift 冻结向量已扩展至十一操作，引擎 **0.5.0 / calculation-rules.v5**，ABI/schema 仍 v1。纯域新增结构化事件/条件权重、分支合并与注入回合转移器的不可变 BFS 图构建；完整旧回合器尚未迁完，不以自定义回调测试代替。新域/runner **14/14 CTest**、图与 builder **5/5 Python 差分**（1.41 秒，新增 106 组），新纯域 ASan/UBSan/leak **32/32 PASS**（1.58 秒）。P2 图 ABI 另有 50 拓扑、行动 ABI 256 情况的精确差分；全量 CTest **46/46 PASS**。新正式 ABI 的全量 sanitizer 原进程仍运行，未记为 PASS。
- **f04a552**：新增旧通用任务列表/详情/幂等取消，进度 **19/41**；真实 PG 仓库验证稳定 fingerprint/重复提交、租约/心跳/过期恢复、进度守恒、取消和结果分页。独立重建 .5 Core 后 CTest **46/46**，Go 所有包 **18 PASS / 1 专用 Swift 服务 fixture SKIP**、race/vet 通过，外部 curl 六条 HTTP 200；测试实例已清理。证据 `p3-server-20261124/jobs-final/`。任务创建/复杂推演/完整 coordinator 仍未完成，原生 CSV 初始化正在另批开发，未纳入该检查点。
- **e248d3b**：计算通过一个 actor 调用读取宝可梦/招式/性格/属性表及 manifest 的不可变快照，避免知识安装插入多次 await 导致混用版本。两个真实 SQLite 包、16 次安装和 64 次读取竞争，所有输入字段与版本保持整版一致，旧快照不变。实际 Swift→Go HTTP 完整 .5 请求/响应仍一致，整包 **17 tests / 1 skipped**（仅未配置 P5 专用服务 URL），零失败（2.721 秒）；证据 `migration-p2-snapshot-online-20261124/`。

## 下一步

`BASE-WEB-001` 已独立修正并通过上述完整 Web 回归：将 Pokémon/招式选择限定在防守目标弹窗，并增加保存按钮可用断言，未改业务代码或删减原断言。

统一提交已验证 Core/离线知识/AppSupport 与 SwiftUI 工程，执行实际 iPhone/iPad App CI，并处理真实编译/运行反馈；继续完整合法行动、回合/动态效果/图/SCC/搜索/事件分析及 Go API/Worker 和同步迁移。P2–P6 全部要求和 Human 双设备验收均仍保留；P1/P2 不能因当前切片通过而标记 PASS。

## 恢复提示

最近三个已提交基线检查点：`12d9c10`（P0/合同/隔离环境）、`aef5b9d`（生成 SQL 空白规范化）、`6a94e88`（Web 测试定位修正）。之后的 Core 提交以分支 `git log` 为准。

跨语言检查点：`c42acac`（C ABI/Go/Swift 实际闭环）、`425c9b8`（用户授权 Ready-PR CI）、`738919a`（Apple 交叉编译依赖发现修复；远端完整 CI 全绿）。后续纯记录提交不改变这些已经验证的代码；不为文档状态更新重复运行整套 SDK 构建，下一次代码变更再推送并运行 CI。

先查看本文件和 `core/README.md`，然后 `git status --short`。原完整回归已经通过，不在没有新行为改动或失败的情况下重复执行 6 分钟图 benchmark；下一轮应继续实现缺失能力。当前没有需要观察的遗留计算任务；一次性验证均已结束。
