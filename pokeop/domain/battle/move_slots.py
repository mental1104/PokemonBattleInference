from __future__ import annotations

from dataclasses import dataclass, replace

from pokeop.domain.battle.specs import InvalidBattleState


@dataclass(frozen=True, slots=True)
class MoveSlotState:
    """表示一个招式槽在当前战斗节点中的动态状态。

    Args:
        move_id: 与 PokemonSpec 中 MoveSpec 对应的正整数招式 ID。
        current_pp: 当前剩余 PP，必须位于 0 到 max_pp。
        max_pp: 当前配置下的最大 PP，必须大于 0。
        is_disabled: 当前是否被禁用；禁用只影响合法行动，不改写 PP。
        is_locked: 当前是否为唯一锁定招式；首版仅用于讲究锁招一致性校验。
    """

    move_id: int
    current_pp: int
    max_pp: int
    is_disabled: bool = False
    is_locked: bool = False

    def __post_init__(self) -> None:
        """校验招式槽 ID 和 PP 范围。

        Raises:
            InvalidBattleState: ID、最大 PP 或当前 PP 不合法时抛出。
        """
        if isinstance(self.move_id, bool) or self.move_id <= 0:
            raise InvalidBattleState("move_id must be greater than 0")
        if isinstance(self.max_pp, bool) or self.max_pp <= 0:
            raise InvalidBattleState("max_pp must be greater than 0")
        if isinstance(self.current_pp, bool) or not 0 <= self.current_pp <= self.max_pp:
            raise InvalidBattleState("current_pp must be between 0 and max_pp")
        if not isinstance(self.is_disabled, bool):
            raise InvalidBattleState("is_disabled must be a bool")
        if not isinstance(self.is_locked, bool):
            raise InvalidBattleState("is_locked must be a bool")

    def with_current_pp(self, current_pp: int) -> "MoveSlotState":
        """返回只替换当前 PP 的新招式槽。

        Args:
            current_pp: 新的剩余 PP，仍必须位于 0 到 max_pp。

        Returns:
            通过构造期校验的新 MoveSlotState，原对象保持不变。
        """
        return replace(self, current_pp=current_pp)

    def with_disabled(self, disabled: bool = True) -> "MoveSlotState":
        """返回更新禁用状态的新招式槽。

        Args:
            disabled: True 表示招式当前不可选，False 表示解除禁用。

        Returns:
            更新后的新 MoveSlotState。
        """
        return replace(self, is_disabled=disabled)

    def with_locked(self, locked: bool = True) -> "MoveSlotState":
        """返回更新锁定标记的新招式槽。

        Args:
            locked: True 表示该槽是当前唯一锁定招式。

        Returns:
            更新后的新 MoveSlotState；整体锁定一致性由 BattlerState 校验。
        """
        return replace(self, is_locked=locked)


__all__ = ["MoveSlotState"]
