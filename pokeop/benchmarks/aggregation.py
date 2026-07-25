"""聚合基准样本，并校准预算、加速比和语言路线结论。"""

from __future__ import annotations

import cProfile
import io
import os
import platform
import pstats
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from fractions import Fraction
from itertools import combinations
from math import ceil

from pokeop.benchmarks.execution import _fraction_text, _peak_rss_bytes
from pokeop.benchmarks.models import (
    BenchmarkBudgetRecommendation,
    BenchmarkConsistencyCheck,
    BenchmarkEnvironment,
    BenchmarkLimits,
    BenchmarkPairSample,
    BenchmarkProgressPoint,
    BenchmarkRunSummary,
    BenchmarkWorkloadSpec,
)


@dataclass(slots=True)
class _RunAccumulator:
    """流式聚合轻量样本，避免在父进程保存任何完整状态图。

    Args:
        total_pair_count: workload 完整配置空间大小，用作精确权重分母。
        progress_target_count: 本次计划执行数量，用于确保 smoke 末尾也采样进度。
        progress_every: 每完成多少个配置对采样一次累计曲线。
        started_at: 当前 run 的 perf_counter 起点。

    其余字段均是父进程内部可变累计值，不作为跨层公共合同。
    """

    total_pair_count: int
    progress_target_count: int
    progress_every: int
    started_at: float
    processed_pair_count: int = 0
    succeeded_count: int = 0
    truncated_count: int = 0
    failed_count: int = 0
    cumulative_node_count: int = 0
    cumulative_edge_count: int = 0
    raw_transition_count: int = 0
    merged_transition_count: int = 0
    scc_count: int = 0
    max_scc_size: int = 0
    max_turn_number: int = 0
    max_numerator_bits: int = 0
    max_denominator_bits: int = 0
    fraction_aggregation_seconds: float = 0.0
    input_serialization_seconds: float = 0.0
    output_serialization_seconds: float = 0.0
    serialized_input_bytes: int = 0
    serialized_output_bytes: int = 0
    peak_rss_bytes: int = 0
    worker_cpu_seconds: float = 0.0
    progress_update_seconds: float = 0.0
    process_ids: set[int] = field(default_factory=set)
    latencies: list[float] = field(default_factory=list)
    node_counts: list[int] = field(default_factory=list)
    edge_counts: list[int] = field(default_factory=list)
    completed_pair_ids: list[str] = field(default_factory=list)
    probability_records: list[str] = field(default_factory=list)
    progress_curve: list[BenchmarkProgressPoint] = field(default_factory=list)
    weighted_win: Fraction = Fraction(0)
    weighted_loss: Fraction = Fraction(0)
    weighted_draw: Fraction = Fraction(0)

    def add(self, sample: BenchmarkPairSample) -> None:
        """消费一个轻量样本，并更新概率、图规模、序列化和 RSS 指标。

        Args:
            sample: 单配置执行返回的轻量样本，不得持有完整状态图。

        Side Effects:
            原地更新计数、精确概率、分位数输入、进程集合和进度曲线。
        """
        self.processed_pair_count += 1
        self.completed_pair_ids.append(sample.pair_id)
        self.latencies.append(sample.wall_seconds)
        self.node_counts.append(sample.node_count)
        self.edge_counts.append(sample.edge_count)
        self.cumulative_node_count += sample.node_count
        self.cumulative_edge_count += sample.edge_count
        self.raw_transition_count += sample.raw_transition_count
        self.merged_transition_count += sample.merged_transition_count
        self.scc_count += sample.scc_count
        self.max_scc_size = max(self.max_scc_size, sample.max_scc_size)
        self.max_turn_number = max(self.max_turn_number, sample.max_turn_number)
        self.max_numerator_bits = max(self.max_numerator_bits, sample.numerator_bits)
        self.max_denominator_bits = max(self.max_denominator_bits, sample.denominator_bits)
        self.input_serialization_seconds += sample.input_serialization_seconds
        self.output_serialization_seconds += sample.output_serialization_seconds
        self.serialized_input_bytes += sample.input_bytes
        self.serialized_output_bytes += sample.output_bytes
        self.peak_rss_bytes = max(self.peak_rss_bytes, sample.peak_rss_bytes)
        self.worker_cpu_seconds += sample.cpu_seconds
        self.process_ids.add(sample.process_id)

        if sample.status == "succeeded":
            self.succeeded_count += 1
            assert sample.win_probability is not None
            assert sample.loss_probability is not None
            assert sample.draw_probability is not None
            started = time.perf_counter()
            weight = Fraction(1, self.total_pair_count)
            self.weighted_win += weight * Fraction(*sample.win_probability)
            self.weighted_loss += weight * Fraction(*sample.loss_probability)
            self.weighted_draw += weight * Fraction(*sample.draw_probability)
            self.fraction_aggregation_seconds += time.perf_counter() - started
        elif sample.status == "truncated":
            self.truncated_count += 1
        else:
            self.failed_count += 1

        self.probability_records.append(
            "|".join(
                (
                    sample.pair_id,
                    sample.status,
                    _fraction_text(sample.win_probability),
                    _fraction_text(sample.loss_probability),
                    _fraction_text(sample.draw_probability),
                )
            )
        )
        if (
            self.processed_pair_count % self.progress_every == 0
            or self.processed_pair_count == self.progress_target_count
        ):
            progress_started = time.perf_counter()
            self.progress_curve.append(
                BenchmarkProgressPoint(
                    processed_pairs=self.processed_pair_count,
                    elapsed_seconds=time.perf_counter() - self.started_at,
                    parent_rss_bytes=_peak_rss_bytes(),
                    cumulative_nodes=self.cumulative_node_count,
                    cumulative_edges=self.cumulative_edge_count,
                )
            )
            self.progress_update_seconds += time.perf_counter() - progress_started


