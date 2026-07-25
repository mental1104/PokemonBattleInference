"""验证固定配置摘要状态图保持精确语义并避免预算后的无效扩展。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from fractions import Fraction

from pokeop.application.solver.models import (
    GraphNodeOutcome,
    GraphTruncationReason,
    StateGraphLimits,
)
from pokeop.application.solver.summary_state_graph import (
    SummaryStateGraphBuilder,
    merge_summary_transitions,
)
from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
)
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


@dataclass(slots=True)
class _CountingExpander:
    """按状态键返回预设转移，并记录实际发生的昂贵扩展次数。"""

    transitions_by_key: dict[StateKey, tuple[WeightedTransition[BattleState], ...]]
    expanded_keys: list[StateKey] = field(default_factory=list)

    def expand(
        self,
        state: BattleState,
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """记录当前状态键，并返回对应的完整后继分布。

        Args:
            state: 轻量构图器当前准备展开的不可变状态。

        Returns:
            预设的精确后继分布；缺失键表示异常无合法行动。
        """
        self.expanded_keys.append(state.state_key)
        return self.transitions_by_key.get(state.state_key, ())


def _with_hp(
    state: BattleState,
    *,
    attacker_delta: int = 0,
    defender_delta: int = 0,
    turn_number: int = 2,
) -> BattleState:
    """通过 HP 差异构造具有独立 ``StateKey`` 的非终局测试状态。"""
    return replace(
        state,
        attacker=state.attacker.with_current_hp(
            state.attacker.current_hp + attacker_delta
        ),
        defender=state.defender.with_current_hp(
            state.defender.current_hp + defender_delta
        ),
        turn_number=turn_number,
    )


def _transition(
    state: BattleState,
    probability: Fraction,
    event_summary: TransitionEventSummary | None = None,
) -> WeightedTransition[BattleState]:
    """把测试状态包装为精确带权后继。"""
    return WeightedTransition(
        probability=probability,
        state=state,
        event_summary=event_summary or TransitionEventSummary.empty(),
    )


def test_summary_merge_discards_event_paths_but_preserves_probability() -> None:
    """等价后继应归并为概率 1 的单边，同时不复制探索事件路径。"""
    root = build_effect_test_battle_state()
    successor = _with_hp(root, attacker_delta=-1)
    equivalent = replace(successor, turn_number=20)
    event = TransitionEvent(
        event_type=TransitionEventType.DAMAGE_ROLL,
        event_id="roll",
        outcome_id="85",
        numeric_value=10,
    )

    merged = merge_summary_transitions(
        (
            _transition(
                successor,
                Fraction(1, 2),
                TransitionEventSummary.single(event),
            ),
            _transition(
                equivalent,
                Fraction(1, 2),
                TransitionEventSummary.single(event),
            ),
        )
    )

    assert len(merged) == 1
    assert merged[0].probability == Fraction(1, 1)
    assert merged[0].event_summary == TransitionEventSummary.empty()
    assert merged[0].source_key is None


def test_edge_budget_stops_before_expanding_queued_states() -> None:
    """达到边预算后必须清空队列，不能继续解析注定不会写入的状态。"""
    root = build_effect_test_battle_state()
    first = _with_hp(root, attacker_delta=-1)
    second = _with_hp(root, defender_delta=-1)
    later = _with_hp(first, attacker_delta=-1, turn_number=3)
    expander = _CountingExpander(
        {
            root.state_key: (
                _transition(first, Fraction(1, 2)),
                _transition(second, Fraction(1, 2)),
            ),
            first.state_key: (_transition(later, Fraction(1, 1)),),
            second.state_key: (_transition(later, Fraction(1, 1)),),
        }
    )

    result = SummaryStateGraphBuilder(
        expander,
        limits=StateGraphLimits(max_edges=2),
    ).build(root)

    assert expander.expanded_keys == [root.state_key, first.state_key]
    assert result.truncation_reasons == (GraphTruncationReason.MAX_EDGES,)
    assert result.statistics.edge_count == 2
    assert result.nodes[1].outcome is GraphNodeOutcome.UNKNOWN
    assert result.nodes[2].outcome is GraphNodeOutcome.UNKNOWN


def test_empty_summary_expansion_keeps_no_legal_action_draw_semantics() -> None:
    """轻量摘要构图不能把无后继状态误报为概率分布异常。"""
    root = build_effect_test_battle_state()

    result = SummaryStateGraphBuilder(_CountingExpander({})).build(root)

    assert result.is_complete
    assert result.nodes[0].outcome is GraphNodeOutcome.DRAW
    assert result.nodes[0].termination_reason is TerminationReason.NO_LEGAL_ACTION
