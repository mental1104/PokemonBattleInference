"""运行二十招式池与最多 44,100 配置对的版本化精确求解基准。"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

from pokeop.benchmarks.fixtures import WORKLOADS, iter_benchmark_cases, workload_by_id
from pokeop.benchmarks.models import (
    DEFAULT_PROGRESS_EVERY,
    DEFAULT_SMOKE_PAIR_LIMIT,
    FIXTURE_VERSION,
    BenchmarkLimits,
    BenchmarkReport,
    BenchmarkRunSummary,
    BenchmarkWorkloadSpec,
)
from pokeop.benchmarks.reporting import load_resume_pair_ids, write_report
from pokeop.benchmarks.runner import run_benchmark_suite


def main(argv: Sequence[str] | None = None) -> int:
    """解析 CLI 参数、运行基准并写出 JSON/Markdown 结果。

    Args:
        argv: 可选命令行参数序列；None 时读取当前进程 sys.argv。

    Returns:
        全部跨 worker 一致性检查通过时返回 0，否则返回 2。

    Side Effects:
        启动当前进程或子进程计算，并在指定目录原子写入两类报告。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workload",
        action="append",
        choices=("all", *(value.workload_id for value in WORKLOADS)),
        default=[],
        help="可重复指定；默认执行 attack-10x10。",
    )
    parser.add_argument(
        "--workers",
        default=f"1,{min(4, os.cpu_count() or 1)}",
        help="逗号分隔的进程数，例如 1,4。",
    )
    parser.add_argument(
        "--max-pairs",
        type=int,
        default=DEFAULT_SMOKE_PAIR_LIMIT,
        help="默认只跑 100 对；使用 --full 执行完整 workload。",
    )
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--cumulative-node-limit", type=int)
    parser.add_argument("--cumulative-edge-limit", type=int)
    parser.add_argument("--max-failures", type=int)
    parser.add_argument("--progress-every", type=int, default=DEFAULT_PROGRESS_EVERY)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("build/benchmarks"))
    args = parser.parse_args(argv)

    selected_ids = args.workload or ["attack-10x10"]
    selected = (
        WORKLOADS
        if "all" in selected_ids
        else tuple(workload_by_id(value) for value in selected_ids)
    )
    worker_counts = tuple(int(value) for value in args.workers.split(",") if value)
    resume_ids = (
        load_resume_pair_ids(args.resume_from)
        if args.resume_from is not None
        else frozenset()
    )
    report = run_benchmark_suite(
        selected,
        worker_counts=worker_counts,
        limits=BenchmarkLimits(
            max_pairs=None if args.full else args.max_pairs,
            cumulative_node_limit=args.cumulative_node_limit,
            cumulative_edge_limit=args.cumulative_edge_limit,
            max_failures=args.max_failures,
            progress_every=args.progress_every,
        ),
        profile_serial=args.profile,
        resume_pair_ids=resume_ids,
    )
    json_path, markdown_path = write_report(report, args.output_dir)
    print(json_path)
    print(markdown_path)
    return 0 if all(check.consistent for check in report.consistency_checks) else 2


__all__ = [
    "FIXTURE_VERSION",
    "WORKLOADS",
    "BenchmarkLimits",
    "BenchmarkReport",
    "BenchmarkRunSummary",
    "BenchmarkWorkloadSpec",
    "iter_benchmark_cases",
    "load_resume_pair_ids",
    "run_benchmark_suite",
    "workload_by_id",
    "write_report",
]


if __name__ == "__main__":
    raise SystemExit(main())
