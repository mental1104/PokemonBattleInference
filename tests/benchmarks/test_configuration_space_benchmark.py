"""验证 issue #92 基准夹具、轻量指标、报告输出和恢复合同。"""

from __future__ import annotations

import json
from dataclasses import replace
from fractions import Fraction
from itertools import islice

from pokeop.application.solver.models import StateGraphLimits
from pokeop.benchmarks.configuration_space import (
    FIXTURE_VERSION,
    WORKLOADS,
    BenchmarkLimits,
    iter_benchmark_cases,
    load_resume_pair_ids,
    run_benchmark_suite,
    workload_by_id,
    write_report,
)


def test_frozen_workload_pair_counts_match_issue_92_contract() -> None:
    """固定 workload 必须覆盖三种候选分配和三类图行为。

    测试明确锁定 19+1、12+8、10+10 对应的 3,876、34,650、44,100
    配置对数量，并要求每个夹具双方候选总数严格等于二十，避免以后修改
    组合规则或夹具时静默偏离 issue #92 的性能基线。该边界也保证后续机器
    报告可以跨提交比较，而不是在输入规模变化后误判性能回归或性能提升。
    """
    pair_counts = {workload.workload_id: workload.pair_count for workload in WORKLOADS}

    assert len(WORKLOADS) == 6
    assert pair_counts["attack-19x1"] == 3_876
    assert pair_counts["attack-12x8"] == 34_650
    assert pair_counts["attack-10x10"] == 44_100
    assert pair_counts["mixed-10x10"] == 44_100
    assert pair_counts["cyclic-10x10"] == 44_100
    assert pair_counts["budget-stop-10x10"] == 44_100
    assert all(
        workload.attacker_move_count + workload.defender_move_count == 20
        for workload in WORKLOADS
    )


def test_case_iterator_is_stable_and_preserves_full_space_weight() -> None:
    """配置对生成器必须保持稳定顺序和完整空间权重语义。

    测试只截取 19+1 workload 的前三项，验证重复遍历产生一致 pair ID，且
    每项权重仍以完整 3,876 配置空间为分母，不因 smoke 限制或惰性截取
    重新归一化，从而保护部分覆盖报告和恢复执行的幂等边界。该测试还要求
    配置中招式槽位遵循产品规范，防止 iterator 为追求速度绕过现有组合语义。
    """
    workload = workload_by_id("attack-19x1")

    first = tuple(islice(iter_benchmark_cases(workload), 3))
    repeated = tuple(islice(iter_benchmark_cases(workload), 3))

    assert [case.work_item.pair_id for case in first] == [
        case.work_item.pair_id for case in repeated
    ]
    assert len({case.work_item.pair_id for case in first}) == 3
    assert all(
        case.work_item.configuration_weight == Fraction(1, 3_876)
        for case in first
    )
    assert all(len(case.work_item.configuration.attacker.moves) == 4 for case in first)
    assert all(len(case.work_item.configuration.defender.moves) == 1 for case in first)


def test_smoke_run_reports_graph_fraction_process_and_progress_metrics(tmp_path) -> None:
    """真实 builder 与 solver 的紧预算 smoke case 必须形成可追溯报告。

    即使结果因节点或边上限被截断，也要记录原始转移、归并边、SCC、进程、
    RSS、序列化、进度曲线和停止状态。报告只能保存轻量 pair 摘要，不得暴露
    graph artifact；PostgreSQL 未参与 direct-solver 路径时必须保留 null，不能
    伪造写库耗时。最后还要验证 JSON、Markdown 与恢复 ID 可以互相闭环，确保
    长耗时完整运行在中断后仍有明确、可复用且不会重复计算的部分结果。
    """
    workload = replace(
        workload_by_id("attack-19x1"),
        workload_id="test-attack-19x1",
        graph_limits=StateGraphLimits(max_nodes=2, max_edges=8, max_turns=1),
    )

    report = run_benchmark_suite(
        (workload,),
        worker_counts=(1, 2),
        limits=BenchmarkLimits(max_pairs=2, progress_every=1),
    )
    serial_run, parallel_run = report.runs

    assert report.fixture_version == FIXTURE_VERSION
    assert report.consistency_checks[0].consistent
    for run in (serial_run, parallel_run):
        assert run.requested_pair_count == 2
        assert run.processed_pair_count == 2
        assert run.succeeded_count + run.truncated_count + run.failed_count == 2
        assert run.raw_transition_count >= run.merged_transition_count
        assert run.process_count >= 1
        assert run.progress_curve[-1].processed_pairs == 2
        assert run.progress_update_seconds >= 0
        assert run.postgres_write_seconds is None
        assert len(run.completed_pair_ids) == 2
        assert not hasattr(run, "graph")

    json_path, markdown_path = write_report(report, tmp_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["fixture_version"] == FIXTURE_VERSION
    assert payload["runs"][0]["processed_pair_count"] == 2
    assert "postgres_write_seconds" in payload["runs"][0]
    assert markdown_path.read_text(encoding="utf-8").startswith(
        f"# Configuration Space Benchmark ({FIXTURE_VERSION})"
    )
    assert load_resume_pair_ids(json_path) == frozenset(serial_run.completed_pair_ids)
