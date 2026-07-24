"""验证结构化战报严格遵循用户实际选择的 edge 序列。"""

from __future__ import annotations

from pokeop.application.solver.models import GraphNodeId
from pokeop.application.use_cases.battle_exploration import (
    BuildBattleReportUseCase,
    LoadBattleNodeUseCase,
)
from tests.application.use_cases.battle_exploration_test_helpers import (
    GRAPH_ID,
    REVISION,
    advance,
    stored_store,
)


def test_reports_preserve_distinct_merge_paths_and_edge_alternatives() -> None:
    """两条路径合流到同一节点时，报告仍按各自 edge 和替代事件路径生成。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    left_merged = advance(store, advance(store, root, 0), 2)
    right_merged = advance(store, advance(store, root, 1), 3)

    left_report = BuildBattleReportUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        left_merged,
    )
    right_report = BuildBattleReportUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        right_merged,
    )

    assert left_report.current_node_id == right_report.current_node_id == 3
    assert tuple(step.edge_id for step in left_report.steps) == (0, 2)
    assert tuple(step.edge_id for step in right_report.steps) == (1, 3)
    assert left_report.cumulative_probability.numerator == "1"
    assert left_report.cumulative_probability.denominator == "3"
    assert right_report.cumulative_probability.numerator == "2"
    assert right_report.cumulative_probability.denominator == "3"
    assert len(right_report.steps[0].event_paths) == 2
    assert tuple(
        path.battle_events[0].kind for path in right_report.steps[0].event_paths
    ) == ("damage", "damage")


def test_report_keeps_cycle_back_edge_and_repeated_root_node() -> None:
    """循环回边不能被误判为路径结束，重复 root 必须出现在步骤目标中。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    merged = advance(store, advance(store, root, 0), 2)
    cycled = advance(store, merged, 4)

    report = BuildBattleReportUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        cycled,
    )

    assert cycled.current_node_id == GraphNodeId(0)
    assert tuple(step.target_node_id for step in report.steps) == (1, 3, 0)
    assert report.current_node_id == 0
    assert report.depth == 3
    assert report.cumulative_probability.numerator == "1"
    assert report.cumulative_probability.denominator == "12"


def test_report_step_probabilities_are_exact_prefix_products() -> None:
    """每一步累计概率必须使用 Fraction 前缀乘积，而不是展示浮点值回算。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    terminal = advance(
        store,
        advance(store, advance(store, root, 0), 2),
        5,
    )

    report = BuildBattleReportUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        terminal,
    )

    assert tuple(
        (step.cumulative_probability.numerator, step.cumulative_probability.denominator)
        for step in report.steps
    ) == (("1", "3"), ("1", "3"), ("1", "4"))
    assert len(report.steps[-1].event_paths) == 2
    assert report.cumulative_probability.numerator == "1"
    assert report.cumulative_probability.denominator == "4"
