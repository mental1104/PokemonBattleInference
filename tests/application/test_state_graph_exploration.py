from __future__ import annotations

from fractions import Fraction
from typing import cast

import pytest

from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
    StrongComponent,
    StrongComponentId,
    StrongComponentKind,
)
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationDepthError,
    ExplorationEdgeError,
    ExplorationGraphMismatchError,
    ExplorationPathError,
    ExplorationPathStep,
    StateGraphExplorationUseCase,
)
from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import TransitionEventSummary


_ROOT_NODE_ID = GraphNodeId(0)
_LEFT_NODE_ID = GraphNodeId(1)
_RIGHT_NODE_ID = GraphNodeId(2)
_MERGED_NODE_ID = GraphNodeId(3)
_TERMINAL_NODE_ID = GraphNodeId(4)
_ROOT_TO_LEFT_EDGE_ID = GraphEdgeId(0)
_ROOT_TO_RIGHT_EDGE_ID = GraphEdgeId(1)
_LEFT_TO_MERGED_EDGE_ID = GraphEdgeId(2)
_RIGHT_TO_MERGED_EDGE_ID = GraphEdgeId(3)
_MERGED_TO_ROOT_EDGE_ID = GraphEdgeId(4)
_MERGED_TO_TERMINAL_EDGE_ID = GraphEdgeId(5)


def _node(
    node_id: GraphNodeId,
    *,
    outcome: GraphNodeOutcome = GraphNodeOutcome.NON_TERMINAL,
    predecessor_node_id: GraphNodeId | None = None,
    predecessor_edge_id: GraphEdgeId | None = None,
) -> StateGraphNode:
    """构造探索测试只需读取 ID 的轻量状态图节点。

    Args:
        node_id: 当前测试图中的连续节点 ID。
        outcome: 节点的终局分类。
        predecessor_node_id: 图构建器首次发现节点时记录的代表前驱。
        predecessor_edge_id: 图构建器首次发现节点时记录的代表边。

    Returns:
        带有占位战斗状态和唯一状态键的不可变图节点。
    """
    return StateGraphNode(
        node_id=node_id,
        state=cast(BattleState, object()),
        state_key=cast(StateKey, ("test-state", int(node_id))),
        outcome=outcome,
        termination_reason=(
            TerminationReason.KNOCKOUT
            if outcome is GraphNodeOutcome.ATTACKER_WIN
            else None
        ),
        predecessor_node_id=predecessor_node_id,
        predecessor_edge_id=predecessor_edge_id,
    )


def _edge(
    edge_id: GraphEdgeId,
    source_node_id: GraphNodeId,
    target_node_id: GraphNodeId,
    probability: Fraction,
) -> StateGraphEdge:
    """构造一条具有精确概率的测试图边。

    Args:
        edge_id: 当前测试图中的连续边 ID。
        source_node_id: 边的起点节点 ID。
        target_node_id: 边的终点节点 ID。
        probability: 从起点选择该后继状态的精确概率。

    Returns:
        不附带随机事件详情的不可变状态图边。
    """
    return StateGraphEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        probability=probability,
        event_summary=TransitionEventSummary.empty(),
    )


