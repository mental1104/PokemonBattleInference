from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContext
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import (
    AppliedModifier,
    DEFAULT_RANDOM_MULTIPLIERS,
    DamageCalculationState,
    build_default_damage_chain,
    calculate_base_damage,
)

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


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

# TODO 这里函数签名很奇怪啊，context如果传了就可以覆盖其他所有的值，然后context里面又把所有的attacker定义了一遍，有没有干净的函数签名？如果我后面又扩展了一个字段，Context类里得加，这个函数又得加。
def calculate_damage_rolls(
    *,
    attacker: BattlePokemon | None = None,
    defender: BattlePokemon | None = None,
    move: BattleMove | None = None,
    ruleset: "BattleRuleset | None" = None,
    environment: BattleEnvironment | None = None,
    context: DamageContext | None = None,
    is_critical: bool = False,
    is_spread_move: bool = False,
    is_protect_reduced: bool = False,
    is_multi_target_battle: bool = False,
) -> DamageRollResult:
    """
    使用默认伤害责任链计算一次招式的 16 档伤害。

    旧调用方式可以继续分别传 attacker、defender、move；新调用方式可以直接
    传 DamageContext，以携带 ruleset、weather、terrain 等统一上下文。
    """
    # TODO 这里是短路场景，但是在代码结构里面却占了大多数行，请你适当对该逻辑进行封装，同一行函数解决。
    if context is None:
        if attacker is None or defender is None or move is None:
            raise ValueError("attacker, defender and move are required without context")
        context = DamageContext(
            attacker=attacker,
            defender=defender,
            move=move,
            ruleset=ruleset,
            environment=environment or BattleEnvironment(),
            is_critical=is_critical,
            is_spread_move=is_spread_move,
            is_protect_reduced=is_protect_reduced,
            is_multi_target_battle=is_multi_target_battle,
        )

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
