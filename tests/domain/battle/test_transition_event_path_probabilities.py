"""验证等价状态归并后仍保留事件路径的精确条件概率。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
    merge_equivalent_transitions,
)


@dataclass(frozen=True, slots=True)
class _State:
    """提供归并测试所需的最小稳定状态键。"""

    key: str

    @property
    def state_key(self) -> str:
        """返回用于判断两个测试后继状态等价的稳定键。"""
        return self.key


def _event(outcome_id: str) -> TransitionEventSummary:
    """构造一个具有稳定结果标识的单事件路径摘要。

    Args:
        outcome_id: 区分两条随机历史的稳定结果标识。

    Returns:
        条件概率为 1 的单事件路径摘要。
    """
    return TransitionEventSummary.single(
        TransitionEvent(
            event_type=TransitionEventType.CUSTOM,
            event_id="test:event",
            outcome_id=outcome_id,
        )
    )


def test_merge_equivalent_transitions_preserves_unequal_path_probabilities() -> None:
    """验证不等概率分支归并后不会被错误解释为等概率事件路径。"""
    merged = merge_equivalent_transitions(
        (
            WeightedTransition(
                probability=Fraction(1, 4),
                state=_State("same"),
                event_summary=_event("not-triggered"),
            ),
            WeightedTransition(
                probability=Fraction(3, 4),
                state=_State("same"),
                event_summary=_event("triggered"),
            ),
        )
    )

    assert len(merged) == 1
    assert merged[0].probability == Fraction(1)
    assert merged[0].event_summary.path_probabilities == (
        Fraction(1, 4),
        Fraction(3, 4),
    )
    assert tuple(
        path[0].outcome_id for path in merged[0].event_summary.paths
    ) == ("not-triggered", "triggered")


def test_concatenate_multiplies_conditional_event_path_probabilities() -> None:
    """验证多级随机事件组合使用路径条件概率乘法而非路径数量平均。"""
    first = TransitionEventSummary(
        paths=(
            (_event("first-a").paths[0][0],),
            (_event("first-b").paths[0][0],),
        ),
        path_probabilities=(Fraction(1, 4), Fraction(3, 4)),
    )
    second = TransitionEventSummary(
        paths=(
            (_event("second-a").paths[0][0],),
            (_event("second-b").paths[0][0],),
        ),
        path_probabilities=(Fraction(2, 5), Fraction(3, 5)),
    )

    combined = first.concatenate(second)

    assert combined.path_probabilities == (
        Fraction(1, 10),
        Fraction(3, 20),
        Fraction(3, 10),
        Fraction(9, 20),
    )
    assert sum(combined.path_probabilities, start=Fraction(0)) == Fraction(1)
