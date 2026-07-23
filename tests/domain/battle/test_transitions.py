from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from types import SimpleNamespace

import pytest

from pokeop.domain.battle.transitions import (
    EmptyTransitionSetError,
    InvalidStateKeyError,
    InvalidTransitionEventError,
    InvalidTransitionProbabilityError,
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    UnnormalizedTransitionSetError,
    WeightedTransition,
    branch_transitions,
    combine_independent_transitions,
    damage_rolls_to_transitions,
    merge_equivalent_transitions,
    normalize_transition_weights,
    total_transition_probability,
    validate_transition_distribution,
)


@dataclass(frozen=True, slots=True)
class FakeBattleState:
    """测试用不可变状态，只保留验证概率归并所需的 HP 和阶段。"""

    hp: int
    phase: str = "ready"
    speed_winner: str | None = None

    @property
    def state_key(self) -> tuple[int, str, str | None]:
        """返回与未来测试语义相关的稳定状态键。"""
        return (self.hp, self.phase, self.speed_winner)


@dataclass(frozen=True, slots=True)
class InvalidKeyState:
    """测试非法状态键错误语义的状态替身。"""

    @property
    def state_key(self) -> list[str]:
        """故意返回不可哈希列表，用于触发确定错误。"""
        return ["invalid"]


def _event(
    event_type: TransitionEventType,
    event_id: str,
    outcome_id: str,
    numeric_value: int | None = None,
) -> TransitionEventSummary:
    """构造测试分支使用的单事件摘要。

    Args:
        event_type: 随机事件类别。
        event_id: 当前事件来源的稳定标识。
        outcome_id: 当前分支结果的稳定标识。
        numeric_value: 可选的解释数值。

    Returns:
        只包含该事件的一条路径摘要。
    """
    return TransitionEventSummary.single(
        TransitionEvent(
            event_type=event_type,
            event_id=event_id,
            outcome_id=outcome_id,
            numeric_value=numeric_value,
        )
    )


def _deterministic(state: FakeBattleState) -> WeightedTransition[FakeBattleState]:
    """为条件分支测试创建概率为 1 的确定性转移。"""
    return WeightedTransition(probability=Fraction(1, 1), state=state)


@pytest.mark.parametrize(
    "probability",
    [0, Fraction(0, 1), Fraction(-1, 2), Fraction(3, 2), 0.5],
)
def test_weighted_transition_rejects_non_exact_or_out_of_range_probability(
    probability: object,
) -> None:
    """验证 0、负数、超过 1 和浮点概率都得到同一种确定错误。"""
    with pytest.raises(InvalidTransitionProbabilityError):
        WeightedTransition(
            probability=probability,  # type: ignore[arg-type]
            state=FakeBattleState(hp=10),
        )


def test_weighted_transition_rejects_unhashable_state_key() -> None:
    """验证状态归并只能依赖可哈希的稳定 ``state_key``。"""
    with pytest.raises(InvalidStateKeyError):
        WeightedTransition(
            probability=Fraction(1, 1),
            state=InvalidKeyState(),  # type: ignore[type-var]
        )


def test_empty_and_unnormalized_distributions_have_deterministic_errors() -> None:
    """验证空集合和总和不为 1 的完整随机分支不会被静默接受。"""
    with pytest.raises(EmptyTransitionSetError):
        validate_transition_distribution(())

    incomplete = (
        WeightedTransition(
            probability=Fraction(1, 3),
            state=FakeBattleState(hp=10, phase="left"),
        ),
        WeightedTransition(
            probability=Fraction(1, 3),
            state=FakeBattleState(hp=10, phase="right"),
        ),
    )
    with pytest.raises(UnnormalizedTransitionSetError):
        validate_transition_distribution(incomplete)


def test_normalize_transition_weights_preserves_exact_fraction_values() -> None:
    """验证待归一化精确权重会被缩放为严格总和 1 的概率。"""
    normalized = normalize_transition_weights(
        (
            WeightedTransition(
                probability=Fraction(1, 4),
                state=FakeBattleState(hp=10, phase="left"),
            ),
            WeightedTransition(
                probability=Fraction(1, 2),
                state=FakeBattleState(hp=10, phase="right"),
            ),
        )
    )

    assert [transition.probability for transition in normalized] == [
        Fraction(1, 3),
        Fraction(2, 3),
    ]
    assert total_transition_probability(normalized) == Fraction(1, 1)


def test_merge_equivalent_transitions_adds_probability_and_keeps_event_paths() -> None:
    """验证相同 ``state_key`` 的后继节点精确归并并保留两条解释路径。"""
    state = FakeBattleState(hp=0, phase="fainted")
    merged = merge_equivalent_transitions(
        (
            WeightedTransition(
                probability=Fraction(5, 16),
                state=state,
                event_summary=_event(
                    TransitionEventType.DAMAGE_ROLL,
                    "damage:test",
                    "roll-low",
                    10,
                ),
                source_key="damage.random-roll",
            ),
            WeightedTransition(
                probability=Fraction(11, 16),
                state=replace(state),
                event_summary=_event(
                    TransitionEventType.DAMAGE_ROLL,
                    "damage:test",
                    "roll-high",
                    20,
                ),
                source_key="damage.random-roll",
            ),
        )
    )

    assert len(merged) == 1
    assert merged[0].probability == Fraction(1, 1)
    assert len(merged[0].event_summary.paths) == 2
    assert merged[0].source_key == "damage.random-roll"


