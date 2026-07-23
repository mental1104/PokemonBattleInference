from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from pokeop.application.solver.state_graph import (
    GraphNodeOutcome,
    GraphTruncationReason,
    StateGraphBuilder,
    StateGraphLimits,
    StrongComponentKind,
)
from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.inference_rules import CycleResolution
from pokeop.domain.battle.state import BattlePhase, BattleState, StateKey
from pokeop.domain.battle.transitions import WeightedTransition
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


@dataclass(frozen=True, slots=True)
class _MappingExpander:
    """按 ``StateKey`` 返回测试预先声明的完整状态转移分布。

    Args:
        transitions_by_key: 每个非终局状态键对应的带权后继状态元组。
            缺失键表示当前状态异常地没有任何合法行动。
    """

    transitions_by_key: dict[StateKey, tuple[WeightedTransition[BattleState], ...]]

    def expand(
        self,
        state: BattleState,
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """返回当前状态对应的测试转移，缺失时返回空集合。

        Args:
            state: 图构建器正在展开的正式不可变战斗状态。

        Returns:
            预先声明的完整精确转移元组；未配置状态返回空元组。
        """
        return self.transitions_by_key.get(state.state_key, ())


def _transition(
    state: BattleState,
    probability: Fraction = Fraction(1, 1),
) -> WeightedTransition[BattleState]:
    """把测试后继状态包装为精确带权转移。

    Args:
        state: 当前分支到达的不可变后继状态。
        probability: 当前完整随机事件中的精确分支概率。

    Returns:
        不附加解释事件的 ``WeightedTransition``。
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
    """通过不可变更新构造具有指定 HP、回合和阶段的测试状态。

    Args:
        state: 作为配置与其他动态字段基线的战斗状态。
        attacker_hp: 攻击方目标 HP；None 表示保持原值。
        defender_hp: 防守方目标 HP；None 表示保持原值。
        turn_number: 目标回合号；None 表示保持原值。
        phase: 目标粗粒度战斗阶段；None 表示保持原值。

    Returns:
        保留原配置并只替换指定字段的新 ``BattleState``。
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


def test_builds_acyclic_graph_and_marks_win_loss_terminal_nodes() -> None:
    """简单 DAG 应完整构建，并按双方 HP 标记胜负叶子。"""
    root = build_effect_test_battle_state()
    attacker_win = _with_hp(
        root,
        defender_hp=0,
        phase=BattlePhase.TERMINAL,
    )
    defender_win = _with_hp(
        root,
        attacker_hp=0,
        phase=BattlePhase.TERMINAL,
    )
    expander = _MappingExpander(
        {
            root.state_key: (
                _transition(attacker_win, Fraction(1, 2)),
                _transition(defender_win, Fraction(1, 2)),
            )
        }
    )

    result = StateGraphBuilder(expander).build(root)

    assert result.is_complete
    assert result.statistics.unique_state_count == 3
    assert result.statistics.edge_count == 2
    assert result.statistics.terminal_counts.attacker_wins == 1
    assert result.statistics.terminal_counts.defender_wins == 1
    assert result.statistics.terminal_counts.draws == 0
    assert result.representative_path(result.nodes[2].node_id) == (0, 2)
    assert all(
        component.kind is StrongComponentKind.ACYCLIC
        for component in result.components
    )


def test_reuses_two_loop_states_and_marks_closed_scc_as_draw() -> None:
    """两个状态互相回跳时只能创建两个节点，并由封闭 SCC 证明平局。"""
    state_a = build_effect_test_battle_state()
    state_b = _with_hp(
        state_a,
        attacker_hp=state_a.attacker.current_hp - 1,
        turn_number=2,
    )
    state_a_again = replace(state_a, turn_number=3)
    expander = _MappingExpander(
        {
            state_a.state_key: (_transition(state_b),),
            state_b.state_key: (_transition(state_a_again),),
        }
    )

    result = StateGraphBuilder(expander).build(state_a)

    assert result.is_complete
    assert result.statistics.unique_state_count == 2
    assert result.statistics.edge_count == 2
    assert result.statistics.closed_cycle_count == 1
    assert result.statistics.terminal_counts.draws == 2
    assert {node.outcome for node in result.nodes} == {GraphNodeOutcome.DRAW}
    assert {
        node.termination_reason for node in result.nodes
    } == {TerminationReason.CYCLE_GUARD}
    closed = tuple(
        component
        for component in result.components
        if component.kind is StrongComponentKind.CLOSED_CYCLE
    )
    assert len(closed) == 1
    assert closed[0].node_ids == (0, 1)


def test_cycle_with_terminal_exit_is_not_declared_draw() -> None:
    """循环只要存在终局出口，就必须保留为可吸收循环而不是直接判平。"""
    state_a = build_effect_test_battle_state()
    state_b = _with_hp(
        state_a,
        attacker_hp=state_a.attacker.current_hp - 1,
        turn_number=2,
    )
    state_a_again = replace(state_a, turn_number=3)
    attacker_win = _with_hp(
        state_b,
        defender_hp=0,
        turn_number=2,
        phase=BattlePhase.TERMINAL,
    )
    expander = _MappingExpander(
        {
            state_a.state_key: (_transition(state_b),),
            state_b.state_key: (
                _transition(state_a_again, Fraction(1, 2)),
                _transition(attacker_win, Fraction(1, 2)),
            ),
        }
    )

    result = StateGraphBuilder(expander).build(state_a)

    assert result.statistics.unique_state_count == 3
    assert result.statistics.terminal_reachable_cycle_count == 1
    assert result.statistics.terminal_counts.draws == 0
    assert result.statistics.terminal_counts.attacker_wins == 1
    cycle = tuple(
        component
        for component in result.components
        if component.kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE
    )
    assert len(cycle) == 1
    assert cycle[0].reaches_terminal
    assert {
        result.node(node_id).outcome for node_id in cycle[0].node_ids
    } == {GraphNodeOutcome.NON_TERMINAL}


def test_merges_duplicate_successors_before_creating_edges() -> None:
    """同一 ``StateKey`` 的多条随机分支应合并为一个节点和一条边。"""
    root = build_effect_test_battle_state()
    successor = _with_hp(
        root,
        attacker_hp=root.attacker.current_hp - 1,
        turn_number=2,
    )
    equivalent_successor = replace(successor, turn_number=20)
    expander = _MappingExpander(
        {
            root.state_key: (
                _transition(successor, Fraction(1, 2)),
                _transition(equivalent_successor, Fraction(1, 2)),
            )
        }
    )

    result = StateGraphBuilder(expander).build(root)

    assert result.statistics.unique_state_count == 2
    assert result.statistics.edge_count == 1
    assert result.edges[0].probability == Fraction(1, 1)
    assert result.nodes[1].predecessor_edge_id == result.edges[0].edge_id


def test_max_turns_marks_unknown_instead_of_draw() -> None:
    """回合保护触发时必须显式截断为 unknown，不能污染数学平局统计。"""
    root = build_effect_test_battle_state()
    over_limit = replace(root, turn_number=2)
    expander = _MappingExpander({over_limit.state_key: (_transition(root),)})

    result = StateGraphBuilder(
        expander,
        limits=StateGraphLimits(max_turns=1),
    ).build(over_limit)

    assert not result.is_complete
    assert result.truncation_reasons == (GraphTruncationReason.MAX_TURNS,)
    assert result.nodes[0].outcome is GraphNodeOutcome.UNKNOWN
    assert result.nodes[0].termination_reason is GraphTruncationReason.MAX_TURNS
    assert result.statistics.terminal_counts.draws == 0
    assert result.statistics.terminal_counts.unknown == 1


def test_node_limit_marks_source_unknown_without_partial_distribution() -> None:
    """节点资源不足时不得只写入完整随机分布的一部分。"""
    root = build_effect_test_battle_state()
    first = _with_hp(
        root,
        attacker_hp=root.attacker.current_hp - 1,
        turn_number=2,
    )
    second = _with_hp(
        root,
        defender_hp=root.defender.current_hp - 1,
        turn_number=2,
    )
    expander = _MappingExpander(
        {
            root.state_key: (
                _transition(first, Fraction(1, 2)),
                _transition(second, Fraction(1, 2)),
            )
        }
    )

    result = StateGraphBuilder(
        expander,
        limits=StateGraphLimits(max_nodes=2),
    ).build(root)

    assert not result.is_complete
    assert result.truncation_reasons == (GraphTruncationReason.MAX_NODES,)
    assert result.statistics.unique_state_count == 1
    assert result.statistics.edge_count == 0
    assert result.nodes[0].outcome is GraphNodeOutcome.UNKNOWN


def test_closed_cycle_can_remain_non_terminal_for_future_probability_solver() -> None:
    """规则要求吸收概率求解时，封闭 SCC 不应被图构建器抢先判平。"""
    state_a = build_effect_test_battle_state()
    rules = replace(
        state_a.rules,
        cycle_resolution=CycleResolution.SOLVE_ABSORPTION_PROBABILITY,
    )
    state_a = replace(state_a, rules=rules)
    state_b = _with_hp(
        state_a,
        attacker_hp=state_a.attacker.current_hp - 1,
        turn_number=2,
    )
    state_a_again = replace(state_a, turn_number=3)
    expander = _MappingExpander(
        {
            state_a.state_key: (_transition(state_b),),
            state_b.state_key: (_transition(state_a_again),),
        }
    )

    result = StateGraphBuilder(expander).build(state_a)

    assert result.is_complete
    assert result.statistics.closed_cycle_count == 1
    assert result.statistics.terminal_counts.draws == 0
    assert result.statistics.terminal_counts.non_terminal == 2
    closed = next(
        component
        for component in result.components
        if component.kind is StrongComponentKind.CLOSED_CYCLE
    )
    assert not closed.reaches_terminal


def test_empty_expansion_and_mutual_knockout_have_deterministic_draw_semantics() -> None:
    """异常无后继和双方同时濒死应分别给出稳定平局原因。"""
    root = build_effect_test_battle_state()
    no_action_result = StateGraphBuilder(_MappingExpander({})).build(root)
    mutual_knockout = _with_hp(
        root,
        attacker_hp=0,
        defender_hp=0,
        phase=BattlePhase.TERMINAL,
    )
    mutual_result = StateGraphBuilder(_MappingExpander({})).build(mutual_knockout)

    assert no_action_result.nodes[0].outcome is GraphNodeOutcome.DRAW
    assert (
        no_action_result.nodes[0].termination_reason
        is TerminationReason.NO_LEGAL_ACTION
    )
    assert mutual_result.nodes[0].outcome is GraphNodeOutcome.DRAW
    assert (
        mutual_result.nodes[0].termination_reason
        is TerminationReason.MUTUAL_KNOCKOUT
    )


def test_deep_chain_uses_explicit_stacks_instead_of_python_recursion() -> None:
    """超过默认递归深度的状态链仍应完成 BFS 与 SCC 分析。"""
    base = build_effect_test_battle_state()
    base = replace(base, rules=replace(base.rules, max_turns=None))
    states: list[BattleState] = []
    for index in range(1_100):
        attacker_hp = index % base.attacker.spec.stats.hp + 1
        defender_hp = (
            index // base.attacker.spec.stats.hp
        ) % base.defender.spec.stats.hp + 1
        states.append(
            _with_hp(
                base,
                attacker_hp=attacker_hp,
                defender_hp=defender_hp,
                turn_number=index + 1,
            )
        )
    transitions = {
        current.state_key: (_transition(following),)
        for current, following in zip(states, states[1:])
    }
    terminal = _with_hp(
        states[-1],
        defender_hp=0,
        phase=BattlePhase.TERMINAL,
    )
    transitions[states[-1].state_key] = (_transition(terminal),)

    result = StateGraphBuilder(_MappingExpander(transitions)).build(states[0])

    assert result.is_complete
    assert result.statistics.unique_state_count == 1_101
    assert result.statistics.edge_count == 1_100
    assert result.statistics.terminal_counts.attacker_wins == 1
    assert result.statistics.closed_cycle_count == 0
