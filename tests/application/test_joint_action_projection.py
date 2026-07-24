"""验证状态图联合行动投影与紧凑随机结果。"""

from __future__ import annotations

from fractions import Fraction

from pokeop.application.joint_action_metadata import with_joint_action_probability
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.application.state_graph_projection import StateGraphProjectionUseCase
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind, event_summary
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary, TransitionEventType
from tests.application.use_cases.battle_exploration_test_helpers import node
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


def _selected(move_id: int, side: BattleSide) -> BattleEvent:
    """构造一侧普通招式选择事件。"""
    return BattleEvent(
        kind=BattleEventKind.MOVE_SELECTED,
        turn_number=1,
        actor=side,
        target=(
            BattleSide.DEFENDER
            if side is BattleSide.ATTACKER
            else BattleSide.ATTACKER
        ),
        move_id=move_id,
        source_identifier="move",
    )


def _joint_path(
    attacker_move_id: int,
    defender_move_id: int,
    *,
    ordered_first: BattleSide = BattleSide.ATTACKER,
    roll_index: int | None = None,
    damage: int | None = None,
    cancel_defender: bool = False,
) -> tuple[TransitionEvent, ...]:
    """构造包含双方选择、顺序、离散伤害和可选后手取消的完整路径。"""
    ordered_second = (
        BattleSide.DEFENDER
        if ordered_first is BattleSide.ATTACKER
        else BattleSide.ATTACKER
    )
    events: list[TransitionEvent] = [
        _selected(attacker_move_id, BattleSide.ATTACKER),
        _selected(defender_move_id, BattleSide.DEFENDER),
        BattleEvent(
            kind=BattleEventKind.ACTION_ORDERED,
            turn_number=1,
            actor=ordered_first,
            value=1,
            source_identifier="move",
        ),
        BattleEvent(
            kind=BattleEventKind.ACTION_ORDERED,
            turn_number=1,
            actor=ordered_second,
            value=2,
            source_identifier="move",
        ),
        BattleEvent(
            kind=BattleEventKind.MOVE_USED,
            turn_number=1,
            actor=ordered_first,
            target=ordered_second,
            move_id=(attacker_move_id if ordered_first is BattleSide.ATTACKER else defender_move_id),
            source_identifier="move",
        ),
    ]
    if roll_index is not None and damage is not None:
        events.extend(
            (
                TransitionEvent(
                    event_type=TransitionEventType.DAMAGE_ROLL,
                    event_id="joint-damage",
                    outcome_id=f"roll-{roll_index}",
                    numeric_value=damage,
                ),
                BattleEvent(
                    kind=BattleEventKind.HIT,
                    turn_number=1,
                    actor=ordered_first,
                    target=ordered_second,
                    move_id=(attacker_move_id if ordered_first is BattleSide.ATTACKER else defender_move_id),
                    source_identifier="accuracy",
                ),
                BattleEvent(
                    kind=BattleEventKind.DAMAGE,
                    turn_number=1,
                    actor=ordered_first,
                    target=ordered_second,
                    move_id=(attacker_move_id if ordered_first is BattleSide.ATTACKER else defender_move_id),
                    source_identifier="move",
                    value=damage,
                ),
            )
        )
    if cancel_defender:
        events.append(
            BattleEvent(
                kind=BattleEventKind.FAINTED,
                turn_number=1,
                actor=BattleSide.DEFENDER,
                source_identifier="move",
            )
        )
    else:
        events.append(
            BattleEvent(
                kind=BattleEventKind.MOVE_USED,
                turn_number=1,
                actor=ordered_second,
                target=ordered_first,
                move_id=(defender_move_id if ordered_second is BattleSide.DEFENDER else attacker_move_id),
                source_identifier="move",
            )
        )
    return tuple(events)


def _graph(edges: tuple[StateGraphEdge, ...]) -> StateGraphBuildResult:
    """构造联合行动投影所需的最小连续状态图。"""
    state = build_effect_test_battle_state()
    nodes = (node(0, state), node(1, state.with_phase(state.phase)))
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=2,
            edge_count=len(edges),
            max_turn_number=1,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=0,
                defender_wins=0,
                draws=0,
                non_terminal=2,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )


