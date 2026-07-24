from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

import pytest

from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    StateGraphBuildResult,
)
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationDepthError,
    ExplorationEdgeError,
    ExplorationGraphMismatchError,
    ExplorationPathError,
    ExplorationPathStep,
    StateGraphExplorationUseCase,
)
from pokeop.domain.battle.state import BattlePhase, BattleState, StateKey
from pokeop.domain.battle.transitions import WeightedTransition
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


@dataclass(frozen=True, slots=True)
class _MappingExpander:
    """按状态键返回测试预先声明的完整后继概率分布。

    Args:
        transitions_by_key: 每个非终局状态对应的带权后继状态元组。
    """

    transitions_by_key: dict[StateKey, tuple[WeightedTransition[BattleState], ...]]

    def expand(
        self,
        state: BattleState,
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """返回当前测试状态的完整后继集合。

        Args:
            state: 状态图构建器正在展开的不可变战斗状态。

        Returns:
            预先声明的带权后继元组；缺失状态返回空元组。
        """
        return self.transitions_by_key.get(state.state_key, ())


def _transition(
    state: BattleState,
    probability: Fraction,
) -> WeightedTransition[BattleState]:
    """把测试后继状态包装为精确概率转移。

    Args:
        state: 当前图边到达的不可变后继状态。
        probability: 当前节点完整随机分布中的精确边概率。

    Returns:
        不附加额外事件说明的 ``WeightedTransition``。
    """
    return WeightedTransition(probability=probability, state=state)


def _with_hp(
    state: BattleState,
    *,
    attacker_hp: int | None = None,
    defender_hp: int | None = None,
    turn_number: int | None = None,
    phase: BattlePhase | None = None,
) -> BattleState:
    """通过不可变替换构造具有指定 HP、回合和阶段的测试状态。

    Args:
        state: 作为其余战斗字段基线的状态。
        attacker_hp: 攻击方目标 HP；None 表示保持原值。
        defender_hp: 防守方目标 HP；None 表示保持原值。
        turn_number: 目标绝对回合号；None 表示保持原值。
        phase: 目标战斗阶段；None 表示保持原值。

    Returns:
        仅替换指定字段的新 ``BattleState``。
    """
    attacker = state.attacker
    defender = state.defender
    if attacker_hp is not None:
        attacker = attacker.with_current_hp(attacker_hp)
    if defender_hp is not None:
        defender = defender.with_current_hp(defender_hp)
    return replace(
        state,
        attacker=attacker,
        defender=defender,
        turn_number=state.turn_number if turn_number is None else turn_number,
        phase=state.phase if phase is None else phase,
    )


def _build_exploration_graph() -> StateGraphBuildResult:
    """构建同时包含分叉、状态合流、循环回边和终局出口的测试图。

    Returns:
        根节点分叉到两个状态、随后合流并可回到根节点的完整状态图。
    """
    root = build_effect_test_battle_state()
    left = _with_hp(
        root,
        attacker_hp=root.attacker.current_hp - 1,
        turn_number=2,
    )
    right = _with_hp(
        root,
        defender_hp=root.defender.current_hp - 1,
        turn_number=2,
    )
    merged = _with_hp(
        root,
        attacker_hp=root.attacker.current_hp - 1,
        defender_hp=root.defender.current_hp - 1,
        turn_number=3,
    )
    root_again = replace(root, turn_number=4)
    terminal = _with_hp(
        merged,
        defender_hp=0,
        turn_number=4,
        phase=BattlePhase.TERMINAL,
    )
    expander = _MappingExpander(
        {
            root.state_key: (
                _transition(left, Fraction(1, 3)),
                _transition(right, Fraction(2, 3)),
            ),
            left.state_key: (_transition(merged, Fraction(1, 1)),),
            right.state_key: (_transition(merged, Fraction(1, 1)),),
            merged.state_key: (
                _transition(root_again, Fraction(1, 4)),
                _transition(terminal, Fraction(3, 4)),
            ),
        }
    )
    return StateGraphBuilder(expander).build(root)


def _node_id_by_hp(
    graph: StateGraphBuildResult,
    *,
    attacker_hp: int,
    defender_hp: int,
) -> GraphNodeId:
    """按双方 HP 定位测试图中的唯一节点 ID。

    Args:
        graph: 待查询的测试状态图。
        attacker_hp: 目标攻击方当前 HP。
        defender_hp: 目标防守方当前 HP。

    Returns:
        唯一匹配双方 HP 的图节点 ID。
    """
    matches = tuple(
        node.node_id
        for node in graph.nodes
        if node.state.attacker.current_hp == attacker_hp
        and node.state.defender.current_hp == defender_hp
    )
    assert len(matches) == 1
    return matches[0]


def _edge_id(
    graph: StateGraphBuildResult,
    source_node_id: GraphNodeId,
    target_node_id: GraphNodeId,
) -> GraphEdgeId:
    """按起点和终点定位测试图中的唯一边 ID。

    Args:
        graph: 待查询的测试状态图。
        source_node_id: 目标边的起点节点 ID。
        target_node_id: 目标边的终点节点 ID。

    Returns:
        唯一匹配端点的图边 ID。
    """
    matches = tuple(
        edge.edge_id
        for edge in graph.edges
        if edge.source_node_id == source_node_id
        and edge.target_node_id == target_node_id
    )
    assert len(matches) == 1
    return matches[0]


def test_root_advance_and_probability_use_immutable_edge_sequence() -> None:
    """普通链应保留原游标，并使用 Fraction 累乘实际选择的边概率。"""
    graph = _build_exploration_graph()
    use_case = StateGraphExplorationUseCase(graph_id="graph-a", graph=graph)
    root = use_case.create_root_cursor()
    root_state = graph.node(graph.root_node_id).state
    left_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp,
    )
    merged_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp - 1,
    )

    left_cursor = use_case.advance(root, _edge_id(graph, graph.root_node_id, left_id))
    merged_cursor = use_case.advance(
        left_cursor,
        _edge_id(graph, left_id, merged_id),
    )

    assert root.depth == 0
    assert root.current_node_id == graph.root_node_id
    assert left_cursor.depth == 1
    assert merged_cursor.current_node_id == merged_id
    assert use_case.current_node(merged_cursor).node_id == merged_id
    assert use_case.cumulative_probability(root) == Fraction(1, 1)
    assert use_case.cumulative_probability(merged_cursor) == Fraction(1, 3)
    assert isinstance(use_case.cumulative_probability(merged_cursor), Fraction)


