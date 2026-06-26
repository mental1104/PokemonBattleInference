from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterable

from pokeop.domain.battle.context import BattleMove, BattlePokemon, MoveCategory
from pokeop.domain.models.types import Type, TypeHelper


DEFAULT_RANDOM_MULTIPLIERS: tuple[float, ...] = tuple(i / 100 for i in range(85, 101))


@dataclass(frozen=True)
class AppliedModifier:
    """
    记录一次伤害计算中实际应用过的修正项。

    multiplier 用于 STAB、属性克制、特性、道具这类固定倍率；
    min_multiplier/max_multiplier 用于随机伤害这种范围型修正。
    """

    key: str
    multiplier: float | None = None
    min_multiplier: float | None = None
    max_multiplier: float | None = None


@dataclass(frozen=True)
class DamageCalculationState:
    """
    伤害责任链在各节点之间传递的不可变计算状态。

    attacker、defender、move 是本次计算的输入快照；
    base_damage 是基础伤害节点产物；modifier 累乘 STAB、属性克制等非随机修正；
    rolls 和 applied_modifiers 是链路最终给 DamageRollResult 使用的输出。
    """

    attacker: BattlePokemon
    defender: BattlePokemon
    move: BattleMove
    base_damage: int = 0
    modifier: float = 1.0
    rolls: tuple[int, ...] = ()
    applied_modifiers: tuple[AppliedModifier, ...] = ()

    def with_base_damage(self, base_damage: int) -> "DamageCalculationState":
        """返回写入基础伤害的新状态，供 BaseDamageModifier 使用。"""
        return DamageCalculationState(
            attacker=self.attacker,
            defender=self.defender,
            move=self.move,
            base_damage=base_damage,
            modifier=self.modifier,
            rolls=self.rolls,
            applied_modifiers=self.applied_modifiers,
        )

    def with_multiplier(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回累乘一个倍率并追加对应修正记录的新状态。"""
        return DamageCalculationState(
            attacker=self.attacker,
            defender=self.defender,
            move=self.move,
            base_damage=self.base_damage,
            modifier=self.modifier * multiplier,
            rolls=self.rolls,
            applied_modifiers=self.applied_modifiers + (applied_modifier,),
        )

    def with_rolls(
        self,
        rolls: tuple[int, ...],
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回写入最终随机伤害档位并追加随机修正记录的新状态。"""
        return DamageCalculationState(
            attacker=self.attacker,
            defender=self.defender,
            move=self.move,
            base_damage=self.base_damage,
            modifier=self.modifier,
            rolls=rolls,
            applied_modifiers=self.applied_modifiers + (applied_modifier,),
        )


def calculate_stab_multiplier(move_type: Type, attacker_types: tuple[Type, ...]) -> float:
    """计算本系加成倍率：招式属性属于攻击方属性时为 1.5，否则为 1.0。"""
    return 1.5 if move_type in attacker_types else 1.0


def calculate_type_effectiveness(
    move_type: Type,
    defender_types: tuple[Type, ...],
) -> float:
    """计算招式属性打防守方一个或两个属性时的总克制倍率。"""
    multiplier = 1.0
    for defender_type in defender_types:
        multiplier *= TypeHelper.get_type_efficacy(move_type, defender_type) / 100.0
    return multiplier


def offensive_stat(attacker: BattlePokemon, move: BattleMove) -> int:
    """根据招式分类选择攻击方使用攻击还是特攻。"""
    if move.category is MoveCategory.PHYSICAL:
        return attacker.stats.attack
    if move.category is MoveCategory.SPECIAL:
        return attacker.stats.special_attack
    raise ValueError("status moves do not deal direct damage")


def defensive_stat(defender: BattlePokemon, move: BattleMove) -> int:
    """根据招式分类选择防守方使用防御还是特防。"""
    if move.category is MoveCategory.PHYSICAL:
        return defender.stats.defense
    if move.category is MoveCategory.SPECIAL:
        return defender.stats.special_defense
    raise ValueError("status moves do not deal direct damage")


def calculate_base_damage(
    *,
    level: int,
    power: int,
    attack: int,
    defense: int,
) -> int:
    """
    按现代宝可梦基础伤害公式计算未应用倍率前的伤害。

    这里只处理等级、威力、攻击和防御四个核心数值；
    STAB、属性克制、随机数、特性和道具都应由后续责任链节点处理。
    """
    if defense <= 0:
        raise ValueError("defense must be greater than 0")

    level_factor = floor((2 * level) / 5 + 2)
    scaled = floor(level_factor * power * attack / defense)
    return floor(scaled / 50) + 2


class DamageModifierChain:
    """
    伤害修正责任链的基类。

    每个节点只负责读取并返回 DamageCalculationState；
    子类通过重写 apply 实现自己的修正，handle 负责把状态继续传给下一个节点。
    """

    def __init__(self, next_link: "DamageModifierChain | None" = None) -> None:
        """初始化当前链节点，并可选指定下一个节点。"""
        self._next_link = next_link

    def set_next(self, next_link: "DamageModifierChain") -> "DamageModifierChain":
        """设置下一个链节点并返回它，方便连续组装责任链。"""
        self._next_link = next_link
        return next_link

    def handle(self, state: DamageCalculationState) -> DamageCalculationState:
        """执行当前节点的 apply，然后把新状态交给下一个节点。"""
        next_state = self.apply(state)
        if self._next_link is None:
            return next_state
        return self._next_link.handle(next_state)

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """默认节点不改变状态；子类通过重写它实现具体修正。"""
        return state


class BaseDamageModifier(DamageModifierChain):
    """责任链节点：计算未应用任何倍率前的基础伤害。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """根据攻击方等级、招式威力、攻防能力值写入 base_damage。"""
        return state.with_base_damage(
            calculate_base_damage(
                level=state.attacker.level,
                power=state.move.power,
                attack=offensive_stat(state.attacker, state.move),
                defense=defensive_stat(state.defender, state.move),
            )
        )


class StabModifier(DamageModifierChain):
    """责任链节点：应用攻击方本系招式加成。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """如果攻击方属性包含招式属性，则把总倍率乘以 1.5 并记录 STAB。"""
        multiplier = calculate_stab_multiplier(state.move.type, state.attacker.types)
        return state.with_multiplier(
            multiplier,
            AppliedModifier("stab", multiplier=multiplier),
        )


class TypeEffectivenessModifier(DamageModifierChain):
    """责任链节点：应用属性克制倍率。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """按防守方属性计算总克制倍率，并把它累乘到当前状态。"""
        multiplier = calculate_type_effectiveness(state.move.type, state.defender.types)
        return state.with_multiplier(
            multiplier,
            AppliedModifier("type_effectiveness", multiplier=multiplier),
        )


class RandomRollModifier(DamageModifierChain):
    """责任链节点：根据随机倍率生成最终伤害档位。"""

    def __init__(
        self,
        random_multipliers: tuple[float, ...] = DEFAULT_RANDOM_MULTIPLIERS,
        next_link: DamageModifierChain | None = None,
    ) -> None:
        """初始化随机档位节点，默认使用宝可梦 0.85 到 1.00 的 16 档随机数。"""
        super().__init__(next_link)
        if not random_multipliers:
            raise ValueError("random_multipliers must not be empty")
        self._random_multipliers = random_multipliers

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """把基础伤害和已累乘倍率映射成最终随机伤害 rolls。"""
        rolls = tuple(
            floor(state.base_damage * state.modifier * random_multiplier)
            for random_multiplier in self._random_multipliers
        )
        return state.with_rolls(
            rolls,
            AppliedModifier(
                "random",
                min_multiplier=self._random_multipliers[0],
                max_multiplier=self._random_multipliers[-1],
            ),
        )


def build_damage_chain(links: Iterable[DamageModifierChain]) -> DamageModifierChain:
    """按传入顺序串联责任链节点，并返回第一个节点作为链入口。"""
    iterator = iter(links)
    try:
        first = next(iterator)
    except StopIteration as exc:
        raise ValueError("damage chain must contain at least one link") from exc

    current = first
    for link in iterator:
        current = current.set_next(link)
    return first


def build_default_damage_chain() -> DamageModifierChain:
    """
    构建当前阶段默认伤害链。

    默认顺序是基础伤害 -> STAB -> 属性克制 -> 随机档位；
    后续道具、特性、天气等节点通常应插在属性克制和随机档位之间。
    """
    return build_damage_chain(
        (
            BaseDamageModifier(),
            StabModifier(),
            TypeEffectivenessModifier(),
            RandomRollModifier(),
        )
    )


__all__ = [
    "AppliedModifier",
    "BaseDamageModifier",
    "DEFAULT_RANDOM_MULTIPLIERS",
    "DamageCalculationState",
    "DamageModifierChain",
    "RandomRollModifier",
    "StabModifier",
    "TypeEffectivenessModifier",
    "build_damage_chain",
    "build_default_damage_chain",
    "calculate_base_damage",
    "calculate_stab_multiplier",
    "calculate_type_effectiveness",
    "defensive_stat",
    "offensive_stat",
]
