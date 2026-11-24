# P0：Python/Vue 行为基线与迁移映射

参考提交：`10c422e`。本阶段只记录和复现现有行为；既有缺陷的修正单独提交，不将绿色构建等同于完整迁移。

## 冻结合同

`contracts/reference/` 由 `tools/migration/capture_baseline.py` 在不连接数据库、不运行 FastAPI lifespan 的情况下导出：

- `legacy-openapi.v1.json`：41 个 HTTP 操作的请求、响应、状态码与 schema。
- `legacy-routes.v1.tsv`：可逐项核对的 method/path/operationId 清单。另保留 `/healthz`、静态资源、Swagger 文档及异常响应；这些非 OpenAPI 路径继续由 `pokeop/main.py` 和 API 测试负责。
- `legacy-schema.v1.sql`：179 张原始知识表和 6 张业务运行表的表、约束与索引参考。它是生成快照，**不是升级脚本，不应执行**。
- `SHA256SUMS`：快照校验值。物化视图继续以 `pokeop/persistence/views/sql/poke_champion/*.sql` 的 8 个 SQL 文件为权威来源，不能用表 DDL 快照替代。

当前 `common` 固定于 `39e85858e7b1cefe0a5916b01b6bbf5a59f6d0a1`，`pokeapi` 固定于 `1567d53073a069b6c96e1c393c5c490f602e3ab5`。迁移没有更新 submodule。`pokeop/assets_data` 是指向 PokeAPI CSV 的相对软链，目录调整时必须维持数据来源。

## 功能与模块归属