def _budget_stop_reason(
    accumulator: _RunAccumulator,
    limits: BenchmarkLimits,
) -> str | None:
    """在领取下一 case 前检查累计节点、边和失败数量预算。

    Args:
        accumulator: 已完成配置对的轻量累计状态。
        limits: 可选累计节点、边和最大失败数预算。

    Returns:
        首个已触发的稳定停止原因；仍可继续领取时返回 None。
    """
    if (
        limits.cumulative_node_limit is not None
        and accumulator.cumulative_node_count >= limits.cumulative_node_limit
    ):
        return "cumulative-node-limit"
    if (
        limits.cumulative_edge_limit is not None
        and accumulator.cumulative_edge_count >= limits.cumulative_edge_limit
    ):
        return "cumulative-edge-limit"
    if limits.max_failures is not None and accumulator.failed_count >= limits.max_failures:
        return "max-failures"
    return None


def _recommendation(
    workload: BenchmarkWorkloadSpec,
    accumulator: _RunAccumulator,
    *,
    worker_count: int,
    progress_every: int,
) -> BenchmarkBudgetRecommendation:
    """根据实际 P95、最大值与完整空间规模推导保守预算建议。

    Args:
        workload: 当前运行对应的完整配置空间规格。
        accumulator: 当前样本的图规模、状态和覆盖累计值。
        worker_count: 本次运行实际请求的进程数。
        progress_every: 本次进度快照频率。

    Returns:
        配置对、单 pair、累计预算、失败数、worker 和进度频率建议。
    """
    p95_nodes = int(ceil(_percentile(accumulator.node_counts, 0.95)))
    p95_edges = int(ceil(_percentile(accumulator.edge_counts, 0.95)))
    max_nodes = max(accumulator.node_counts, default=1)
    max_edges = max(accumulator.edge_counts, default=1)
    default_nodes = max(100, int(ceil(p95_nodes * 1.5)))
    default_edges = max(400, int(ceil(p95_edges * 1.5)))
    hard_nodes = max(default_nodes, max_nodes * 2)
    hard_edges = max(default_edges, max_edges * 2)
    mean_nodes = (
        accumulator.cumulative_node_count / accumulator.processed_pair_count
        if accumulator.processed_pair_count
        else default_nodes
    )
    mean_edges = (
        accumulator.cumulative_edge_count / accumulator.processed_pair_count
        if accumulator.processed_pair_count
        else default_edges
    )
    default_cumulative_nodes = int(ceil(mean_nodes * workload.pair_count * 1.25))
    default_cumulative_edges = int(ceil(mean_edges * workload.pair_count * 1.25))
    cpu_count = os.cpu_count() or 1
    return BenchmarkBudgetRecommendation(
        default_configuration_pair_limit=workload.pair_count,
        hard_configuration_pair_limit=44_100,
        default_pair_node_limit=default_nodes,
        hard_pair_node_limit=hard_nodes,
        default_pair_edge_limit=default_edges,
        hard_pair_edge_limit=hard_edges,
        default_pair_turn_limit=max(1, accumulator.max_turn_number),
        hard_pair_turn_limit=max(20, workload.graph_limits.max_turns or 20),
        default_cumulative_node_limit=max(default_nodes, default_cumulative_nodes),
        hard_cumulative_node_limit=max(hard_nodes, default_cumulative_nodes * 2),
        default_cumulative_edge_limit=max(default_edges, default_cumulative_edges),
        hard_cumulative_edge_limit=max(hard_edges, default_cumulative_edges * 2),
        default_max_failures=max(10, ceil(workload.pair_count * 0.01)),
        hard_max_failures=max(100, ceil(workload.pair_count * 0.05)),
        default_worker_count=min(worker_count, cpu_count),
        hard_worker_count=min(16, cpu_count),
        default_progress_every=progress_every,
        hard_progress_every=max(progress_every, 1_000),
    )


