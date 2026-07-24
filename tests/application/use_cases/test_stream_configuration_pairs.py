"""验证配置对流式执行、精确聚合、运行预算和图生命周期。"""

from __future__ import annotations

import gc
from collections.abc import Iterator
from fractions import Fraction
from itertools import islice
from typing import cast

from pokeop.application.use_cases.stream_configuration_pairs import (
    ConfigurationPairExecutionStatus,
    ConfigurationPairStopReason,
    iter_configuration_pairs,
)
from tests.application.use_cases.stream_configuration_pairs_test_helpers import (
    _CancelAfterChecks,
    _FakeExecution,
    _FakeExecutionKind,
    _command,
    _execute,
)


def test_lazily_generates_44100_configuration_pairs() -> None:
    """两侧各 210 个配置应惰性形成 44,100 个稳定配置对。"""
    command = _command(
        attacker_ids=tuple(f"attacker-{index:03d}" for index in reversed(range(210))),
        defender_ids=tuple(f"defender-{index:03d}" for index in reversed(range(210))),
    )

    iterator = iter_configuration_pairs(command)
    assert isinstance(iterator, Iterator)
    first_three = tuple(islice(iterator, 3))

    assert command.total_pair_count == 44_100
    assert [item.attacker_configuration_id for item in first_three] == [
        "attacker-000",
        "attacker-000",
        "attacker-000",
    ]
    assert [item.defender_configuration_id for item in first_three] == [
        "defender-000",
        "defender-001",
        "defender-002",
    ]
    assert len(first_three) + sum(1 for _ in iterator) == 44_100


def test_streams_all_statuses_and_releases_each_complete_graph() -> None:
    """fake sink 应逐项看到成功、失败、截断，完整图同时存活数量上界为 1。"""
    command = _command()
    executions = {
        ("attacker-a", "defender-a"): _FakeExecution(
            win_probability=Fraction(3, 4),
            loss_probability=Fraction(1, 4),
            draw_probability=Fraction(0),
        ),
        ("attacker-a", "defender-b"): _FakeExecution(
            kind=_FakeExecutionKind.RAISE_ERROR
        ),
        ("attacker-b", "defender-a"): _FakeExecution(
            kind=_FakeExecutionKind.TRUNCATED,
            node_count=7,
            edge_count=9,
        ),
        ("attacker-b", "defender-b"): _FakeExecution(
            win_probability=Fraction(1, 4),
            loss_probability=Fraction(1, 2),
            draw_probability=Fraction(1, 4),
        ),
    }

    aggregate, executor, result_sink, progress_sink = _execute(command, executions)
    gc.collect()

    assert [result.status for result in result_sink.results] == [
        ConfigurationPairExecutionStatus.SUCCEEDED,
        ConfigurationPairExecutionStatus.FAILED,
        ConfigurationPairExecutionStatus.TRUNCATED,
        ConfigurationPairExecutionStatus.SUCCEEDED,
    ]
    assert aggregate.succeeded_count == 2
    assert aggregate.failed_count == 1
    assert aggregate.truncated_count == 1
    assert aggregate.attempted_weight == Fraction(1)
    assert aggregate.completed_weight == Fraction(1, 2)
    assert aggregate.weighted_win_probability == Fraction(1, 4)
    assert aggregate.weighted_loss_probability == Fraction(3, 16)
    assert aggregate.weighted_draw_probability == Fraction(1, 16)
    assert aggregate.stop_reason is ConfigurationPairStopReason.COMPLETED
    assert len(progress_sink.progress) == 4
    assert progress_sink.progress[-1].cumulative_node_count == aggregate.cumulative_node_count
    assert result_sink.final == aggregate
    assert all(not hasattr(result, "graph") for result in result_sink.results)
    assert result_sink.results[0].attacker_move_ids == (245, 280)
    assert result_sink.results[0].defender_move_ids == (8, 252)
    assert executor.max_live_graph_count == 1
    assert all(reference() is None for reference in executor.graph_references)