def test_composes_hit_damage_and_speed_tie_as_multi_level_exact_distribution() -> None:
    """验证命中、条件伤害和同速三层随机分支按乘法组合且总和严格为 1。"""
    hit_distribution = (
        WeightedTransition(
            probability=Fraction(3, 4),
            state=FakeBattleState(hp=10, phase="hit"),
            event_summary=_event(
                TransitionEventType.HIT_CHECK,
                "move:test:accuracy",
                "hit",
            ),
        ),
        WeightedTransition(
            probability=Fraction(1, 4),
            state=FakeBattleState(hp=10, phase="miss"),
            event_summary=_event(
                TransitionEventType.HIT_CHECK,
                "move:test:accuracy",
                "miss",
            ),
        ),
    )

    def damage_branch(
        state: FakeBattleState,
    ) -> tuple[WeightedTransition[FakeBattleState], ...]:
        """命中时产生两档伤害，未命中时保持确定性状态。"""
        if state.phase == "miss":
            return (_deterministic(state),)
        return (
            WeightedTransition(
                probability=Fraction(1, 2),
                state=FakeBattleState(hp=5, phase="damaged"),
                event_summary=_event(
                    TransitionEventType.DAMAGE_ROLL,
                    "move:test:damage",
                    "low",
                    5,
                ),
            ),
            WeightedTransition(
                probability=Fraction(1, 2),
                state=FakeBattleState(hp=0, phase="fainted"),
                event_summary=_event(
                    TransitionEventType.DAMAGE_ROLL,
                    "move:test:damage",
                    "high",
                    10,
                ),
            ),
        )

    after_damage = branch_transitions(
        hit_distribution,
        branch_factory=damage_branch,
    )
    assert sorted(transition.probability for transition in after_damage) == [
        Fraction(1, 4),
        Fraction(3, 8),
        Fraction(3, 8),
    ]

    speed_tie = (
        WeightedTransition(
            probability=Fraction(1, 2),
            state=FakeBattleState(hp=0, phase="speed", speed_winner="left"),
            event_summary=_event(
                TransitionEventType.SPEED_TIE,
                "turn:1:speed-tie",
                "left-first",
            ),
        ),
        WeightedTransition(
            probability=Fraction(1, 2),
            state=FakeBattleState(hp=0, phase="speed", speed_winner="right"),
            event_summary=_event(
                TransitionEventType.SPEED_TIE,
                "turn:1:speed-tie",
                "right-first",
            ),
        ),
    )

    combined = combine_independent_transitions(
        after_damage,
        speed_tie,
        state_combiner=lambda battle, speed: replace(
            battle,
            speed_winner=speed.speed_winner,
        ),
    )

    assert len(combined) == 6
    assert total_transition_probability(combined) == Fraction(1, 1)
    assert sorted(transition.probability for transition in combined) == [
        Fraction(1, 8),
        Fraction(1, 8),
        Fraction(3, 16),
        Fraction(3, 16),
        Fraction(3, 16),
        Fraction(3, 16),
    ]
    assert all(
        len(transition.event_summary.paths[0]) >= 2
        for transition in combined
    )


def test_damage_rolls_all_knock_out_merge_into_one_fainted_successor() -> None:
    """验证 16 个伤害档全部击倒目标时只保留一个概率为 1 的濒死节点。"""
    state = FakeBattleState(hp=8)
    damage_result = SimpleNamespace(rolls=tuple(range(8, 24)))

    def apply_damage(current: FakeBattleState, damage: int) -> FakeBattleState:
        """按 HP 下限 0 应用伤害，并在归零时写入濒死阶段。"""
        remaining_hp = max(0, current.hp - damage)
        return replace(
            current,
            hp=remaining_hp,
            phase="fainted" if remaining_hp == 0 else "ready",
        )

    transitions = damage_rolls_to_transitions(
        state=state,
        damage_result=damage_result,  # type: ignore[arg-type]
        apply_damage=apply_damage,
        event_id="move:test:damage-roll",
        source_key="damage.random-roll",
    )

    assert len(transitions) == 1
    assert transitions[0].state == FakeBattleState(hp=0, phase="fainted")
    assert transitions[0].probability == Fraction(1, 1)
    assert len(transitions[0].event_summary.paths) == 16
    assert {
        path[0].numeric_value for path in transitions[0].event_summary.paths
    } == set(range(8, 24))


def test_damage_roll_adapter_rejects_empty_or_negative_rolls() -> None:
    """验证伤害档位适配器不会接受空集合或负伤害。"""
    state = FakeBattleState(hp=10)

    with pytest.raises(EmptyTransitionSetError):
        damage_rolls_to_transitions(
            state=state,
            damage_result=SimpleNamespace(rolls=()),  # type: ignore[arg-type]
            apply_damage=lambda current, _: current,
            event_id="damage:empty",
        )

    with pytest.raises(InvalidTransitionEventError):
        damage_rolls_to_transitions(
            state=state,
            damage_result=SimpleNamespace(rolls=(-1,)),  # type: ignore[arg-type]
            apply_damage=lambda current, _: current,
            event_id="damage:negative",
        )