def test_branch_and_merge_keep_distinct_paths_to_same_state() -> None:
    """两条分支合流到同一节点时仍应保留不同的实际边序列。"""
    graph = _build_exploration_graph()
    use_case = StateGraphExplorationUseCase(graph_id="graph-a", graph=graph)
    root = use_case.create_root_cursor()
    root_state = graph.node(graph.root_node_id).state
    left_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp,
    )
    right_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp,
        defender_hp=root_state.defender.current_hp - 1,
    )
    merged_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp - 1,
    )

    left_path = use_case.advance(
        use_case.advance(root, _edge_id(graph, graph.root_node_id, left_id)),
        _edge_id(graph, left_id, merged_id),
    )
    right_path = use_case.advance(
        use_case.advance(root, _edge_id(graph, graph.root_node_id, right_id)),
        _edge_id(graph, right_id, merged_id),
    )

    assert left_path.current_node_id == right_path.current_node_id == merged_id
    assert left_path.steps != right_path.steps
    assert use_case.cumulative_probability(left_path) == Fraction(1, 3)
    assert use_case.cumulative_probability(right_path) == Fraction(2, 3)


def test_cycle_back_edge_can_reenter_root_without_predecessor_path() -> None:
    """循环路径应允许节点重复出现，并按实际回边重新进入根节点。"""
    graph = _build_exploration_graph()
    use_case = StateGraphExplorationUseCase(graph_id="graph-a", graph=graph)
    root = use_case.create_root_cursor()
    root_state = graph.node(graph.root_node_id).state
    left_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp,
    )
    merged_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp - 1,
    )

    cursor = use_case.advance(root, _edge_id(graph, graph.root_node_id, left_id))
    cursor = use_case.advance(cursor, _edge_id(graph, left_id, merged_id))
    cursor = use_case.advance(cursor, _edge_id(graph, merged_id, graph.root_node_id))

    assert cursor.current_node_id == graph.root_node_id
    assert tuple(step.source_node_id for step in cursor.steps) == (
        graph.root_node_id,
        left_id,
        merged_id,
    )
    assert tuple(step.target_node_id for step in cursor.steps) == (
        left_id,
        merged_id,
        graph.root_node_id,
    )
    assert use_case.cumulative_probability(cursor) == Fraction(1, 12)


def test_back_and_truncate_return_ancestor_cursors_and_reject_overflow() -> None:
    """回退与祖先跳转应返回新游标，并稳定拒绝根回退和越界深度。"""
    graph = _build_exploration_graph()
    use_case = StateGraphExplorationUseCase(graph_id="graph-a", graph=graph)
    root = use_case.create_root_cursor()
    root_state = graph.node(graph.root_node_id).state
    left_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp,
    )
    merged_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp - 1,
    )
    cursor = use_case.advance(root, _edge_id(graph, graph.root_node_id, left_id))
    cursor = use_case.advance(cursor, _edge_id(graph, left_id, merged_id))
    cursor = use_case.advance(cursor, _edge_id(graph, merged_id, graph.root_node_id))

    parent = use_case.back(cursor)
    first_step = use_case.truncate(cursor, 1)
    root_again = use_case.truncate(cursor, 0)

    assert cursor.depth == 3
    assert parent.depth == 2
    assert parent.current_node_id == merged_id
    assert first_step.depth == 1
    assert first_step.current_node_id == left_id
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
    root_state = graph.node(graph.root_node_id).state
    left_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp,
    )
    right_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp,
        defender_hp=root_state.defender.current_hp - 1,
    )
    merged_id = _node_id_by_hp(
        graph,
        attacker_hp=root_state.attacker.current_hp - 1,
        defender_hp=root_state.defender.current_hp - 1,
    )
    root_to_left = _edge_id(graph, graph.root_node_id, left_id)
    left_to_merged = _edge_id(graph, left_id, merged_id)

    with pytest.raises(ExplorationEdgeError):
        use_case.advance(root, GraphEdgeId(len(graph.edges)))
    with pytest.raises(ExplorationEdgeError):
        use_case.advance(root, left_to_merged)
    with pytest.raises(ExplorationGraphMismatchError):
        other_graph.validate(root)
    with pytest.raises(ExplorationPathError):
        ExplorationCursor(
            graph_id="graph-a",
            root_node_id=graph.root_node_id,
            steps=(
                ExplorationPathStep(
                    source_node_id=graph.root_node_id,
                    edge_id=root_to_left,
                    target_node_id=left_id,
                ),
                ExplorationPathStep(
                    source_node_id=right_id,
                    edge_id=left_to_merged,
                    target_node_id=merged_id,
                ),
            ),
        )

    forged = ExplorationCursor(
        graph_id="graph-a",
        root_node_id=graph.root_node_id,
        steps=(
            ExplorationPathStep(
                source_node_id=graph.root_node_id,
                edge_id=root_to_left,
                target_node_id=right_id,
            ),
        ),
    )
    with pytest.raises(ExplorationPathError):
        use_case.validate(forged)