def _calibrate_cross_run_metrics(
    summaries: Sequence[BenchmarkRunSummary],
) -> tuple[BenchmarkRunSummary, ...]:
    """根据同一 workload 的串行基线校准加速比和建议 worker 数。

    Args:
        summaries: 已完成的 workload/worker 运行摘要，允许包含部分覆盖结果。

    Returns:
        保持原顺序、补齐相对单进程加速比并统一默认 worker 建议的摘要元组。
    """
    serial_throughput: dict[str, float] = {}
    best_workers: dict[str, int] = {}
    best_throughput: dict[str, float] = {}
    for summary in summaries:
        if summary.worker_count == 1:
            serial_throughput[summary.workload_id] = summary.throughput_pairs_per_second
        if summary.throughput_pairs_per_second > best_throughput.get(
            summary.workload_id, -1.0
        ):
            best_throughput[summary.workload_id] = summary.throughput_pairs_per_second
            best_workers[summary.workload_id] = summary.worker_count

    calibrated: list[BenchmarkRunSummary] = []
    for summary in summaries:
        baseline = serial_throughput.get(summary.workload_id, 0.0)
        speedup = (
            summary.throughput_pairs_per_second / baseline
            if baseline > 0
            else (1.0 if summary.worker_count == 1 else 0.0)
        )
        recommendation = replace(
            summary.recommendation,
            default_worker_count=best_workers.get(
                summary.workload_id, summary.recommendation.default_worker_count
            ),
        )
        calibrated.append(
            replace(
                summary,
                speedup_vs_single_process=speedup,
                recommendation=recommendation,
            )
        )
    return tuple(calibrated)


def _language_decision(
    summaries: Sequence[BenchmarkRunSummary],
) -> tuple[str, str]:
    """根据完整最大规模覆盖和 profiler 自耗时占比给出语言路线结论。

    Args:
        summaries: 已校准的全部运行摘要。

    Returns:
        稳定决策标识和可直接写入报告的人类可读证据说明。
    """
    complete_maximum = tuple(
        summary
        for summary in summaries
        if summary.total_pair_count == 44_100
        and summary.processed_pair_count == summary.total_pair_count
        and summary.stop_reason == "completed"
    )
    profiled = tuple(
        summary
        for summary in complete_maximum
        if summary.profiler_top_ten
    )
    if not complete_maximum:
        return (
            "insufficient-evidence",
            "尚未在当前机器完整覆盖 44,100 配置对，不能据此冻结原生语言改写结论。",
        )
    if not profiled:
        return (
            "profile-python-first",
            "最大配置空间已完成，但缺少单进程 profiler 证据；应先分析 Python 热点。",
        )
    top_share = max(summary.profiler_top_self_time_share for summary in profiled)
    if top_share >= 0.70:
        return (
            "consider-local-native-acceleration",
            f"单一 profiler 自耗时热点占比达到 {top_share:.2%}，可评估窄范围原生加速。",
        )
    return (
        "continue-pure-python",
        f"完整最大配置空间已覆盖，最高单一 profiler 自耗时占比为 {top_share:.2%}，未达到 70% 门槛。",
    )