| 已有功能 / 权威来源 | 目标归属 | 迁移必须保留的行为与现有验证 |
| --- | --- | --- |
| 能力公式、等级修正：`domain/battle/stats.py`、`stat_stage_math.py` | `core/` | HP/非 HP floor 顺序、EV/IV/性格、-6…6 等级与至少 1；`tests/domain/battle/test_stats.py`、`test_stat_stage_math.py`。 |
| 速度目标与行动顺序：`application/use_cases/configuration_speed_goals.py`、`domain/battle/move_execution.py`、`status/modifiers.py` | 数值与比较到 `core/`，输入知识装配到 `server/`、`ios/` | 严格大于/小于、同速分支、招式优先级、麻痹代际差异和 effect 排序；现有 speed、action policy、status tests。不能把初版 `_effective_speed` 当作全部速度机制。 |
| 伤害/KO：`domain/battle/damage.py`、`modifiers.py`、`ko.py`、`rulesets/` | `core/` | 16 档随机值及重复槽位权重；天气/场地/屏障/会心/范围/守住/道具/特性与修正顺序；代际身份及不支持规则显式失败；`test_damage*`、`test_ko.py`。 |
| 战斗状态、StateKey、行动、PP：`domain/battle/state.py`、`specs.py`、`actions.py`、`move_slots.py` | `core/` | 不可变值、规范化身份、招式槽与 PP、终局判断；`test_battle_state.py`、`test_legal_actions.py`、`test_inference_outcome.py`。 |
| 效果与回合：`domain/battle/effects/`、`turn_phases.py`、`structured_turn_resolver.py`、`status/` | `core/`；静态机制知识经快照注入 | 阶段顺序、守卫、组合、状态清理、Fake Out、Struggle、免疫、未支持机制准入；effect/turn/status/grounding tests。 |
| 概率转移：`domain/battle/transitions.py`、`battle_events.py` | `core/` | `Fraction`、分布总质量、等价 StateKey 合并、联合行动与替代事件路径的条件概率；transition/event tests。不得把等价状态事件直接相加后丢失条件权重。 |
| 图构建、摘要图、SCC 与求解：`application/solver/` | `core/` | 节点/边/回合上限、frontier/截断与未知质量、闭环 SCC、无穷期望、精确线性方程、摘要图与完整图一致；solver tests。 |
| 配置空间：`application/configuration_space/`、`use_cases/stream_configuration_pairs/`、`search_configuration_spreads*` | 枚举/计算到 `core/`；调度/分页到 `server/` | 招式排列不影响集合、C(n,min(4,n))、全空间权重、部分覆盖不归一化、预算/准入、速度与伤害混合约束；configuration_space/use_cases tests。 |
| 事件分析与探索：`application/event_analysis/`、`state_graph_exploration.py`、`winning_paths.py` | 图计算到 `core/`；图缓存/导航会话到 `server/` | 首次发生、次数分布、条件质量为零时显式未定义、counterfactual 边界、前进/回退/分组；event_analysis、exploration、winning_paths tests。 |
| 图鉴、招式、属性相克、合法特性和道具：`domain/knowledge/`、`persistence/calculator/`、`persistence/battle_inference/` | `data/` 快照、`server/` 查询、`ios/` SQLite；`core/` 只接收值/知识接口 | 中文、分页/筛选、版本组、招式和特性覆盖合同、物化视图映射；knowledge/repository/calculator API tests。 |
| 能力配置：`domain/stat_configurations*`、`application/use_cases/stat_configurations.py`、`persistence/stat_configurations/` | `server/` PostgreSQL + `ios/` 独立用户 SQLite | 稳定 ID、tenant、预设/自定义/专属绑定、隐藏、排序、软删除；stat_configuration tests。现有模型没有 revision/change-log，P5 需非破坏性新增。 |
| 后台任务：`application/repositories/battle_inference_jobs.py`、`use_cases/_battle_inference_jobs/`、`_battle_inference_worker/`、`workers/` | `server/` Go Worker + PostgreSQL；计算调用 `core/` | 幂等提交、冻结执行规格、calculation revision、lease/heartbeat、并发领取、崩溃恢复、取消、进度、issue/结果分页、完整图按需重算；job/worker/API tests 和 6 项真实 PostgreSQL tests。 |
| HTTP：`pokeop/api/`、`pokeop/main.py` | `server/`，对外合同在 `contracts/` | 保留 OpenAPI 41 项以及 health/static/docs；租户 header 由可信入口提供。HTTP 展示小数不能反向替代 Core 精确概率。 |
| Vue：`web/` | 保留 `web/` | 搜索、计算、反推、任务、图探索、报告、最近使用、配置编辑；31 个 Vitest 文件及生产 build。继续使用同源 `/api` 代理，迁移 HTTP 时不得自行改路径。 |
| CSV/模型生成/导入：`tool/`、`scripts/`、`models_pokeapi.py`、`persistence/importers/` | `tools/` Python、`data/` SQL/离线包 | 原始数据和许可保留；默认不执行 reset；导入幂等、资产解析、只读图片来源、物化视图。模型生成代码不手工改。 |
| 部署：`docker-compose.yaml`、`Dockerfile.backend`、`web/Dockerfile`、`INSTALLROOT/` | `deploy/`，完成替代后再改变在线镜像 | 保留 frontend/backend/worker/postgres/db-init 职责与原卷；常规 down 不删数据；生产切换、备份确认、最终合并由 Human 授权。 |
| 参考实现与测试：`pokeop/`、`tests/` | 验证替代后到 `legacy/`；共享向量在 `tests/vectors/` | 保留原断言和 Python 参考，不能通过移除失败用例获得 PASS。现有 GitHub Actions 只读审查，P6 才更新。 |

以上 `domain/`、`application/`、`persistence/` 路径均相对 `pokeop/`。没有现在就移动目录：最终清理依赖替代能力验证，机械移动会破坏既有导入、构建和数据软链。

## 运行基线与已知问题

原始报告根：`/volume1/homes/mental1104/Backup/PokemonBattleInference/migration-20261124/`。

| 验证 | 结果 | 范围与限制 |
| --- | --- | --- |
| Python 3.11 原测试 | 565 项通过；首次 6 项集成因临时 DNS 配置错误未执行 | 原始 `python-baseline.log` / XML 保留。数据库修正后的独立重跑见下一行，不能把初次失败掩盖为通过。 |
| PostgreSQL 16 原集成 | 6 passed，5.81 秒 | `postgres-baseline.log` / XML；隔离的临时数据库，覆盖 44,100 case 元数据、竞争领取、幂等结果、租约/协调恢复与取消。未连接生产库。 |
| Vue 全集 | 94 passed / 1 failed，31 文件，9.85 秒 | Linux Node 22 容器稳定重现；失败 `ConfigurationSolverView goal detail dialog > opens the compact row…`。 |
| Vue 生产构建 | PASS | 类型检查与 Vite 构建通过，101 modules；不能替代真实 Web 对 Go 的网络验收。 |
| 原配置图 benchmark | PASS（有限样本基线） | `budget-stop-10x10`、workers 1/2、各 2 对；270.777 / 140.881 秒，一致性 PASS。每种模式均 2 truncated / 0 failed，930 nodes / 1,536 edges。原每对 500 nodes/2,000 edges/8 turns 上限；非 44,100 对完整性能结果。 |

