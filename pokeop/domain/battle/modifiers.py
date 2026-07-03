from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from math import floor
from typing import TYPE_CHECKING, Iterable

from pokeop.domain.battle.ability_effects import resolve_ability_effect
from pokeop.domain.battle.context import BattleMove, BattlePokemon, DamageContext, MoveCategory
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import is_grounded
from pokeop.domain.battle.item_effects import resolve_item_effect
from pokeop.domain.battle.terrain import Terrain, terrain_damage_boost_multiplier
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type, TypeHelper

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


DEFAULT_RANDOM_MULTIPLIERS: tuple[float, ...] = tuple(i / 100 for i in range(85, 101))


def _default_ruleset() -> "BattleRuleset":
    from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile

    return BattleRulesetProfile.modern()


class ModifierStage(str, Enum):
    """显式标识伤害修正在公式链路中的阶段。"""

    BASE_POWER = "base_power"
    ATTACK_STAT = "attack_stat"
    DEFENSE_STAT = "defense_stat"
    STAB = "stab"
    TYPE_EFFECTIVENESS = "type_effectiveness"
    SCREEN = "screen"
    CRITICAL = "critical"
    SPREAD = "spread"
    PROTECT = "protect"
    FINAL_DAMAGE = "final_damage"
    RANDOM = "random"


