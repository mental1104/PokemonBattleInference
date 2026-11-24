# 架构迁移进度

本文件是长程迁移的恢复入口。目标保持 P0–P6 全部范围；任何 Linux 验证均不能替代 macOS、Xcode 或双设备人工验收。

## 当前状态（2026-11-24）

| 阶段 | 状态 | 当前证据与剩余工作 |
| --- | --- | --- |
| P0 基线 | PASS | `migration-baseline.md`、41 项 HTTP/185 表快照、原测试结果及真实有界 benchmark 已记录；Web 既有一项失败单独登记。 |
| P1 C++ Core | NOT_STARTED | 尚无 C++ 替代能力。 |
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

## 下一步

先单独修正 `BASE-WEB-001` 的错误测试选择范围，保持业务和全部断言；随后提交已初步验证的 C++ 能力值/等级/KO 切片、共享差分和统一测试入口。P1 后续仍包括完整伤害/规则/状态/效果/回合/图/SCC/搜索/事件分析，不可因首批通过而标记 P1 PASS。