def test_typed_solver_failure_keeps_graph_resource_summary() -> None:
    """完整图的 solver 资源失败应写出失败状态和已消耗图规模。"""
    command = _command(
        attacker_ids=("attacker-a",),
        defender_ids=("defender-a",),
    )
    aggregate, executor, result_sink, _ = _execute(
        command,
        {
            ("attacker-a", "defender-a"): _FakeExecution(
                kind=_FakeExecutionKind.SOLVER_FAILED,
                node_count=11,
                edge_count=13,
                scc_count=4,
            )
        },
    )
    gc.collect()

    result = result_sink.results[0]
    assert result.status is ConfigurationPairExecutionStatus.FAILED
    assert result.node_count == 11
    assert result.edge_count == 13
    assert result.scc_count == 4
    assert result.diagnostics == ("fake solver resource limit",)
    assert aggregate.failed_count == 1
    assert aggregate.completed_weight == Fraction(0)
    assert aggregate.attempted_weight == Fraction(1)
    assert all(reference() is None for reference in executor.graph_references)


def test_cumulative_node_budget_stops_before_claiming_another_pair() -> None:
    """累计节点达到预算后应保留已完成摘要，不领取下一配置且不重新归一化。"""
    command = _command(
        attacker_ids=("attacker-a",),
        defender_ids=("defender-a", "defender-b", "defender-c", "defender-d"),
        cumulative_node_limit=5,
    )

    aggregate, _, result_sink, progress_sink = _execute(command, {})

    assert aggregate.stop_reason is ConfigurationPairStopReason.CUMULATIVE_NODE_LIMIT
    assert aggregate.processed_pair_count == 2
    assert aggregate.unprocessed_pair_count == 2
    assert aggregate.cumulative_node_count == 6
    assert aggregate.attempted_weight == Fraction(1, 2)
    assert aggregate.completed_weight == Fraction(1, 2)
    assert (
        aggregate.weighted_win_probability
        + aggregate.weighted_loss_probability
        + aggregate.weighted_draw_probability
        == Fraction(1, 2)
    )
    assert len(result_sink.results) == 2
    assert len(progress_sink.progress) == 2


def test_streaming_fraction_aggregate_and_top_k_match_eager_reference() -> None:
    """小规模流式概率、计数和 Top-K 应与一次性参考计算完全一致。"""
    command = _command(top_k=2)
    executions = {
        ("attacker-a", "defender-a"): _FakeExecution(
            win_probability=Fraction(1, 3),
            loss_probability=Fraction(1, 3),
            draw_probability=Fraction(1, 3),
            expected_turns=Fraction(5, 2),
            node_count=4,
            edge_count=5,
        ),
        ("attacker-a", "defender-b"): _FakeExecution(
            win_probability=Fraction(3, 5),
            loss_probability=Fraction(1, 5),
            draw_probability=Fraction(1, 5),
            expected_turns=Fraction(7, 2),
            node_count=8,
            edge_count=10,
        ),
        ("attacker-b", "defender-a"): _FakeExecution(
            win_probability=Fraction(1, 10),
            loss_probability=Fraction(7, 10),
            draw_probability=Fraction(1, 5),
            expected_turns=Fraction(9, 2),
            node_count=6,
            edge_count=7,
        ),
        ("attacker-b", "defender-b"): _FakeExecution(
            win_probability=Fraction(4, 5),
            loss_probability=Fraction(1, 10),
            draw_probability=Fraction(1, 10),
            expected_turns=Fraction(2),
            node_count=3,
            edge_count=2,
        ),
    }

    aggregate, _, result_sink, _ = _execute(command, executions)
    eager_win = sum(
        (Fraction(1, 4) * execution.win_probability for execution in executions.values()),
        start=Fraction(0),
    )
    eager_loss = sum(
        (Fraction(1, 4) * execution.loss_probability for execution in executions.values()),
        start=Fraction(0),
    )
    eager_draw = sum(
        (Fraction(1, 4) * execution.draw_probability for execution in executions.values()),
        start=Fraction(0),
    )

    assert aggregate.weighted_win_probability == eager_win
    assert aggregate.weighted_loss_probability == eager_loss
    assert aggregate.weighted_draw_probability == eager_draw
    assert aggregate.completed_weight == Fraction(1)
    assert aggregate.cumulative_node_count == sum(
        execution.node_count for execution in executions.values()
    )
    assert aggregate.cumulative_edge_count == sum(
        execution.edge_count for execution in executions.values()
    )
    expected_win_order = [
        result.pair_id
        for result in sorted(
            result_sink.results,
            key=lambda result: (
                -cast(Fraction, result.win_probability),
                result.pair_id,
            ),
        )[:2]
    ]
    assert [entry.pair_id for entry in aggregate.top_win_probability] == expected_win_order
    assert len(aggregate.top_expected_turns) == 2
    assert aggregate.top_expected_turns[0].expected_turns == Fraction(9, 2)
    assert len(aggregate.top_node_count) == 2
    assert aggregate.top_node_count[0].node_count == 8
    assert aggregate.fraction_complexity.observed_fraction_count > 0
    assert aggregate.fraction_complexity.max_denominator_bits >= 3