@dataclass(frozen=True)
class AppliedModifier:
    """
    记录一次伤害计算中实际应用过的修正项。

    multiplier 用于 STAB、属性克制、特性、道具这类固定倍率；
    min_multiplier/max_multiplier 用于随机伤害这种范围型修正。stage、source
    和 reason 让新增天气、场地、特性、道具可以进入统一 trace。
    """

    key: str
    multiplier: float | None = None
    min_multiplier: float | None = None
    max_multiplier: float | None = None
    stage: ModifierStage | None = None
    source: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class DamageCalculationState:
    """
    伤害责任链在各节点之间传递的不可变计算状态。

    attacker、defender、move 是本次计算的输入快照；ruleset 与 environment
    组成 DamageContext；base_power、attack_stat、defense_stat 保存阶段修正
    后的公式输入；base_damage、modifier、rolls 和 applied_modifiers 是链路
    最终给 DamageRollResult 使用的输出。
    """

    attacker: BattlePokemon
    defender: BattlePokemon
    move: BattleMove
    ruleset: "BattleRuleset | None" = None
    environment: BattleEnvironment = field(default_factory=BattleEnvironment)
    base_power: int | None = None
    attack_stat: int | None = None
    defense_stat: int | None = None
    base_damage: int = 0
    modifier: float = 1.0
    type_effectiveness: float = 1.0
    is_critical: bool = False
    is_spread_move: bool = False
    is_protect_reduced: bool = False
    is_multi_target_battle: bool = False
    rolls: tuple[int, ...] = ()
    applied_modifiers: tuple[AppliedModifier, ...] = ()

    @classmethod
    def from_context(cls, context: DamageContext) -> "DamageCalculationState":
        """从统一 DamageContext 构建责任链初始状态。"""
        return cls(
            attacker=context.attacker,
            defender=context.defender,
            move=context.move,
            ruleset=context.ruleset,
            environment=context.environment,
            is_critical=context.is_critical,
            is_spread_move=context.is_spread_move,
            is_protect_reduced=context.is_protect_reduced,
            is_multi_target_battle=context.is_multi_target_battle,
        )

    @property
    def active_ruleset(self) -> "BattleRuleset":
        """返回显式规则集或当前 domain 默认现代规则集。"""
        return self.ruleset or _default_ruleset()

    @property
    def context(self) -> DamageContext:
        """返回当前状态对应的统一伤害上下文。"""
        return DamageContext(
            attacker=self.attacker,
            defender=self.defender,
            move=self.move,
            ruleset=self.active_ruleset,
            environment=self.environment,
            is_critical=self.is_critical,
            is_spread_move=self.is_spread_move,
            is_protect_reduced=self.is_protect_reduced,
            is_multi_target_battle=self.is_multi_target_battle,
        )

    @property
    def effective_power(self) -> int:
        """返回经过 base power 阶段修正后的招式威力。"""
        return self.base_power if self.base_power is not None else self.move.power

    @property
    def effective_attack_stat(self) -> int:
        """返回经过 attack stat 阶段修正后的攻击或特攻。"""
        if self.attack_stat is not None:
            return self.attack_stat
        return offensive_stat(self.attacker, self.move)

    @property
    def effective_defense_stat(self) -> int:
        """返回经过 defense stat 阶段修正后的防御或特防。"""
        if self.defense_stat is not None:
            return self.defense_stat
        return defensive_stat(self.defender, self.move)

    def _with_modifier_record(
        self,
        applied_modifier: AppliedModifier,
        **changes: object,
    ) -> "DamageCalculationState":
        return replace(
            self,
            applied_modifiers=self.applied_modifiers + (applied_modifier,),
            **changes,
        )

    def with_base_power_multiplier(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回应用 base power 阶段倍率并记录 trace 的新状态。"""
        return self._with_modifier_record(
            applied_modifier,
            base_power=floor(self.effective_power * multiplier),
        )

    def with_attack_stat_multiplier(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回应用 attack stat 阶段倍率并记录 trace 的新状态。"""
        return self._with_modifier_record(
            applied_modifier,
            attack_stat=floor(self.effective_attack_stat * multiplier),
        )

    def with_defense_stat_multiplier(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回应用 defense stat 阶段倍率并记录 trace 的新状态。"""
        return self._with_modifier_record(
            applied_modifier,
            defense_stat=floor(self.effective_defense_stat * multiplier),
        )

    def with_base_damage(self, base_damage: int) -> "DamageCalculationState":
        """返回写入基础伤害的新状态，供 BaseDamageModifier 使用。"""
        return replace(self, base_damage=base_damage)

    def with_multiplier(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回累乘一个伤害倍率并追加对应修正记录的新状态。"""
        return self._with_modifier_record(
            applied_modifier,
            modifier=self.modifier * multiplier,
        )

    def with_type_effectiveness(
        self,
        multiplier: float,
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回写入属性克制倍率、累乘伤害倍率并追加记录的新状态。"""
        return self._with_modifier_record(
            applied_modifier,
            type_effectiveness=multiplier,
            modifier=self.modifier * multiplier,
        )

    def with_rolls(
        self,
        rolls: tuple[int, ...],
        applied_modifier: AppliedModifier,
    ) -> "DamageCalculationState":
        """返回写入最终随机伤害档位并追加随机修正记录的新状态。"""
        return self._with_modifier_record(applied_modifier, rolls=rolls)


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

    这里只处理等级、威力、攻击和防御四个核心数值；这些数值本身可以先由
    base power、attack stat、defense stat 阶段修正。
    """
    if defense <= 0:
        raise ValueError("defense must be greater than 0")

    level_factor = floor((2 * level) / 5 + 2)
    scaled = floor(level_factor * power * attack / defense)
    return floor(scaled / 50) + 2


def _applied_modifier(
    key: str,
    *,
    multiplier: float,
    stage: ModifierStage,
    source: str | None = None,
    reason: str = "",
) -> AppliedModifier:
    return AppliedModifier(
        key=key,
        multiplier=multiplier,
        stage=stage,
        source=source or key,
        reason=reason,
    )


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


class AbilityBasePowerModifier(DamageModifierChain):
    """责任链节点：应用会改变招式威力的攻击方特性。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现 Technician；未知或未生效特性保持 no-op。"""
        effect = resolve_ability_effect(state.attacker.ability)
        if effect is None:
            return state

        result = effect.base_power_multiplier(state.context)
        if result is None:
            return state
        return state.with_base_power_multiplier(
            result.multiplier,
            _applied_modifier(
                result.key,
                multiplier=result.multiplier,
                stage=ModifierStage.BASE_POWER,
                reason=result.reason,
            ),
        )


class ItemAttackStatModifier(DamageModifierChain):
    """责任链节点：应用会改变攻击或特攻数值的攻击方道具。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现 Choice Band 与 Choice Specs；未知或未生效道具保持 no-op。"""
        effect = resolve_item_effect(state.attacker.item)
        if effect is None:
            return state

        result = effect.attack_stat_multiplier(state.context)
        if result is None:
            return state
        return state.with_attack_stat_multiplier(
            result.multiplier,
            _applied_modifier(
                result.key,
                multiplier=result.multiplier,
                stage=ModifierStage.ATTACK_STAT,
                reason=result.reason,
            ),
        )


class EnvironmentDefenseStatModifier(DamageModifierChain):
    """责任链节点：应用会改变防御或特防数值的天气。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现沙暴岩石特防和现代雪天冰属性物防修正。"""
        weather = state.environment.weather
        policy = state.active_ruleset.damage_policy
        sandstorm_multiplier = policy.sandstorm_rock_spdef_multiplier
        if (
            weather is Weather.SANDSTORM
            and sandstorm_multiplier is not None
            and state.move.category is MoveCategory.SPECIAL
            and Type.ROCK in state.defender.types
        ):
            return state.with_defense_stat_multiplier(
                sandstorm_multiplier,
                _applied_modifier(
                    "weather:sandstorm",
                    multiplier=sandstorm_multiplier,
                    stage=ModifierStage.DEFENSE_STAT,
                    reason="Sandstorm boosts Rock-type Special Defense.",
                ),
            )

        snow_multiplier = policy.snow_ice_defense_multiplier
        if (
            weather is Weather.SNOW
            and snow_multiplier is not None
            and state.move.category is MoveCategory.PHYSICAL
            and Type.ICE in state.defender.types
        ):
            return state.with_defense_stat_multiplier(
                snow_multiplier,
                _applied_modifier(
                    "weather:snow",
                    multiplier=snow_multiplier,
                    stage=ModifierStage.DEFENSE_STAT,
                    reason="Modern snow boosts Ice-type Defense.",
                ),
            )

        hail_multiplier = policy.hail_ice_defense_multiplier
        if (
            weather is Weather.HAIL
            and hail_multiplier is not None
            and state.move.category is MoveCategory.PHYSICAL
            and Type.ICE in state.defender.types
        ):
            return state.with_defense_stat_multiplier(
                hail_multiplier,
                _applied_modifier(
                    "weather:hail",
                    multiplier=hail_multiplier,
                    stage=ModifierStage.DEFENSE_STAT,
                    reason="Hail boosts Ice-type Defense when enabled by policy.",
                ),
            )

        return state


class ItemDefenseStatModifier(DamageModifierChain):
    """责任链节点：应用会改变防御或特防数值的防守方道具。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现 Eviolite；未知或未生效道具保持 no-op。"""
        effect = resolve_item_effect(state.defender.item)
        if effect is None:
            return state

        result = effect.defense_stat_multiplier(state.context)
        if result is None:
            return state
        return state.with_defense_stat_multiplier(
            result.multiplier,
            _applied_modifier(
                result.key,
                multiplier=result.multiplier,
                stage=ModifierStage.DEFENSE_STAT,
                reason=result.reason,
            ),
        )


class BaseDamageModifier(DamageModifierChain):
    """责任链节点：计算未应用伤害倍率前的基础伤害。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """根据等级、阶段修正后的威力、攻击和防御写入 base_damage。"""
        return state.with_base_damage(
            calculate_base_damage(
                level=state.attacker.level,
                power=state.effective_power,
                attack=state.effective_attack_stat,
                defense=state.effective_defense_stat,
            )
        )


class StabModifier(DamageModifierChain):
    """责任链节点：应用攻击方本系招式加成。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """如果攻击方属性包含招式属性，则应用 STAB；Adaptability 可改写倍率。"""
        multiplier = calculate_stab_multiplier(state.move.type, state.attacker.types)
        source = "stab"
        reason = "Same-type attack bonus."

        effect = resolve_ability_effect(state.attacker.ability)
        if effect is not None:
            result = effect.stab_multiplier(state.context)
            if result is not None:
                multiplier = result.multiplier
                source = result.key
                reason = result.reason

        return state.with_multiplier(
            multiplier,
            _applied_modifier(
                "stab",
                multiplier=multiplier,
                stage=ModifierStage.STAB,
                source=source,
                reason=reason,
            ),
        )


class TypeEffectivenessModifier(DamageModifierChain):
    """责任链节点：应用属性克制倍率。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """按防守方属性计算总克制倍率，并把它累乘到当前状态。"""
        multiplier = calculate_type_effectiveness(state.move.type, state.defender.types)
        return state.with_type_effectiveness(
            multiplier,
            _applied_modifier(
                "type_effectiveness",
                multiplier=multiplier,
                stage=ModifierStage.TYPE_EFFECTIVENESS,
                reason="Type effectiveness multiplier.",
            ),
        )


class ScreenDamageModifier(DamageModifierChain):
    """责任链节点：应用防守方一侧屏障类减伤。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """Reflect、Light Screen 和 Aurora Veil 在会心时被忽略。"""
        if state.is_critical:
            return state

        policy = state.active_ruleset.damage_policy
        defender_side = state.environment.defender_side
        screen_multiplier = (
            policy.screen_multi_target_multiplier
            if state.is_multi_target_battle
            else policy.screen_single_target_multiplier
        )
        aurora_multiplier = (
            policy.aurora_veil_multi_target_multiplier
            if state.is_multi_target_battle
            else policy.aurora_veil_single_target_multiplier
        )

        next_state = state
        if defender_side.reflect and state.move.category is MoveCategory.PHYSICAL:
            next_state = next_state.with_multiplier(
                screen_multiplier,
                _applied_modifier(
                    "screen:reflect",
                    multiplier=screen_multiplier,
                    stage=ModifierStage.SCREEN,
                    reason="Reflect reduces physical direct damage on defender side.",
                ),
            )

        if defender_side.light_screen and state.move.category is MoveCategory.SPECIAL:
            next_state = next_state.with_multiplier(
                screen_multiplier,
                _applied_modifier(
                    "screen:light_screen",
                    multiplier=screen_multiplier,
                    stage=ModifierStage.SCREEN,
                    reason="Light Screen reduces special direct damage on defender side.",
                ),
            )

        if (
            defender_side.aurora_veil
            and state.move.category in (MoveCategory.PHYSICAL, MoveCategory.SPECIAL)
        ):
            next_state = next_state.with_multiplier(
                aurora_multiplier,
                _applied_modifier(
                    "screen:aurora_veil",
                    multiplier=aurora_multiplier,
                    stage=ModifierStage.SCREEN,
                    reason="Aurora Veil reduces physical and special direct damage on defender side.",
                ),
            )

        return next_state


class CriticalHitModifier(DamageModifierChain):
    """责任链节点：应用会心一击直接伤害倍率。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """应用 ruleset 会心倍率；Sniper 可在同一 critical 阶段改写该倍率。"""
        if not state.is_critical:
            return state

        multiplier = state.active_ruleset.damage_policy.critical_hit_multiplier
        source = "critical_hit"
        reason = "Critical hit direct damage multiplier."
        effect = resolve_ability_effect(state.attacker.ability)
        if effect is not None:
            result = effect.critical_hit_multiplier(state.context, multiplier)
            if result is not None:
                multiplier = result.multiplier
                source = result.key
                reason = result.reason

        return state.with_multiplier(
            multiplier,
            _applied_modifier(
                "critical_hit",
                multiplier=multiplier,
                stage=ModifierStage.CRITICAL,
                source=source,
                reason=reason,
            ),
        )


class SpreadMoveModifier(DamageModifierChain):
    """责任链节点：应用当前场景中多目标招式的伤害修正。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """is_spread_move 只表达当前命中场景，不读取 move metadata 或目标选择。"""
        if not state.is_spread_move:
            return state

        multiplier = state.active_ruleset.damage_policy.spread_move_multiplier
        return state.with_multiplier(
            multiplier,
            _applied_modifier(
                "spread_move",
                multiplier=multiplier,
                stage=ModifierStage.SPREAD,
                reason="Spread move damage multiplier for this target.",
            ),
        )


class ProtectDamageModifier(DamageModifierChain):
    """责任链节点：应用保护类穿透伤害减免 hook。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """This is not a full Protect action gate; it only models damage reduction."""
        if not state.is_protect_reduced:
            return state

        multiplier = state.active_ruleset.damage_policy.protect_damage_multiplier
        return state.with_multiplier(
            multiplier,
            _applied_modifier(
                "protect_reduction",
                multiplier=multiplier,
                stage=ModifierStage.PROTECT,
                reason="Protect-style damage reduction hook.",
            ),
        )


class WeatherFinalDamageModifier(DamageModifierChain):
    """责任链节点：应用天气造成的 final damage 阶段修正。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现晴天/雨天对火系与水系招式的直接伤害修正。"""
        weather = state.environment.weather
        policy = state.active_ruleset.damage_policy
        multiplier: float | None = None
        reason = ""
        if weather is Weather.HARSH_SUNLIGHT and state.move.type is Type.FIRE:
            multiplier = policy.weather_boost_multiplier
            reason = "Harsh sunlight boosts Fire-type damage."
        elif weather is Weather.HARSH_SUNLIGHT and state.move.type is Type.WATER:
            multiplier = policy.weather_weaken_multiplier
            reason = "Harsh sunlight weakens Water-type damage."
        elif weather is Weather.RAIN and state.move.type is Type.WATER:
            multiplier = policy.weather_boost_multiplier
            reason = "Rain boosts Water-type damage."
        elif weather is Weather.RAIN and state.move.type is Type.FIRE:
            multiplier = policy.weather_weaken_multiplier
            reason = "Rain weakens Fire-type damage."

        if multiplier is None or weather is None:
            return state

        return state.with_multiplier(
            multiplier,
            _applied_modifier(
                f"weather:{weather.value}",
                multiplier=multiplier,
                stage=ModifierStage.FINAL_DAMAGE,
                reason=reason,
            ),
        )


class TerrainFinalDamageModifier(DamageModifierChain):
    """责任链节点：应用场地造成的 final damage 阶段修正。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现四种场地的直接伤害增减，并使用最小 grounded 判定。"""
        terrain = state.environment.terrain
        if terrain is None:
            return state

        boost_multiplier = terrain_damage_boost_multiplier(state.active_ruleset)
        terrain_boosts: dict[Terrain, Type] = {
            Terrain.ELECTRIC: Type.ELECTRIC,
            Terrain.PSYCHIC: Type.PSYCHIC,
            Terrain.GRASSY: Type.GRASS,
        }

        boosted_type = terrain_boosts.get(terrain)
        if (
            boosted_type is not None
            and state.move.type is boosted_type
            and is_grounded(state.attacker, state.environment)
        ):
            return state.with_multiplier(
                boost_multiplier,
                _applied_modifier(
                    f"terrain:{terrain.value}",
                    multiplier=boost_multiplier,
                    stage=ModifierStage.FINAL_DAMAGE,
                    reason=f"{terrain.value} boosts grounded matching-type attacks.",
                ),
            )

        if (
            terrain is Terrain.MISTY
            and state.move.type is Type.DRAGON
            and is_grounded(state.defender, state.environment)
        ):
            multiplier = state.active_ruleset.damage_policy.misty_terrain_dragon_multiplier
            return state.with_multiplier(
                multiplier,
                _applied_modifier(
                    "terrain:misty_terrain",
                    multiplier=multiplier,
                    stage=ModifierStage.FINAL_DAMAGE,
                    reason="Misty Terrain weakens Dragon-type damage to grounded defenders.",
                ),
            )

        return state


class AbilityFinalDamageModifier(DamageModifierChain):
    """责任链节点：应用防守方特性的 final damage 阶段修正。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现 Thick Fat、Filter 和 Solid Rock；未知特性保持 no-op。"""
        effect = resolve_ability_effect(state.defender.ability)
        if effect is None:
            return state

        result = effect.final_damage_multiplier(
            state.context,
            state.type_effectiveness,
        )
        if result is None:
            return state
        return state.with_multiplier(
            result.multiplier,
            _applied_modifier(
                result.key,
                multiplier=result.multiplier,
                stage=ModifierStage.FINAL_DAMAGE,
                reason=result.reason,
            ),
        )


class ItemFinalDamageModifier(DamageModifierChain):
    """责任链节点：应用攻击方道具的 final damage 阶段修正。"""

    def apply(self, state: DamageCalculationState) -> DamageCalculationState:
        """当前实现 Life Orb 与 Expert Belt；未知或未生效道具保持 no-op。"""
        effect = resolve_item_effect(state.attacker.item)
        if effect is None:
            return state

        result = effect.final_damage_multiplier(
            state.context,
            state.type_effectiveness,
        )
        if result is None:
            return state
        return state.with_multiplier(
            result.multiplier,
            _applied_modifier(
                result.key,
                multiplier=result.multiplier,
                stage=ModifierStage.FINAL_DAMAGE,
                reason=result.reason,
            ),
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
                stage=ModifierStage.RANDOM,
                source="random",
                reason="Pokemon damage random roll range.",
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

    默认顺序显式区分 base power、attack stat、defense stat、基础伤害、
    STAB、属性克制、final damage 和随机档位；后续新增特性/道具通常只扩展
    对应 source resolver 或新增同阶段节点，不需要改写基础伤害公式。
    """
    return build_damage_chain(
        (
            AbilityBasePowerModifier(),
            ItemAttackStatModifier(),
            EnvironmentDefenseStatModifier(),
            ItemDefenseStatModifier(),
            BaseDamageModifier(),
            StabModifier(),
            TypeEffectivenessModifier(),
            ScreenDamageModifier(),
            CriticalHitModifier(),
            SpreadMoveModifier(),
            ProtectDamageModifier(),
            WeatherFinalDamageModifier(),
            TerrainFinalDamageModifier(),
            AbilityFinalDamageModifier(),
            ItemFinalDamageModifier(),
            RandomRollModifier(),
        )
    )


__all__ = [
    "AbilityBasePowerModifier",
    "AbilityFinalDamageModifier",
    "AppliedModifier",
    "BaseDamageModifier",
    "CriticalHitModifier",
    "DEFAULT_RANDOM_MULTIPLIERS",
    "DamageCalculationState",
    "DamageModifierChain",
    "EnvironmentDefenseStatModifier",
    "ItemAttackStatModifier",
    "ItemDefenseStatModifier",
    "ItemFinalDamageModifier",
    "ModifierStage",
    "ProtectDamageModifier",
    "RandomRollModifier",
    "ScreenDamageModifier",
    "SpreadMoveModifier",
    "StabModifier",
    "TerrainFinalDamageModifier",
    "TypeEffectivenessModifier",
    "WeatherFinalDamageModifier",
    "build_damage_chain",
    "build_default_damage_chain",
    "calculate_base_damage",
    "calculate_stab_multiplier",
    "calculate_type_effectiveness",
    "defensive_stat",
    "offensive_stat",
]