def _build_exploration_graph() -> StateGraphBuildResult:
    """构建包含分叉、状态合流、循环回边和终局出口的测试图。

    Returns:
        路径结构为 ``root -> left/right -> merged -> root/terminal`` 的完整图。
    """
    nodes = (
        _node(_ROOT_NODE_ID),
        _node(
            _LEFT_NODE_ID,
            predecessor_node_id=_ROOT_NODE_ID,
            predecessor_edge_id=_ROOT_TO_LEFT_EDGE_ID,
        ),
        _node(
            _RIGHT_NODE_ID,
            predecessor_node_id=_ROOT_NODE_ID,
            predecessor_edge_id=_ROOT_TO_RIGHT_EDGE_ID,
        ),
        _node(
            _MERGED_NODE_ID,
            predecessor_node_id=_LEFT_NODE_ID,
            predecessor_edge_id=_LEFT_TO_MERGED_EDGE_ID,
        ),
        _node(
            _TERMINAL_NODE_ID,
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            predecessor_node_id=_MERGED_NODE_ID,
            predecessor_edge_id=_MERGED_TO_TERMINAL_EDGE_ID,
        ),
    )
    edges = (
        _edge(
            _ROOT_TO_LEFT_EDGE_ID,
            _ROOT_NODE_ID,
            _LEFT_NODE_ID,
            Fraction(1, 3),
        ),
        _edge(
            _ROOT_TO_RIGHT_EDGE_ID,
            _ROOT_NODE_ID,
            _RIGHT_NODE_ID,
            Fraction(2, 3),
        ),
        _edge(
            _LEFT_TO_MERGED_EDGE_ID,
            _LEFT_NODE_ID,
            _MERGED_NODE_ID,
            Fraction(1, 1),
        ),
        _edge(
            _RIGHT_TO_MERGED_EDGE_ID,
            _RIGHT_NODE_ID,
            _MERGED_NODE_ID,
            Fraction(1, 1),
        ),
        _edge(
            _MERGED_TO_ROOT_EDGE_ID,
            _MERGED_NODE_ID,
            _ROOT_NODE_ID,
            Fraction(1, 4),
        ),
        _edge(
            _MERGED_TO_TERMINAL_EDGE_ID,
            _MERGED_NODE_ID,
            _TERMINAL_NODE_ID,
            Fraction(3, 4),
        ),
    )
    components = (
        StrongComponent(
            component_id=StrongComponentId(0),
            node_ids=(
                _ROOT_NODE_ID,
                _LEFT_NODE_ID,
                _RIGHT_NODE_ID,
                _MERGED_NODE_ID,
            ),
            kind=StrongComponentKind.TERMINAL_REACHABLE_CYCLE,
            outgoing_component_ids=(StrongComponentId(1),),
            reaches_terminal=True,
        ),
        StrongComponent(
            component_id=StrongComponentId(1),
            node_ids=(_TERMINAL_NODE_ID,),
            kind=StrongComponentKind.ACYCLIC,
            outgoing_component_ids=(),
            reaches_terminal=True,
        ),
    )
    statistics = StateGraphStatistics(
        unique_state_count=len(nodes),
        edge_count=len(edges),
        max_turn_number=4,
        terminal_counts=StateGraphTerminalCounts(
            attacker_wins=1,
            defender_wins=0,
            draws=0,
            non_terminal=4,
            unknown=0,
        ),
        closed_cycle_count=0,
        terminal_reachable_cycle_count=1,
    )
    return StateGraphBuildResult(
        root_node_id=_ROOT_NODE_ID,
        nodes=nodes,
        edges=edges,
        components=components,
        statistics=statistics,
    )


def test_root_advance_and_probability_use_immutable_edge_sequence() -> None:
    """普通链应保留原游标，并使用 Fraction 累乘实际选择的边概率。"""
    use_case = StateGraphExplorationUseCase(
        graph_id="graph-a",
        graph=_build_exploration_graph(),
    )
    root = use_case.create_root_cursor()

    left_cursor = use_case.advance(root, _ROOT_TO_LEFT_EDGE_ID)
    merged_cursor = use_case.advance(left_cursor, _LEFT_TO_MERGED_EDGE_ID)

    assert root.depth == 0
    assert root.current_node_id == _ROOT_NODE_ID
    assert left_cursor.depth == 1
    assert merged_cursor.current_node_id == _MERGED_NODE_ID
    assert use_case.current_node(merged_cursor).node_id == _MERGED_NODE_ID
    assert use_case.cumulative_probability(root) == Fraction(1, 1)
    assert use_case.cumulative_probability(merged_cursor) == Fraction(1, 3)
    assert isinstance(use_case.cumulative_probability(merged_cursor), Fraction)


def test_branch_and_merge_keep_distinct_paths_to_same_state() -> None:
    """两条分支合流到同一节点时仍应保留不同的实际边序列。"""
    use_case = StateGraphExplorationUseCase(
        graph_id="graph-a",
        graph=_build_exploration_graph(),
    )
    root = use_case.create_root_cursor()

    left_path = use_case.advance(
        use_case.advance(root, _ROOT_TO_LEFT_EDGE_ID),
        _LEFT_TO_MERGED_EDGE_ID,
    )
    right_path = use_case.advance(
        use_case.advance(root, _ROOT_TO_RIGHT_EDGE_ID),
        _RIGHT_TO_MERGED_EDGE_ID,
    )

    assert left_path.current_node_id == right_path.current_node_id == _MERGED_NODE_ID
    assert left_path.steps != right_path.steps
    assert use_case.cumulative_probability(left_path) == Fraction(1, 3)
    assert use_case.cumulative_probability(right_path) == Fraction(2, 3)