def test_same_formal_edge_is_split_into_exact_joint_action_groups() -> None:
    """两个联合行动即使到达同一 StateKey，也必须按策略概率拆成两个一级组。"""
    first = with_joint_action_probability(
        event_summary(_joint_path(418, 8)),
        selection_probability=Fraction(1, 4),
        random_probability=Fraction(1, 1),
    ).paths[0]
    second = with_joint_action_probability(
        event_summary(_joint_path(999, 8)),
        selection_probability=Fraction(3, 4),
        random_probability=Fraction(1, 1),
    ).paths[0]
    graph = _graph(
        (
            StateGraphEdge(
                edge_id=GraphEdgeId(0),
                source_node_id=GraphNodeId(0),
                target_node_id=GraphNodeId(1),
                probability=Fraction(1, 1),
                event_summary=TransitionEventSummary((first, second)),
            ),
        )
    )

    collapsed = StateGraphProjectionUseCase("joint-actions", graph).project_node(
        GraphNodeId(0)
    )

    assert len(collapsed.transition_groups) == 2
    assert {
        group.attacker_action.move_id
        for group in collapsed.transition_groups
        if group.attacker_action is not None
    } == {418, 999}
    assert {
        (group.selection_probability.numerator, group.selection_probability.denominator)
        for group in collapsed.transition_groups
    } == {("1", "4"), ("3", "4")}
    assert all(group.distinct_outcome_count == 1 for group in collapsed.transition_groups)


def test_joint_action_outcomes_keep_conditional_probability_and_discrete_rolls() -> None:
    """同一联合行动的 16 档必须保留离散 roll，并与联合选择概率分开计算。"""
    paths = tuple(
        with_joint_action_probability(
            event_summary(
                _joint_path(
                    418,
                    8,
                    roll_index=index,
                    damage=10,
                    cancel_defender=True,
                )
            ),
            selection_probability=Fraction(1, 2),
            random_probability=Fraction(1, 1),
        ).paths[0]
        for index in range(16)
    )
    graph = _graph(
        (
            StateGraphEdge(
                edge_id=GraphEdgeId(0),
                source_node_id=GraphNodeId(0),
                target_node_id=GraphNodeId(1),
                probability=Fraction(1, 2),
                event_summary=TransitionEventSummary(paths),
            ),
            StateGraphEdge(
                edge_id=GraphEdgeId(1),
                source_node_id=GraphNodeId(0),
                target_node_id=GraphNodeId(0),
                probability=Fraction(1, 2),
                event_summary=with_joint_action_probability(
                    event_summary(_joint_path(999, 8)),
                    selection_probability=Fraction(1, 2),
                    random_probability=Fraction(1, 1),
                ),
            ),
        )
    )
    use_case = StateGraphProjectionUseCase("discrete-rolls", graph)
    collapsed = use_case.project_node(GraphNodeId(0))
    target_group = next(
        group
        for group in collapsed.transition_groups
        if group.attacker_action is not None and group.attacker_action.move_id == 418
    )

    expanded = use_case.project_node(
        GraphNodeId(0), expanded_group_ids=(target_group.group_id,)
    )
    outcome = next(
        group for group in expanded.transition_groups if group.group_id == target_group.group_id
    ).outcomes[0]

    assert outcome.probability.numerator == "1"
    assert outcome.joint_probability.numerator == "1"
    assert outcome.joint_probability.denominator == "2"
    assert outcome.raw_random_values == tuple(range(85, 101))
    assert len(outcome.compact_results) == 1
    compact = outcome.compact_results[0]
    assert compact.raw_roll_values == tuple(range(85, 101))
    assert compact.final_damage_values == (10,)
    defender_resolution = next(
        result for result in compact.action_resolutions if result.side == "defender"
    )
    assert defender_resolution.status == "cancelled"
    assert defender_resolution.reason == "fainted-before-action"
