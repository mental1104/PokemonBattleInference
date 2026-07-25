"""运行串行或有界多进程配置对基准。"""

from __future__ import annotations

import cProfile
import hashlib
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from itertools import islice

from pokeop.benchmarks.aggregation import (
    _RunAccumulator,
    _budget_stop_reason,
    _calibrate_cross_run_metrics,
    _consistency_checks,
    _environment,
    _language_decision,
    _percentile,
    _profiler_hotspot_share,
    _profiler_lines,
    _recommendation,
    _rss_slope,
)
from pokeop.benchmarks.execution import _execute_case, _failed_benchmark_sample, _peak_rss_bytes
from pokeop.benchmarks.fixtures import iter_benchmark_cases
from pokeop.benchmarks.models import (
    FIXTURE_VERSION,
    BenchmarkCaseInput,
    BenchmarkLimits,
    BenchmarkReport,
    BenchmarkRunSummary,
    BenchmarkWorkloadSpec,
)


def run_benchmark_suite(
    workloads: Sequence[BenchmarkWorkloadSpec],
    *,
    worker_counts: Sequence[int],
    limits: BenchmarkLimits,
    profile_serial: bool = False,
    resume_pair_ids: frozenset[str] = frozenset(),
) -> BenchmarkReport:
    """运行 workload 与 worker 数笛卡尔积，并生成一致性和预算建议。

    Args:
        workloads: 需要执行的固定 workload 集合。
        worker_counts: 每个 workload 依次测试的正整数进程数。
        limits: benchmark 累计预算和进度采样频率。
        profile_serial: 是否对单进程路径启用 cProfile 并保留前十热点。
        resume_pair_ids: 已完成 pair ID；恢复时不再重复执行。

    Returns:
        包含环境、全部运行摘要与单/多进程概率一致性检查的报告。
    """
    normalized_workers = tuple(dict.fromkeys(worker_counts))
    if not normalized_workers or any(value <= 0 for value in normalized_workers):
        raise ValueError("worker_counts must contain positive integers")
    summaries: list[BenchmarkRunSummary] = []
    cancelled = False
    for workload in workloads:
        for worker_count in normalized_workers:
            summary = _run_one(
                workload,
                worker_count=worker_count,
                limits=limits,
                profile=profile_serial and worker_count == 1,
                resume_pair_ids=resume_pair_ids,
            )
            summaries.append(summary)
            if summary.cancelled:
                cancelled = True
                break
        if cancelled:
            break
    calibrated = _calibrate_cross_run_metrics(summaries)
    decision, reason = _language_decision(calibrated)
    return BenchmarkReport(
        schema_version=1,
        fixture_version=FIXTURE_VERSION,
        generated_at_unix_seconds=time.time(),
        environment=_environment(),
        runs=calibrated,
        consistency_checks=_consistency_checks(calibrated),
        language_decision=decision,
        language_decision_reason=reason,
    )


