from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.context import DamageContext
from pokeop.domain.battle.modifiers import (
    AppliedModifier,
    DEFAULT_RANDOM_MULTIPLIERS,
    DamageCalculationState,
    build_default_damage_chain,
    calculate_base_damage,
)


RANDOM_MULTIPLIERS = DEFAULT_RANDOM_MULTIPLIERS


@dataclass(frozen=True)
class DamageRollResult:
    """
    表示一次招式伤害计算的完整 16 档随机结果。

    rolls 保存已经应用基础伤害、STAB、属性克制和随机倍率后的每档伤害；
    defender_hp 用于把伤害换算成百分比；applied_modifiers 记录本次链路实际应用的修正项。
    """

    rolls: tuple[int, ...]
    defender_hp: int
    applied_modifiers: tuple[AppliedModifier, ...]

    @property
    def min_damage(self) -> int:
        """返回 16 档随机伤害中的最低伤害。"""
        return min(self.rolls)

    @property
    def max_damage(self) -> int:
        """返回 16 档随机伤害中的最高伤害。"""
        return max(self.rolls)

    @property
    def expected_damage(self) -> float:
        """返回 16 档随机伤害的算术平均值，作为本阶段的期望伤害。"""
        return sum(self.rolls) / len(self.rolls)

    @property
    def min_percent(self) -> float:
        """返回最低伤害占防守方 HP 的百分比。"""
        return self.min_damage / self.defender_hp * 100

    @property
    def max_percent(self) -> float:
        """返回最高伤害占防守方 HP 的百分比。"""
        return self.max_damage / self.defender_hp * 100

    @property
    def expected_percent(self) -> float:
        """返回期望伤害占防守方 HP 的百分比。"""
        return self.expected_damage / self.defender_hp * 100


def calculate_damage_rolls(context: DamageContext) -> DamageRollResult:
    """
    使用默认伤害责任链计算一次招式的 16 档伤害。

    多字段组装由 DamageContextBuilder 负责；这里保持计算入口只接收
    已归一化的 DamageContext。
    """
    state = build_default_damage_chain().handle(
        DamageCalculationState.from_context(context)
    )
    if not state.rolls:
        raise RuntimeError("damage chain did not produce any rolls")

    return DamageRollResult(
        rolls=state.rolls,
        defender_hp=context.defender.stats.hp,
        applied_modifiers=state.applied_modifiers,
    )


__all__ = [
    "DamageRollResult",
    "RANDOM_MULTIPLIERS",
    "calculate_base_damage",
    "calculate_damage_rolls",
]
