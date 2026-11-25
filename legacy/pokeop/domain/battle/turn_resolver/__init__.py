"""提供绑定稳定源槽身份的完整回合解析入口。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.actions import (
    BattleAction,
    InvalidBattleAction,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.state import BattleState

from . import _core
from ._core import *  # noqa: F403


# structured_turn_resolver 复用这些模块内扩展点；模块迁移为同名包后仍需保持兼容。
_Branch = _core._Branch
_OrderedBranch = _core._OrderedBranch
_branches_to_transitions = _core._branches_to_transitions
_deterministic_transition = _core._deterministic_transition
_validate_accuracy_outcomes = _core._validate_accuracy_outcomes


@dataclass(frozen=True, slots=True)
class TurnResolver(_core.TurnResolver):
    """在既有回合管线上按 ``slot_id`` 校验并消费具体招式行动。"""

    @staticmethod
    def _consume_action(state: BattleState, action: BattleAction) -> BattleState:
        """扣除行动源槽一点 PP，并拒绝槽位与招式身份不一致的行动。

        Args:
            state: 扣除 PP 前的不可变战斗状态。
            action: 已通过合法行动和执行前 effect 校验的具体行动。

        Returns:
            更新源槽和 ``last_move_id`` 后的新状态；挣扎保持普通招式槽不变。

        Raises:
            InvalidBattleAction: 源槽不存在、槽位招式不匹配、招式不可用或 Pass 进入执行
                时抛出。
        """
        if isinstance(action, UseMoveAction):
            battler = state.battler(action.side)
            slot = next(
                (
                    candidate
                    for candidate in battler.move_slots
                    if candidate.slot_id == action.slot_id
                ),
                None,
            )
            if slot is None:
                raise InvalidBattleAction(
                    "selected action source slot is no longer present"
                )
            if slot.move_id != action.move_id:
                raise InvalidBattleAction(
                    "selected action no longer matches its source move slot"
                )
            if slot.current_pp <= 0 or slot.is_disabled:
                raise InvalidBattleAction(
                    "selected move became unusable before pp consumption"
                )
            if (
                battler.choice_lock_move_id is not None
                and battler.choice_lock_move_id != action.move_id
            ):
                raise InvalidBattleAction(
                    "selected move violates the current choice lock"
                )
            updated_battler = battler.with_move_slot(
                slot.with_current_pp(slot.current_pp - 1)
            ).with_last_move(action.move_id)
            return state.with_battler(action.side, updated_battler)
        if isinstance(action, StruggleAction):
            return state
        raise InvalidBattleAction("PassAction cannot enter move execution")


__all__ = _core.__all__