def _run_one(
    workload: BenchmarkWorkloadSpec,
    *,
    worker_count: int,
    limits: BenchmarkLimits,
    profile: bool,
    resume_pair_ids: frozenset[str],
) -> BenchmarkRunSummary:
    """执行单个 workload/worker 组合并保留部分覆盖结果。

    Args:
        workload: 固定候选池、机制类别和单 pair 图预算。
        worker_count: 配置对级执行进程数；1 表示当前进程串行执行。
        limits: 批量累计预算、最大 case 数和进度采样频率。
        profile: 是否在串行路径启用 cProfile。
        resume_pair_ids: 已完成配置对集合，本次生成器会跳过这些 ID。

    Returns:
        包含覆盖率、时间、资源、概率摘要和预算建议的轻量 run 结果。
    """
    available = workload.pair_count - sum(
        pair_id.startswith(f"bench-{workload.workload_id}-")
        for pair_id in resume_pair_ids
    )
    requested = min(available, limits.max_pairs) if limits.max_pairs else available
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    accumulator = _RunAccumulator(
        total_pair_count=workload.pair_count,
        progress_target_count=requested,
        progress_every=limits.progress_every,
        started_at=started_wall,
    )
    profiler = cProfile.Profile() if profile else None
    if profiler is not None:
        profiler.enable()
    cancelled = False
    stop_reason = "completed"
    try:
        cases = islice(
            iter_benchmark_cases(workload, skip_pair_ids=resume_pair_ids),
            requested,
        )
        if worker_count == 1:
            for case in cases:
                accumulator.add(_execute_case(case))
                stop_reason = _budget_stop_reason(accumulator, limits) or stop_reason
                if stop_reason != "completed":
                    break
        else:
            stop_reason = _run_parallel(
                cases,
                worker_count=worker_count,
                accumulator=accumulator,
                limits=limits,
            )
    except KeyboardInterrupt:
        # 用户取消仍然写出已完成 case，便于后续 --resume-from 继续。
        cancelled = True
        stop_reason = "cancelled"
    finally:
        if profiler is not None:
            profiler.disable()

    wall_seconds = time.perf_counter() - started_wall
    coordinator_cpu_seconds = time.process_time() - started_cpu
    cpu_seconds = coordinator_cpu_seconds + (
        accumulator.worker_cpu_seconds if worker_count > 1 else 0.0
    )
    profile_lines = _profiler_lines(profiler)
    profiler_hotspot_share = _profiler_hotspot_share(profiler)
    if stop_reason == "completed" and accumulator.processed_pair_count < requested:
        stop_reason = "source-exhausted"
    recommendation = _recommendation(
        workload,
        accumulator,
        worker_count=worker_count,
        progress_every=limits.progress_every,
    )
    raw = accumulator.raw_transition_count
    merged = accumulator.merged_transition_count
    digest = hashlib.sha256(
        "\n".join(sorted(accumulator.probability_records)).encode("utf-8")
    ).hexdigest()
    total_execution_wall = sum(accumulator.latencies)
    coordinator_overhead = max(
        0.0,
        wall_seconds - total_execution_wall / max(worker_count, 1),
    )
    return BenchmarkRunSummary(
        workload_id=workload.workload_id,
        fixture_version=FIXTURE_VERSION,
        worker_count=worker_count,
        total_pair_count=workload.pair_count,
        requested_pair_count=requested,
        processed_pair_count=accumulator.processed_pair_count,
        coverage_ratio=(
            accumulator.processed_pair_count / workload.pair_count
            if workload.pair_count
            else 0.0
        ),
        succeeded_count=accumulator.succeeded_count,
        truncated_count=accumulator.truncated_count,
        failed_count=accumulator.failed_count,
        cancelled=cancelled,
        stop_reason=stop_reason,
        wall_seconds=wall_seconds,
        cpu_seconds=cpu_seconds,
        throughput_pairs_per_second=(
            accumulator.processed_pair_count / wall_seconds if wall_seconds else 0.0
        ),
        p50_pair_seconds=_percentile(accumulator.latencies, 0.50),
        p95_pair_seconds=_percentile(accumulator.latencies, 0.95),
        peak_rss_bytes=max(accumulator.peak_rss_bytes, _peak_rss_bytes()),
        rss_slope_bytes_per_pair=_rss_slope(accumulator.progress_curve),
        process_count=max(1, len(accumulator.process_ids)),
        cumulative_node_count=accumulator.cumulative_node_count,
        cumulative_edge_count=accumulator.cumulative_edge_count,
        raw_transition_count=raw,
        merged_transition_count=merged,
        transition_merge_rate=(1.0 - merged / raw if raw else 0.0),
        scc_count=accumulator.scc_count,
        max_scc_size=accumulator.max_scc_size,
        max_turn_number=accumulator.max_turn_number,
        max_numerator_bits=accumulator.max_numerator_bits,
        max_denominator_bits=accumulator.max_denominator_bits,
        fraction_aggregation_seconds=accumulator.fraction_aggregation_seconds,
        fraction_aggregation_share=(
            accumulator.fraction_aggregation_seconds / wall_seconds
            if wall_seconds
            else 0.0
        ),
        input_serialization_seconds=accumulator.input_serialization_seconds,
        output_serialization_seconds=accumulator.output_serialization_seconds,
        serialized_input_bytes=accumulator.serialized_input_bytes,
        serialized_output_bytes=accumulator.serialized_output_bytes,
        coordinator_overhead_seconds=coordinator_overhead,
        progress_update_seconds=accumulator.progress_update_seconds,
        postgres_write_seconds=None,
        probability_digest=digest,
        speedup_vs_single_process=1.0 if worker_count == 1 else 0.0,
        profiler_top_self_time_share=profiler_hotspot_share,
        completed_pair_ids=tuple(sorted(accumulator.completed_pair_ids)),
        progress_curve=tuple(accumulator.progress_curve),
        profiler_top_ten=profile_lines,
        recommendation=recommendation,
    )


def _run_parallel(
    cases: Iterable[BenchmarkCaseInput],
    *,
    worker_count: int,
    accumulator: _RunAccumulator,
    limits: BenchmarkLimits,
) -> str:
    """使用有界 in-flight Future 在配置对级并行执行。

    Args:
        cases: 惰性配置对输入流，不会一次性保存全部 case。
        worker_count: ProcessPoolExecutor 的最大工作进程数。
        accumulator: 父进程唯一轻量聚合器。
        limits: 达到累计预算后停止提交新 case。

    Returns:
        completed 或具体累计预算停止原因。

    Side Effects:
        创建并关闭进程池；预算触发后取消尚未开始的 Future。
    """
    iterator = iter(cases)
    in_flight: dict[Future[BenchmarkPairSample], BenchmarkCaseInput] = {}
    queue_depth = max(worker_count * 2, worker_count)
    stop_reason = "completed"
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        exhausted = False
        while in_flight or not exhausted:
            while not exhausted and len(in_flight) < queue_depth:
                try:
                    case = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                in_flight[executor.submit(_execute_case, case)] = case
            if not in_flight:
                break
            completed, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in completed:
                case = in_flight.pop(future)
                try:
                    sample = future.result()
                except Exception as error:  # noqa: BLE001 - 子进程失败必须保留部分报告。
                    sample = _failed_benchmark_sample(case, error)
                accumulator.add(sample)
                reason = _budget_stop_reason(accumulator, limits)
                if reason is not None:
                    stop_reason = reason
                    exhausted = True
                    for pending in in_flight:
                        pending.cancel()
                    in_flight.clear()
                    break
    return stop_reason


__all__ = ["run_benchmark_suite"]
