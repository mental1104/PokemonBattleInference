# 架构迁移进度

本文件是长程迁移的恢复入口。目标保持 P0–P6 全部范围；任何 Linux 验证均不能替代 macOS、Xcode 或双设备人工验收。

## 当前状态（2026-11-24）

| 阶段 | 状态 | 当前证据与剩余工作 |
| --- | --- | --- |
| P0 基线 | PASS | `migration-baseline.md`、41 项 HTTP/185 表快照、原测试结果及真实有界 benchmark 已记录；Web 既有一项失败单独登记。 |
| P1 C++ Core | IN_PROGRESS | 已实现现代能力值/性格、能力等级与给定伤害档位 KO，使用任意精度精确分数；其余完整计算与图推演待迁移，macOS 未验证。 |
| P2 跨语言集成 | NOT_STARTED | 统一 C ABI、Go/Swift 调用及 Apple 目标尚待实现与验证。 |
| P3 Go 服务端 | NOT_STARTED | 现有在线运行时仍是 Python；不得切换生产。 |
| P4 iOS/iPadOS | NOT_STARTED | 应用、离线数据、模拟器与真机闭环待实现。 |
| P5 数据同步 | NOT_STARTED | 数据包与用户同步协议待实现。 |
| P6 部署与回归 | NOT_STARTED | 保留旧 Compose、Python、测试和所有数据库。 |

## 已确认的边界与决策

- 分支 `codex/monorepo-migration`；工作树 `/volume2/workflow/code/worktrees/PokemonBattleInference/monorepo-migration`。不合并、不推送、不切换生产。
- 主工作树 Makefile 有用户原有路径修正，未带入或覆盖。迁移工作树从干净的 `10c422e` 开始。
- `common` 与 `pokeapi` 从现有本地 submodule 初始化，分别固定于 `39e85858`、`1567d530`；没有更新上游版本。
- Python 的 `pokeop/` 暂时保留原路径，避免在替代能力验证前破坏导入、CSV symlink、测试或部署；最终迁往 `legacy/`。
- PostgreSQL 测试会删除测试 schema，因此只允许连接本次创建的临时 PostgreSQL；禁止填入生产 URL。验证服务不发布数据库端口。
- NAS 宿主 Python 为 3.8.15，未发现宿主 C++/CMake/Go/Swift；用声明的 `maintenance` 服务执行一次性 Python 3.11/C++ 验证，源码只读、输出路径独立。

## 人工及平台事项

| 项目 | 状态 | 后续操作 |
| --- | --- | --- |
| macOS / Xcode 构建 | HUMAN_PENDING | 当前为 Linux/NAS，无已确认可操作的 Mac；准备跨平台工程后在 Mac 执行实际构建，不能推定通过。 |
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

## 下一步

`BASE-WEB-001` 已独立修正并通过上述完整 Web 回归：将 Pokémon/招式选择限定在防守目标弹窗，并增加保存按钮可用断言，未改业务代码或删减原断言。

优先让首批能力通过版本化 C ABI 被 Go 实际调用，形成可运行的跨语言闭环；并继续迁移完整伤害、规则、速度效果与不可变状态，再接回合/图/SCC/搜索/事件分析。C ABI 需要明确内存、异常、错误码、线程、取消和批量语义；不得将当前测试进程协议冒充正式 ABI。P2–P6 全部要求、macOS/iOS 真实构建和 Human 双设备验收均仍保留；P1 不能因首批通过而标记 PASS。

## 恢复提示

最近三个已提交基线检查点：`12d9c10`（P0/合同/隔离环境）、`aef5b9d`（生成 SQL 空白规范化）、`6a94e88`（Web 测试定位修正）。之后的 Core 提交以分支 `git log` 为准。

先查看本文件和 `core/README.md`，然后 `git status --short`。原完整回归已经通过，不在没有新行为改动或失败的情况下重复执行 6 分钟图 benchmark；下一轮应继续实现缺失能力。当前没有需要观察的遗留计算任务；一次性验证均已结束。