def test_reordering_candidate_inputs_keeps_pair_set_and_aggregate() -> None:
    """交换候选输入顺序不应改变稳定配置集合、执行顺序或最终聚合。"""
    executions = {
        ("attacker-a", "defender-a"): _FakeExecution(
            win_probability=Fraction(1),
            loss_probability=Fraction(0),
            draw_probability=Fraction(0),
        ),
        ("attacker-a", "defender-b"): _FakeExecution(
            win_probability=Fraction(0),
            loss_probability=Fraction(1),
            draw_probability=Fraction(0),
        ),
        ("attacker-b", "defender-a"): _FakeExecution(
            win_probability=Fraction(1, 2),
            loss_probability=Fraction(1, 2),
            draw_probability=Fraction(0),
        ),
        ("attacker-b", "defender-b"): _FakeExecution(
            win_probability=Fraction(1, 4),
            loss_probability=Fraction(1, 4),
            draw_probability=Fraction(1, 2),
        ),
    }
    forward = _command(
        attacker_ids=("attacker-a", "attacker-b"),
        defender_ids=("defender-a", "defender-b"),
    )
    reversed_input = _command(
        attacker_ids=("attacker-b", "attacker-a"),
        defender_ids=("defender-b", "defender-a"),
    )

    forward_aggregate, _, forward_sink, _ = _execute(forward, executions)
    reversed_aggregate, _, reversed_sink, _ = _execute(reversed_input, executions)

    assert [result.pair_id for result in forward_sink.results] == [
        result.pair_id for result in reversed_sink.results
    ]
    assert forward_aggregate == reversed_aggregate


def test_cancellation_and_max_failure_budget_stop_only_before_new_pairs() -> None:
    """取消与最大失败预算都应在已写出当前轻量结果后停止领取新配置。"""
    command = _command(
        attacker_ids=("attacker-a",),
        defender_ids=("defender-a", "defender-b", "defender-c"),
    )
    cancelled, _, cancelled_sink, _ = _execute(
        command,
        {},
        cancellation_token=_CancelAfterChecks(allowed_checks=2),
    )
    failure_command = _command(
        attacker_ids=("attacker-a",),
        defender_ids=("defender-a", "defender-b", "defender-c"),
        max_failures=1,
    )
    failed, _, failed_sink, _ = _execute(
        failure_command,
        {
            ("attacker-a", "defender-a"): _FakeExecution(
                kind=_FakeExecutionKind.RAISE_ERROR
            )
        },
    )

    assert cancelled.stop_reason is ConfigurationPairStopReason.CANCELLED
    assert cancelled.processed_pair_count == 2
    assert len(cancelled_sink.results) == 2
    assert failed.stop_reason is ConfigurationPairStopReason.MAX_FAILURES
    assert failed.processed_pair_count == 1
    assert failed.failed_count == 1
    assert len(failed_sink.results) == 1


def test_summary_failure_is_typed_and_does_not_abort_later_pairs() -> None:
    """图构建后的摘要异常应保留资源规模，并继续执行后续配置对。"""
    command = _command(
        attacker_ids=("attacker-a",),
        defender_ids=("defender-a", "defender-b"),
    )
    aggregate, executor, result_sink, _ = _execute(
        command,
        {
            ("attacker-a", "defender-a"): _FakeExecution(
                kind=_FakeExecutionKind.MALFORMED_SOLVE_RESULT,
                node_count=12,
                edge_count=17,
                scc_count=5,
                max_turn_number=4,
            )
        },
    )
    gc.collect()

    first, second = result_sink.results
    assert first.status is ConfigurationPairExecutionStatus.FAILED
    assert first.node_count == 12
    assert first.edge_count == 17
    assert first.scc_count == 5
    assert first.max_turn_number == 4
    assert first.diagnostics == (
        "ConfigurationPairStreamError: "
        "solved configuration pair is missing exact probabilities",
    )
    assert second.status is ConfigurationPairExecutionStatus.SUCCEEDED
    assert aggregate.processed_pair_count == 2
    assert aggregate.failed_count == 1
    assert aggregate.succeeded_count == 1
    assert aggregate.stop_reason is ConfigurationPairStopReason.COMPLETED
    assert executor.max_live_graph_count == 1
    assert all(reference() is None for reference in executor.graph_references)
