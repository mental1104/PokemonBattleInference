from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias, runtime_checkable

from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.state import BattleState


class InvalidBattleAction(ValueError):
    """表示行动字段非法，或行动不属于当前合法行动集合。"""


@dataclass(frozen=True, slots=True)
class UseMoveAction:
    """表示一方从稳定运行时槽位使用已配置招式的类型化行动。

    Args:
        side: 执行行动的稳定战斗侧。
        move_id: ``PokemonSpec`` 中配置的正整数招式 ID。
        priority: 当前规则集下的招式优先级；生成器从 ``MoveSpec`` 复制该值。
        slot_id: 产生该行动的稳定运行时槽位 ID。零仅用于兼容旧构造调用，构造后
            会规范化为 move_id。策略概率绑定完整行动身份而不是列表位置。
    """

    side: BattleSide
    move_id: int
    priority: int = 0
    slot_id: int = 0

    def __post_init__(self) -> None:
        """校验行动侧、招式 ID、优先级和运行时槽位身份。

        Raises:
            InvalidBattleAction: 任一字段不满足稳定行动合同时抛出。
        """
        if not isinstance(self.side, BattleSide):
            raise InvalidBattleAction("action side must be a BattleSide")
        if isinstance(self.move_id, bool) or self.move_id <= 0:
            raise InvalidBattleAction("move_id must be greater than 0")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise InvalidBattleAction("move priority must be an integer")
        if self.slot_id == 0:
            object.__setattr__(self, "slot_id", self.move_id)
        elif isinstance(self.slot_id, bool) or self.slot_id <= 0:
            raise InvalidBattleAction("action slot_id must be greater than 0")


@dataclass(frozen=True, slots=True)
class StruggleAction:
    """表示当前没有其他合法招式时使用挣扎。

    Args:
        side: 执行挣扎的一方；挣扎不引用普通招式槽，也不会扣除槽位 PP。
    """

    side: BattleSide

    def __post_init__(self) -> None:
        """校验挣扎行动必须属于明确的战斗侧。"""
        if not isinstance(self.side, BattleSide):
            raise InvalidBattleAction("action side must be a BattleSide")


@dataclass(frozen=True, slots=True)
class PassAction:
    """表示已濒死等确定场景使用的内部占位行动。

    Args:
        side: 无法执行普通行动的一方。该行动只由合法行动生成器内部产生，策略不应
            在仍可行动时主动选择它。
    """

    side: BattleSide

    def __post_init__(self) -> None:
        """校验占位行动必须属于明确的战斗侧。"""
        if not isinstance(self.side, BattleSide):
            raise InvalidBattleAction("action side must be a BattleSide")


BattleAction: TypeAlias = UseMoveAction | StruggleAction | PassAction


@runtime_checkable
class LegalActionGenerator(Protocol):
    """根据完整不可变战斗状态生成一侧当前可供策略选择的行动。"""

    def generate(
        self,
        state: BattleState,
        side: BattleSide,
    ) -> tuple[BattleAction, ...]:
        """返回稳定、有序且非空的合法行动集合。

        Args:
            state: 当前 #21 ``BattleState`` 节点；生成过程不得修改它。
            side: 需要生成行动的一方。

        Returns:
            按运行时招式槽顺序排列的合法行动。已濒死时返回内部 ``PassAction``；
            没有任何可用普通招式时只返回 ``StruggleAction``。
        """


@dataclass(frozen=True, slots=True)
class StandardLegalActionGenerator:
    """实现首版 PP、禁用状态、讲究锁招和濒死场景的合法行动规则。"""

    def generate(
        self,
        state: BattleState,
        side: BattleSide,
    ) -> tuple[BattleAction, ...]:
        """从正式状态模型生成一侧合法行动。

        Args:
            state: 当前不可变战斗状态。
            side: 需要生成合法行动的一方。

        Returns:
            非空行动元组。讲究锁招存在时只保留被锁定且仍可使用的槽位；锁定槽位
            失效时回退到挣扎，而不是允许绕过锁招选择其他招式。

        Raises:
            InvalidBattleAction: 运行时状态包含重复 slot_id、无法形成唯一行动身份时抛出。
        """
        battler = state.battler(side)
        slot_ids = tuple(slot.slot_id for slot in battler.move_slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise InvalidBattleAction("runtime move slot ids must be unique")
        if battler.current_hp == 0:
            # 濒死方不会再进入普通行动选择，内部 Pass 让双方行动合同保持类型完整。
            return (PassAction(side=side),)

        usable_slots = tuple(
            slot
            for slot in battler.move_slots
            if slot.current_pp > 0 and not slot.is_disabled
        )
        if battler.choice_lock_move_id is not None:
            usable_slots = tuple(
                slot
                for slot in usable_slots
                if slot.move_id == battler.choice_lock_move_id
            )

        if not usable_slots:
            # 所有槽位均无 PP、被禁用或被锁招排除时，挣扎是唯一合法行动。
            return (StruggleAction(side=side),)

        return tuple(
            UseMoveAction(
                side=side,
                move_id=slot.move_id,
                priority=battler.spec.move_spec(slot.move_id).priority,
                slot_id=slot.slot_id,
            )
            for slot in usable_slots
        )


__all__ = [
    "BattleAction",
    "InvalidBattleAction",
    "LegalActionGenerator",
    "PassAction",
    "StandardLegalActionGenerator",
    "StruggleAction",
    "UseMoveAction",
]
