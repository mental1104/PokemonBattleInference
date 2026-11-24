# 架构迁移进度

本文件是长程迁移的恢复入口。目标保持 P0–P6 全部范围；任何 Linux 验证均不能替代 macOS、Xcode 或双设备人工验收。

## 当前状态（2026-11-24）

| 阶段 | 状态 | 当前证据与剩余工作 |
| --- | --- | --- |
| P0 基线 | PASS | `migration-baseline.md`、41 项 HTTP/185 表快照、原测试结果及真实有界 benchmark 已记录；Web 既有一项失败单独登记。 |
| P1 C++ Core | IN_PROGRESS | 已实现现代能力值/性格、能力等级与给定伤害档位 KO，使用任意精度精确分数；其余完整计算与图推演待迁移，macOS 未验证。 |
| P2 跨语言集成 | IN_PROGRESS | 首批 C ABI/Go/Swift 在 Linux/macOS 实际调用通过；arm64 iPhoneOS/Simulator 静态库、Swift 模块及 XCFramework 已由 CI 构建并核验。完整 Core 能力仍待迁移和接入。 |
| P3 Go 服务端 | IN_PROGRESS | 新 Core HTTP 入口已实际验收；41 项旧 API、Worker、PostgreSQL 尚未迁移，生产仍为 Python。 |
| P4 iOS/iPadOS | NOT_STARTED | 应用、离线数据、模拟器与真机闭环待实现。 |
| P5 数据同步 | NOT_STARTED | 数据包与用户同步协议待实现。 |
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

## 下一步

`BASE-WEB-001` 已独立修正并通过上述完整 Web 回归：将 Pokémon/招式选择限定在防守目标弹窗，并增加保存按钮可用断言，未改业务代码或删减原断言。

Apple CI 已实际通过，下一轮继续迁移完整伤害、规则、速度效果与不可变状态，再接回合/图/SCC/搜索/事件分析，并复用已接通的 C ABI/双语言入口扩大闭环。P2–P6 全部要求和 Human 双设备验收均仍保留；P1/P2 不能因首批通过而标记 PASS。

## 恢复提示

最近三个已提交基线检查点：`12d9c10`（P0/合同/隔离环境）、`aef5b9d`（生成 SQL 空白规范化）、`6a94e88`（Web 测试定位修正）。之后的 Core 提交以分支 `git log` 为准。

跨语言检查点：`c42acac`（C ABI/Go/Swift 实际闭环）、`425c9b8`（用户授权 Ready-PR CI）、`738919a`（Apple 交叉编译依赖发现修复；远端完整 CI 全绿）。后续纯记录提交不改变这些已经验证的代码；不为文档状态更新重复运行整套 SDK 构建，下一次代码变更再推送并运行 CI。

先查看本文件和 `core/README.md`，然后 `git status --short`。原完整回归已经通过，不在没有新行为改动或失败的情况下重复执行 6 分钟图 benchmark；下一轮应继续实现缺失能力。当前没有需要观察的遗留计算任务；一次性验证均已结束。
