# Configuration Space Benchmark (configuration-space-v1)

## Environment

- Commit: `unknown`
- Python: `3.11.17 (main, Oct  6 2026, 02:02:21) [GCC 14.2.0]`
- Platform: `Linux-5.10.55+-x86_64-with-glibc2.41`
- CPU count: `8`
- Memory bytes: `24790577152`

## Runs

| Workload | Workers | Coverage | Wall(s) | Pair/s | Speedup | P95(s) | RSS | Nodes | Edges | Merge | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| budget-stop-10x10 | 1 | 2/44100 | 270.777 | 0.01 | 1.00x | 136.200699 | 57196544 | 930 | 1536 | 0.00% | 0/2/0 |
| budget-stop-10x10 | 2 | 2/44100 | 140.881 | 0.01 | 1.92x | 140.863862 | 57503744 | 930 | 1536 | 0.00% | 0/2/0 |

## Consistency

- `budget-stop-10x10` 1 vs 2: `PASS`

## Language Decision

- Decision: `insufficient-evidence`
- Evidence: 尚未在当前机器完整覆盖 44,100 配置对，不能据此冻结原生语言改写结论。

## Notes

- `postgres_write_seconds` 在本 direct-solver benchmark 中为 null；需要通过现有持久化 worker 另跑数据库路径，报告不会伪造写库占比。
- `completed_pair_ids` 支持中断后通过 `--resume-from` 跳过已完成配置；报告只保存轻量摘要，不保存 graph artifact。