def _consistency_checks(
    summaries: Sequence[BenchmarkRunSummary],
) -> tuple[BenchmarkConsistencyCheck, ...]:
    """为同 workload 的每两个 worker 结果生成精确一致性检查。

    Args:
        summaries: 已完成并校准的 run 摘要。

    Returns:
        每对 worker 的配置集合、状态计数和概率摘要一致性结果。
    """
    checks: list[BenchmarkConsistencyCheck] = []
    by_workload: dict[str, list[BenchmarkRunSummary]] = {}
    for summary in summaries:
        by_workload.setdefault(summary.workload_id, []).append(summary)
    for workload_id, values in by_workload.items():
        for left, right in combinations(values, 2):
            checks.append(
                BenchmarkConsistencyCheck(
                    workload_id=workload_id,
                    left_worker_count=left.worker_count,
                    right_worker_count=right.worker_count,
                    same_pair_set=left.completed_pair_ids == right.completed_pair_ids,
                    same_status_counts=(
                        left.succeeded_count,
                        left.truncated_count,
                        left.failed_count,
                    )
                    == (
                        right.succeeded_count,
                        right.truncated_count,
                        right.failed_count,
                    ),
                    same_probability_digest=(
                        left.probability_digest == right.probability_digest
                    ),
                )
            )
    return tuple(checks)


def _environment() -> BenchmarkEnvironment:
    """读取不包含凭据的代码版本、解释器、CPU 和物理内存环境。

    Returns:
        可随 JSON 报告持久化的当前机器与 checkout 环境快照。
    """
    return BenchmarkEnvironment(
        commit=_git_commit(),
        python=sys.version.replace("\n", " "),
        platform=platform.platform(),
        machine=platform.machine(),
        processor=platform.processor(),
        cpu_count=os.cpu_count() or 1,
        total_memory_bytes=_total_memory_bytes(),
    )


def _git_commit() -> str:
    """读取当前 checkout commit。

    Returns:
        git rev-parse 输出的 commit SHA；当前目录不是 checkout 时返回 unknown。
    """
    try:
        return subprocess.run(
            ("git", "rev-parse", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _total_memory_bytes() -> int | None:
    """在支持 sysconf 的平台读取物理内存总量。

    Returns:
        物理内存字节数；平台不支持或读取失败时返回 None。
    """
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def _percentile(values: Sequence[float | int], quantile: float) -> float:
    """使用 nearest-rank 规则计算稳定分位数。

    Args:
        values: 待统计的非空或空数值序列。
        quantile: 0 到 1 之间的目标分位位置，调用方使用 P50 或 P95。

    Returns:
        nearest-rank 分位值；空序列返回 0。
    """
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, min(len(ordered) - 1, ceil(quantile * len(ordered)) - 1))
    return ordered[index]


def _rss_slope(points: Sequence[BenchmarkProgressPoint]) -> float:
    """使用首尾曲线点估算每完成一个配置对的 RSS 增长斜率。

    Args:
        points: 按处理顺序采集的父进程 RSS 与累计资源快照。

    Returns:
        每个配置对对应的估算 RSS 字节变化；不足两个点时返回 0。
    """
    if len(points) < 2:
        return 0.0
    first = points[0]
    last = points[-1]
    pair_delta = last.processed_pairs - first.processed_pairs
    return (
        (last.parent_rss_bytes - first.parent_rss_bytes) / pair_delta
        if pair_delta
        else 0.0
    )


def _profiler_lines(profiler: cProfile.Profile | None) -> tuple[str, ...]:
    """把 cProfile 累计耗时前十热点压缩为报告行。

    Args:
        profiler: 已停止采样的串行 cProfile 对象；None 表示未启用。

    Returns:
        去除空行后的 profiler 文本元组，最多覆盖前十热点表。
    """
    if profiler is None:
        return ()
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats("cumulative").print_stats(10)
    return tuple(line.rstrip() for line in stream.getvalue().splitlines() if line.strip())


def _profiler_hotspot_share(profiler: cProfile.Profile | None) -> float:
    """计算 profiler 中单一函数自耗时占总自耗时的最大比例。

    Args:
        profiler: 已停止采样的 cProfile 对象；None 表示未启用 profiler。

    Returns:
        0 到 1 的最大自耗时占比；没有样本时返回 0。
    """
    if profiler is None:
        return 0.0
    statistics = pstats.Stats(profiler)
    total_time = statistics.total_tt
    if total_time <= 0:
        return 0.0
    return max(
        (entry[2] / total_time for entry in statistics.stats.values()),
        default=0.0,
    )


__all__ = [
    "_RunAccumulator",
    "_budget_stop_reason",
    "_calibrate_cross_run_metrics",
    "_consistency_checks",
    "_environment",
    "_language_decision",
    "_profiler_hotspot_share",
    "_profiler_lines",
    "_recommendation",
]
