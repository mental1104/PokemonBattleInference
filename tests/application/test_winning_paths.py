"""验证胜利路径按配置与联合行动序列归并、分页并压缩循环。"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from pokeop.application.solver.models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.application.use_cases.winning_paths import (
    ListWinningPathGroupsUseCase,
    WinningPathWinner,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.state import BattleState
from pokeop.domain.battle.transitions import TransitionEvent
from tests.application.use_cases.battle_exploration_test_helpers import (
    GRAPH_ID,
    REVISION,
    edge,
    node,
    stored_store,
)
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


def _configured_root(ability: DamageAbility) -> BattleState:
    """创建仅替换攻击方特性的合法固定配置根状态。

    Args:
        ability: 用于验证配置隔离的攻击方特性。

    Returns:
        招式槽与新 spec 保持一致的完整根状态。
    """
    root = build_effect_test_battle_state()
    attacker = replace(
        root.attacker,
        spec=replace(root.attacker.spec, ability=ability),
    )
    return replace(root, attacker=attacker)


def _state(
    root: BattleState,
    *,
    attacker_hp_loss: int,
    defender_hp: int,
    turn_number: int,
) -> BattleState:
    """按 HP 和回合号创建测试图中的不可变状态节点。

    Args:
        root: 固定双方配置和规则的根状态。
        attacker_hp_loss: 相对根状态扣除的攻击方 HP。
        defender_hp: 防守方目标 HP。
        turn_number: 当前节点展示用回合号。

    Returns:
        保留配置、只替换动态 HP 和回合号的状态。
    """
    return replace(
        root,
        attacker=root.attacker.with_current_hp(
            root.attacker.current_hp - attacker_hp_loss
        ),
        defender=root.defender.with_current_hp(defender_hp),
        turn_number=turn_number,
    )


def _action_path(
    *,
    turn_number: int,
    attacker_move_id: int,
    defender_move_id: int,
    damage: int,
    source_identifier: str,
    fainted: bool = True,
) -> tuple[TransitionEvent, ...]:
    """构造包含双方选招、伤害和可选终局事实的结构化事件路径。

    Args:
        turn_number: 事件所属回合。
        attacker_move_id: 攻击方选择的招式 ID。
        defender_move_id: 防守方选择的招式 ID。
        damage: 当前替代历史的离散伤害值。
        source_identifier: 区分测试随机历史但不进入行动主键的来源。
        fainted: 是否追加防守方濒死事件；非终局边必须为 False。

    Returns:
        可由胜利路径投影读取的完整事件路径。
    """
    events: list[TransitionEvent] = [
        BattleEvent(
            kind=BattleEventKind.MOVE_SELECTED,
            turn_number=turn_number,
            actor=BattleSide.ATTACKER,
            move_id=attacker_move_id,
            source_identifier="policy",
        ),
        BattleEvent(
            kind=BattleEventKind.MOVE_SELECTED,
            turn_number=turn_number,
            actor=BattleSide.DEFENDER,
            move_id=defender_move_id,
            source_identifier="policy",
        ),
        BattleEvent(
            kind=BattleEventKind.DAMAGE,
            turn_number=turn_number,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=attacker_move_id,
            source_identifier=source_identifier,
            value=damage,
        ),
    ]
    if fainted:
        events.append(
            BattleEvent(
                kind=BattleEventKind.FAINTED,
                turn_number=turn_number,
                actor=BattleSide.DEFENDER,
                source_identifier=source_identifier,
            )
        )
    return tuple(events)


def _acyclic_graph(
    ability: DamageAbility = DamageAbility.MULTISCALE,
) -> StateGraphBuildResult:
    """构造三组胜利行动序列，其中两条随机图路径应归并为同组。"""
    root = _configured_root(ability)
    defender_max_hp = root.defender.current_hp
    nodes = (
        node(0, root),
        node(
            1,
            _state(root, attacker_hp_loss=0, defender_hp=0, turn_number=2),
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
        node(
            2,
            _state(root, attacker_hp_loss=1, defender_hp=0, turn_number=2),
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
        node(
            3,
            _state(root, attacker_hp_loss=2, defender_hp=0, turn_number=2),
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
        node(
            4,
            _state(
                root,
                attacker_hp_loss=0,
                defender_hp=defender_max_hp - 5,
                turn_number=2,
            ),
        ),
        node(
            5,
            _state(root, attacker_hp_loss=3, defender_hp=0, turn_number=3),
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
    )
    edges = (
        edge(
            0,
            0,
            1,
            Fraction(1, 8),
            (
                _action_path(
                    turn_number=1,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=10,
                    source_identifier="roll-10",
                ),
            ),
        ),
        edge(
            1,
            0,
            2,
            Fraction(3, 8),
            (
                _action_path(
                    turn_number=1,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=11,
                    source_identifier="roll-11",
                ),
            ),
        ),
        edge(
            2,
            0,
            3,
            Fraction(1, 4),
            (
                _action_path(
                    turn_number=1,
                    attacker_move_id=280,
                    defender_move_id=252,
                    damage=12,
                    source_identifier="fake-out",
                ),
            ),
        ),
        edge(
            3,
            0,
            4,
            Fraction(1, 4),
            (
                _action_path(
                    turn_number=1,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=5,
                    source_identifier="setup",
                    fainted=False,
                ),
            ),
        ),
        edge(
            4,
            4,
            5,
            Fraction(1, 1),
            (
                _action_path(
                    turn_number=2,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=20,
                    source_identifier="finish",
                ),
            ),
        ),
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=len(nodes),
            edge_count=len(edges),
            max_turn_number=3,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=4,
                defender_wins=0,
                draws=0,
                non_terminal=2,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )


def _cyclic_graph() -> StateGraphBuildResult:
    """构造带可出回边的图，显式胜利路径只覆盖未重复节点的一次退出。"""
    root = _configured_root(DamageAbility.MULTISCALE)
    middle = _state(
        root,
        attacker_hp_loss=0,
        defender_hp=root.defender.current_hp - 5,
        turn_number=2,
    )
    terminal = _state(root, attacker_hp_loss=0, defender_hp=0, turn_number=3)
    nodes = (
        node(0, root),
        node(1, middle),
        node(
            2,
            terminal,
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
    )
    edges = (
        edge(
            0,
            0,
            1,
            Fraction(1, 1),
            (
                _action_path(
                    turn_number=1,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=5,
                    source_identifier="enter",
                    fainted=False,
                ),
            ),
        ),
        edge(
            1,
            1,
            0,
            Fraction(1, 2),
            (
                _action_path(
                    turn_number=2,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=0,
                    source_identifier="repeat",
                    fainted=False,
                ),
            ),
        ),
        edge(
            2,
            1,
            2,
            Fraction(1, 2),
            (
                _action_path(
                    turn_number=2,
                    attacker_move_id=280,
                    defender_move_id=8,
                    damage=20,
                    source_identifier="exit",
                ),
            ),
        ),
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=3,
            edge_count=3,
            max_turn_number=3,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=1,
                defender_wins=0,
                draws=0,
                non_terminal=2,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=1,
        ),
    )


def test_groups_random_histories_by_joint_actions_and_pages_stably() -> None:
    """验证默认排序、随机历史归并、当前页覆盖率和游标无重复。"""
    store = stored_store(_acyclic_graph())
    use_case = ListWinningPathGroupsUseCase(store)

    first = use_case.execute(
        GRAPH_ID,
        REVISION,
        winner=WinningPathWinner.ATTACKER,
        limit=2,
    )

    assert [group.terminal_turn for group in first.path_groups] == [2, 2]
    assert first.path_groups[0].probability.numerator == "1"
    assert first.path_groups[0].probability.denominator == "2"
    assert first.path_groups[0].raw_path_count == 2
    assert first.path_groups[0].damage_values == (10, 11)
    assert first.returned_probability.numerator == "3"
    assert first.returned_probability.denominator == "4"
    assert first.returned_coverage is not None
    assert first.returned_coverage.numerator == "3"
    assert first.returned_coverage.denominator == "4"
    assert first.has_more is True
    assert first.next_cursor is not None
    assert first.query_complete is True

    second = use_case.execute(
        GRAPH_ID,
        REVISION,
        winner=WinningPathWinner.ATTACKER,
        limit=2,
        cursor=first.next_cursor,
    )

    assert len(second.path_groups) == 1
    assert second.path_groups[0].terminal_turn == 3
    assert second.path_groups[0].path_key not in {
        group.path_key for group in first.path_groups
    }
    assert second.has_more is False
    assert second.next_cursor is None


def test_configuration_identity_prevents_cross_configuration_path_merging() -> None:
    """验证相同行动序列在不同特性配置下产生不同配置键和路径键。"""
    multiscale = ListWinningPathGroupsUseCase(
        stored_store(_acyclic_graph(DamageAbility.MULTISCALE))
    ).execute(
        GRAPH_ID,
        REVISION,
        winner=WinningPathWinner.ATTACKER,
    )
    inner_focus = ListWinningPathGroupsUseCase(
        stored_store(_acyclic_graph(DamageAbility.INNER_FOCUS))
    ).execute(
        GRAPH_ID,
        REVISION,
        winner=WinningPathWinner.ATTACKER,
    )

    assert (
        multiscale.configuration.configuration_key
        != inner_focus.configuration.configuration_key
    )
    assert multiscale.path_groups[0].path_key != inner_focus.path_groups[0].path_key


def test_cycle_is_compressed_and_coverage_remains_conservative() -> None:
    """验证可出循环不会无限展开，且只报告显式有限胜利 walk 的概率覆盖。"""
    result = ListWinningPathGroupsUseCase(stored_store(_cyclic_graph())).execute(
        GRAPH_ID,
        REVISION,
        winner=WinningPathWinner.ATTACKER,
    )

    assert len(result.path_groups) == 1
    assert result.path_groups[0].probability.numerator == "1"
    assert result.path_groups[0].probability.denominator == "2"
    assert result.winner_probability is not None
    assert result.winner_probability.numerator == "1"
    assert result.winner_probability.denominator == "1"
    assert result.returned_coverage is not None
    assert result.returned_coverage.numerator == "1"
    assert result.returned_coverage.denominator == "2"
    assert [
        (item.source_node_id, item.edge_id, item.target_node_id)
        for item in result.cycle_references
    ] == [(1, 1, 0)]
    assert result.query_complete is False
    assert result.traversal_truncated is False
