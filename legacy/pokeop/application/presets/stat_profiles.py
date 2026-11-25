from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.stats import NatureModifier, StatProfile, StatValues
from pokeop.domain.models.pokemon_fields import StatField


@dataclass(frozen=True)
class StatProfilePreset:
    """
    表示一个面向用户习惯叫法的努力值/性格配置。

    例如“极攻”“满 HP + 满物防”不是 domain 概念，而是 application 层为了用例输入方便
    提供的预设；apply 会把这个预设套到具体宝可梦种族值上，得到 domain 的 StatProfile。
    """

    key: str
    evs: StatValues
    nature_modifier: NatureModifier = NatureModifier.neutral()

    def apply(self, base_stats: StatValues, *, ivs: StatValues | None = None) -> StatProfile:
        """把当前预设应用到一组种族值上，生成可用于能力值计算的 StatProfile。"""
        return StatProfile(
            base_stats=base_stats,
            evs=self.evs,
            ivs=ivs or StatValues.perfect_ivs(),
            nature_modifier=self.nature_modifier,
        )


MAX_ATK_PLUS = StatProfilePreset(
    key="max_atk_plus",
    evs=StatValues(attack=252),
    nature_modifier=NatureModifier.increase(StatField.ATTACK),
)
MAX_ATK_NEUTRAL = StatProfilePreset(
    key="max_atk_neutral",
    evs=StatValues(attack=252),
)
MAX_HP = StatProfilePreset(
    key="max_hp",
    evs=StatValues(hp=252),
)
MAX_HP_DEF = StatProfilePreset(
    key="max_hp_def",
    evs=StatValues(hp=252, defense=252),
)
MAX_HP_DEF_PLUS = StatProfilePreset(
    key="max_hp_def_plus",
    evs=StatValues(hp=252, defense=252),
    nature_modifier=NatureModifier.increase(StatField.DEFENSE),
)
MAX_HP_SPDEF = StatProfilePreset(
    key="max_hp_spdef",
    evs=StatValues(hp=252, special_defense=252),
)
MAX_HP_SPDEF_PLUS = StatProfilePreset(
    key="max_hp_spdef_plus",
    evs=StatValues(hp=252, special_defense=252),
    nature_modifier=NatureModifier.increase(StatField.SPECIAL_DEFENSE),
)

PRESETS = {
    preset.key: preset
    for preset in (
        MAX_ATK_PLUS,
        MAX_ATK_NEUTRAL,
        MAX_HP,
        MAX_HP_DEF,
        MAX_HP_DEF_PLUS,
        MAX_HP_SPDEF,
        MAX_HP_SPDEF_PLUS,
    )
}


def max_atk_plus(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“极攻”配置：252 Atk、默认 31 IV、攻击性格 1.1。"""
    return MAX_ATK_PLUS.apply(base_stats)


def max_atk_neutral(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满攻”配置：252 Atk、默认 31 IV、性格不修正。"""
    return MAX_ATK_NEUTRAL.apply(base_stats)


def max_hp(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满 HP”配置：252 HP、默认 31 IV、性格不修正。"""
    return MAX_HP.apply(base_stats)


def max_hp_def(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满 HP + 满物防”配置：252 HP / 252 Def。"""
    return MAX_HP_DEF.apply(base_stats)


def max_hp_def_plus(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满 HP + 满物防 + 物防性格”配置。"""
    return MAX_HP_DEF_PLUS.apply(base_stats)


def max_hp_spdef(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满 HP + 满特防”配置：252 HP / 252 SpD。"""
    return MAX_HP_SPDEF.apply(base_stats)


def max_hp_spdef_plus(base_stats: StatValues) -> StatProfile:
    """用给定种族值创建“满 HP + 满特防 + 特防性格”配置。"""
    return MAX_HP_SPDEF_PLUS.apply(base_stats)


__all__ = [
    "MAX_ATK_NEUTRAL",
    "MAX_ATK_PLUS",
    "MAX_HP",
    "MAX_HP_DEF",
    "MAX_HP_DEF_PLUS",
    "MAX_HP_SPDEF",
    "MAX_HP_SPDEF_PLUS",
    "PRESETS",
    "StatProfilePreset",
    "max_atk_neutral",
    "max_atk_plus",
    "max_hp",
    "max_hp_def",
    "max_hp_def_plus",
    "max_hp_spdef",
    "max_hp_spdef_plus",
]
