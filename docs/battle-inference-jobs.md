# 战斗推演后台任务

## 进程边界

- FastAPI 只校验并创建任务、轮询进度、分页读取摘要、请求取消和按需重算单配置完整图。
- `python -m pokeop.workers.battle_inference` 启动独立 coordinator。
- coordinator 在父进程读取 PostgreSQL、准备不可变配置并统一写入结果。
- `ProcessPoolExecutor` 子进程只构建并求解单个配置对，返回不含完整状态图的摘要。
- 批量任务不会把完整状态图写入 PostgreSQL；用户查看某个成功配置时，API 才复用现有 `BattleGraphStore` 重算并保存短生命周期图。

本地 Compose 默认启动一个 `worker` 服务。需要多个 coordinator 时使用：

```bash
docker compose up --scale worker=2
```

每个任务的 `process_count`、`queue_depth`、单配置节点/边/回合上限由创建请求冻结。worker 进程级租约参数可通过以下环境变量调整：

- `POKEOP_WORKER_LEASE_SECONDS`
- `POKEOP_WORKER_HEARTBEAT_SECONDS`
- `POKEOP_WORKER_CANCELLATION_GRACE_SECONDS`
- `POKEOP_WORKER_ACTIVE_POLL_SECONDS`
- `POKEOP_WORKER_IDLE_POLL_SECONDS`

## HTTP 生命周期

统一前缀为 `/v1/inference`：

- `POST /configuration-jobs`：严格准入并返回 `202 Accepted`；网络重试可携带 `Idempotency-Key`，相同键与相同完整输入复用同一任务。
- `GET /configuration-jobs/{job_id}`：轮询数量进度与累计节点/边。
- `GET /configuration-jobs/{job_id}/results`：分页读取全部轻量结果。
- `GET /configuration-jobs/{job_id}/issues`：分页读取失败和截断诊断。
- `POST /configuration-jobs/{job_id}/cancel`：停止领取新配置并请求取消。
- `POST /configuration-jobs/{job_id}/configurations/{configuration_id}/graph`：为一个成功配置按需重算完整图。

运行时表位于 PostgreSQL `poke_runtime` schema。升级后需要执行现有数据库初始化流程，以创建 `battle_inference_job_execution_specs`。

## 当前边界

- v1 worker 接受 #82 的固定 Pokémon、等级、能力配置、特性、道具和候选技能池；显式 `form_id` 会在创建阶段返回 422，避免任务入队后逐项失败。
- 任务结果只保存精确概率、期望回合语义、节点/边数量和稳定诊断，不保存完整图。
- coordinator 失去 lease 后无权写入任务级失败；新的 coordinator 通过 PostgreSQL 行锁和过期 lease 恢复未完成配置。
