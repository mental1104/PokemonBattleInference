"""验证行动概率绑定具体槽位身份，并随当前合法集合精确重分配。"""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from pokeop.domain.battle.action_policy import (
    ActionPolicy,
    ActionSelectionPolicy,
    FirstLegalActionPolicy,
    UniformRandomPolicy,
)
from pokeop.domain.battle.actions import (
    InvalidBattleAction,
    StandardLegalActionGenerator,
    UseMoveAction,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.turn_resolver import TurnResolver
from tests.domain.battle.test_choice_band_effect import _battle_state


@pytest.mark.parametrize("action_count", (4, 3, 1))
def test_uniform_random_policy_uses_exact_current_action_count(
    action_count: int,
) -> None:
    """验证合法具体行动数量为 4、3、1 时分别得到 1/4、1/3、1。"""
    legal_actions = tuple(
        UseMoveAction(
            side=BattleSide.ATTACKER,
            move_id=100 + index,
            slot_id=10 + index,
        )
        for index in range(action_count)
    )

    distribution = UniformRandomPolicy[UseMoveAction]().distribution_for(
        legal_actions
    )

    assert tuple(selection.action for selection in distribution.selections) == (
        legal_actions
    )
    assert tuple(
        selection.probability for selection in distribution.selections
    ) == (Fraction(1, action_count),) * action_count
    assert distribution.total_probability == Fraction(1)


def test_action_selection_policy_is_the_explicit_public_boundary() -> None:
    """验证新边界名称兼容既有协议，并明确 FIRST_LEGAL 仅用于测试或调试。"""
    policy = UniformRandomPolicy[str]()

    assert ActionSelectionPolicy is ActionPolicy
    assert isinstance(policy, ActionSelectionPolicy)
    assert "测试或调试" in FirstLegalActionPolicy[str]().description


def test_pp_disabled_and_choice_lock_redistribute_only_over_remaining_slots() -> None:
    """验证 PP、禁用和锁招过滤后，只在剩余具体槽位行动之间重新分配概率。"""
    state = _battle_state()
    generator = StandardLegalActionGenerator()
    policy = UniformRandomPolicy[UseMoveAction]()

    depleted = state.with_battler(
        BattleSide.ATTACKER,
        state.attacker.with_move_slot(
            state.attacker.move_slot(101).with_current_pp(0)
        ),
    )
    disabled = state.with_battler(
        BattleSide.ATTACKER,
        state.attacker.with_move_slot(
            state.attacker.move_slot(101).with_disabled()
        ),
    )
    locked = state.with_battler(
        BattleSide.ATTACKER,
        state.attacker.with_choice_lock(102),
    )

    for current in (depleted, disabled, locked):
        legal_actions = generator.generate(current, BattleSide.ATTACKER)
        distribution = policy.distribution_for(legal_actions)

        assert legal_actions == (
            UseMoveAction(
                side=BattleSide.ATTACKER,
                move_id=102,
                slot_id=102,
            ),
        )
        assert distribution.selections[0].action == legal_actions[0]
        assert distribution.selections[0].probability == Fraction(1)


def _reordered_state():
    """创建槽位顺序和槽位 ID 均不同于 move_id 顺序的战斗状态。"""
    state = _battle_state()
    attacker = replace(
        state.attacker,
        move_slots=(
            MoveSlotState(
                move_id=102,
                current_pp=5,
                max_pp=5,
                slot_id=20,
            ),
            MoveSlotState(
                move_id=101,
                current_pp=5,
                max_pp=5,
                slot_id=10,
            ),
        ),
    )
    return state.with_battler(BattleSide.ATTACKER, attacker)


def test_runtime_slot_order_is_preserved_after_state_updates() -> None:
    """验证战斗过程只更新目标槽位，不按 move_id 重新排序或重编号运行时槽位。"""
    reordered = _reordered_state()

    actions = StandardLegalActionGenerator().generate(
        reordered,
        BattleSide.ATTACKER,
    )
    updated = reordered.attacker.with_move_slot(
        reordered.attacker.move_slot(102).with_current_pp(4)
    )

    assert tuple(
        (slot.slot_id, slot.move_id)
        for slot in reordered.attacker.move_slots
    ) == ((20, 102), (10, 101))
    assert actions == (
        UseMoveAction(
            side=BattleSide.ATTACKER,
            move_id=102,
            slot_id=20,
        ),
        UseMoveAction(
            side=BattleSide.ATTACKER,
            move_id=101,
            slot_id=10,
        ),
    )
    assert tuple(
        (slot.slot_id, slot.move_id, slot.current_pp)
        for slot in updated.move_slots
    ) == ((20, 102, 4), (10, 101, 5))


def test_turn_resolver_consumes_pp_from_action_source_slot() -> None:
    """验证 resolver 使用行动携带的 slot_id 消费 PP，而不是重新按列表位置解释。"""
    state = _reordered_state()
    action = StandardLegalActionGenerator().generate(
        state,
        BattleSide.ATTACKER,
    )[0]

    consumed = TurnResolver._consume_action(state, action)

    assert consumed.attacker.move_slots[0].slot_id == 20
    assert consumed.attacker.move_slots[0].current_pp == 4
    assert consumed.attacker.move_slots[1].slot_id == 10
    assert consumed.attacker.move_slots[1].current_pp == 5


def test_turn_resolver_rejects_slot_and_move_identity_mismatch() -> None:
    """验证行动声明的源槽与 move_id 不一致时不会错误扣除其他招式 PP。"""
    state = _reordered_state()
    mismatched = UseMoveAction(
        side=BattleSide.ATTACKER,
        move_id=101,
        slot_id=20,
    )

    with pytest.raises(InvalidBattleAction, match="source move slot"):
        TurnResolver._consume_action(state, mismatched)