def test_cycle_back_edge_can_reenter_root_without_predecessor_path() -> None:
    """循环路径应允许节点重复出现，并按实际回边重新进入根节点。"""
    use_case = StateGraphExplorationUseCase(
        graph_id="graph-a",
        graph=_build_exploration_graph(),
    )
    cursor = use_case.create_root_cursor()

    cursor = use_case.advance(cursor, _ROOT_TO_LEFT_EDGE_ID)
    cursor = use_case.advance(cursor, _LEFT_TO_MERGED_EDGE_ID)
    cursor = use_case.advance(cursor, _MERGED_TO_ROOT_EDGE_ID)

    assert cursor.current_node_id == _ROOT_NODE_ID
    assert tuple(step.source_node_id for step in cursor.steps) == (
        _ROOT_NODE_ID,
        _LEFT_NODE_ID,
        _MERGED_NODE_ID,
    )
    assert tuple(step.target_node_id for step in cursor.steps) == (
        _LEFT_NODE_ID,
        _MERGED_NODE_ID,
        _ROOT_NODE_ID,
    )
    assert use_case.cumulative_probability(cursor) == Fraction(1, 12)


def test_back_and_truncate_return_ancestor_cursors_and_reject_overflow() -> None:
    """回退与祖先跳转应返回新游标，并稳定拒绝根回退和越界深度。"""
    use_case = StateGraphExplorationUseCase(
        graph_id="graph-a",
        graph=_build_exploration_graph(),
    )
    root = use_case.create_root_cursor()
    cursor = use_case.advance(root, _ROOT_TO_LEFT_EDGE_ID)
    cursor = use_case.advance(cursor, _LEFT_TO_MERGED_EDGE_ID)
    cursor = use_case.advance(cursor, _MERGED_TO_ROOT_EDGE_ID)

    parent = use_case.back(cursor)
    first_step = use_case.truncate(cursor, 1)
    root_again = use_case.truncate(cursor, 0)

    assert cursor.depth == 3
    assert parent.depth == 2
    assert parent.current_node_id == _MERGED_NODE_ID
    assert first_step.depth == 1
    assert first_step.current_node_id == _LEFT_NODE_ID
    assert root_again == root
    with pytest.raises(ExplorationDepthError):
        use_case.back(root)
    with pytest.raises(ExplorationDepthError):
        use_case.truncate(cursor, -1)
    with pytest.raises(ExplorationDepthError):
        use_case.truncate(cursor, cursor.depth + 1)


def test_invalid_edges_broken_paths_and_cross_graph_cursors_are_rejected() -> None:
    """非法边、断裂步骤、伪造边映射和跨图游标应抛出稳定 application 异常。"""
    graph = _build_exploration_graph()
    use_case = StateGraphExplorationUseCase(graph_id="graph-a", graph=graph)
    other_graph = StateGraphExplorationUseCase(graph_id="graph-b", graph=graph)
    root = use_case.create_root_cursor()

    with pytest.raises(ExplorationEdgeError):
        use_case.advance(root, GraphEdgeId(len(graph.edges)))
    with pytest.raises(ExplorationEdgeError):
        use_case.advance(root, _LEFT_TO_MERGED_EDGE_ID)
    with pytest.raises(ExplorationGraphMismatchError):
        other_graph.validate(root)
    with pytest.raises(ExplorationPathError):
        ExplorationCursor(
            graph_id="graph-a",
            root_node_id=_ROOT_NODE_ID,
            steps=(
                ExplorationPathStep(
                    source_node_id=_ROOT_NODE_ID,
                    edge_id=_ROOT_TO_LEFT_EDGE_ID,
                    target_node_id=_LEFT_NODE_ID,
                ),
                ExplorationPathStep(
                    source_node_id=_RIGHT_NODE_ID,
                    edge_id=_RIGHT_TO_MERGED_EDGE_ID,
                    target_node_id=_MERGED_NODE_ID,
                ),
            ),
        )

    forged = ExplorationCursor(
        graph_id="graph-a",
        root_node_id=_ROOT_NODE_ID,
        steps=(
            ExplorationPathStep(
                source_node_id=_ROOT_NODE_ID,
                edge_id=_ROOT_TO_LEFT_EDGE_ID,
                target_node_id=_RIGHT_NODE_ID,
            ),
        ),
    )
    with pytest.raises(ExplorationPathError):
        use_case.validate(forged)