已知问题与处理边界：

1. **BASE-WEB-001（测试定位缺陷）**：失败用例从整个页面查找 `choose-target-pokemon`，选中了左侧主体选择器，防守目标草稿仍为空；首个用例已正确限定 dialog。修复时应限定到当前目标弹窗，保留全部编辑隔离和结果断言，不改页面业务来迎合错误定位。
2. **BASE-ENV-001**：NAS 宿主 Node 22.22.3 跑 Vitest 时出现段错误。首次日志保留；相同锁文件在 Debian Node 22 容器中完整跑完并稳定重现上述一项失败。尚未确定宿主段错误根因。
3. **BASE-ENV-002（已纠正）**：`compose run` 默认不注册服务 DNS alias。首次临时 DB 无法按 service name 找到；改用本次明确的 container name 后六项真实集成全部通过。验证脚本应为每次执行创建并连接自己的唯一名称，退出清理自有实例。
4. **BASE-DOC-001**：README 描述顶层 `pokeapi-sprites` submodule，但当前 `.gitmodules` 与 Git submodule 状态仅登记 common/pokeapi；原 Compose 仍有顶层/嵌套只读来源兼容。后续资产打包和部署须明确实际数据来源，不能声称顶层已就绪。
5. 原 KO 展示结果为 `float`，其他推演概率为 `Fraction`。新 Core 的概率统一精确；既有 HTTP 展示字段在边界转换，同时保存精确值，不将这一差异称为原推演算法缺陷。
6. 当前能力配置只有软删除及时间戳，没有双设备同步 revision、队列、change-log 或冲突副本。它是 P5 的新增需求，不能用当前 CRUD 冒充同步完成。
7. **BASE-EXPLANATION-001（2026-11-24 新增实证，独立修复）**：原 `application/solver/graph_explanation.py` 在读取合法 MOVE_USED 路径时引用未导入的 BattleSide，实际抛 NameError。原 worker 的 `_explanation_json` 捕获该异常，因此通常成功战斗原先实际保存 explanation_json=None，并没有可用的根行动归因。RED 保留于 `root-action-explanation-20261124/differential.log`（两项原差分都在原函数失败，未将 C++ 输出冒称通过）。独立补回唯一缺失 import 后，才用该修复后的原函数验证新 Core opt-in；不把该增强冒称未修参考的原有成功行为。原文件一行导入及本说明由主 agent 单独提交，与 Core 迁移实现分开。

原 benchmark 的 JSON/Markdown 保留于 `docs/benchmarks/`。只读容器未挂载外部 Git 元数据，所以原报告 `environment.commit` 为 `unknown`；对应 `pokeop/` 已核对与 `10c422e` 无内容差异。该报告不含 PostgreSQL 写入测量，不能从两个截断配置推断全空间吞吐或原生改写收益。

## 重新执行

本地先初始化固定 submodule，准备 Python 3.11+ 与 `requirements.txt`、当前 `Dockerfile.backend` 中列出的 common 可选依赖和 `httpx`。原始 Python 基线：

```sh
PYTHONPATH=submodules/common/python:. python -m pytest tests --ignore=tests/migration
cd web
npm ci
npm test -- --maxWorkers=2 --minWorkers=1
npm run build
```

集成环境合同沿用 `POKEOP_TEST_POSTGRES_URL`；该 URL 必须指向专用测试库，测试会删除测试 schema。macOS 未提供时按既有 fixture 明确跳过，Linux 可 provision 自有 Docker；显式但无效的 URL 必须失败。

合同重新导出：

```sh
PYTHONPATH=submodules/common/python:. python tools/migration/capture_baseline.py --output-dir /tmp/pbi-baseline
```

复现原 benchmark：

```sh
python -m pokeop.benchmarks.configuration_space --workload budget-stop-10x10 --workers 1,2 --max-pairs 2 --progress-every 1 --output-dir /tmp/pbi-legacy-benchmark
```

NAS 使用声明的 maintenance 服务及独立报告目录，详见 `migration-progress.md`。不调用旧 Compose 的 `compose-up`、`compose-init`、`compose-reset`，避免初始化或重置既有业务库。
