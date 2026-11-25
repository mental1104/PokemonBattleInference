from __future__ import annotations

from enum import Enum, unique
from typing import TYPE_CHECKING

from pokeop.domain.battle.modifier_keys import ModifierKey

if TYPE_CHECKING:
    from pokeop.domain.battle.ability_effects import AbilityDamageEffect


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


@unique
class DamageAbility(str, Enum):
    """表示当前 battle domain 已识别并可创建 effect 的特性标识。"""

    UNKNOWN = "unknown"
    TECHNICIAN = "technician"
    ADAPTABILITY = "adaptability"
    THICK_FAT = "thick_fat"
    FILTER = "filter"
    SOLID_ROCK = "solid_rock"
    SNIPER = "sniper"
    MULTISCALE = "multiscale"
    INNER_FOCUS = "inner_focus"

    @property
    def trace_key(self) -> ModifierKey:
        """返回该特性用于伤害 trace 或机制诊断的稳定键。

        Returns:
            与当前枚举成员一一对应的 ``ModifierKey``。
        """
        match self:
            case DamageAbility.UNKNOWN:
                return ModifierKey.ABILITY_UNKNOWN
            case DamageAbility.TECHNICIAN:
                return ModifierKey.ABILITY_TECHNICIAN
            case DamageAbility.ADAPTABILITY:
                return ModifierKey.ABILITY_ADAPTABILITY
            case DamageAbility.THICK_FAT:
                return ModifierKey.ABILITY_THICK_FAT
            case DamageAbility.FILTER:
                return ModifierKey.ABILITY_FILTER
            case DamageAbility.SOLID_ROCK:
                return ModifierKey.ABILITY_SOLID_ROCK
            case DamageAbility.SNIPER:
                return ModifierKey.ABILITY_SNIPER
            case DamageAbility.MULTISCALE:
                return ModifierKey.ABILITY_MULTISCALE
            case DamageAbility.INNER_FOCUS:
                return ModifierKey.ABILITY_INNER_FOCUS
        raise AssertionError(f"unhandled damage ability: {self!r}")

    def create_effect(self) -> "AbilityDamageEffect":
        """创建该特性对应的兼容 domain effect。

        Returns:
            已知特性的具体 effect；``UNKNOWN`` 返回显式 no-op 实现。具体 effect 可以
            在旧伤害接口之外额外实现动态伤害或临时状态阻止窄协议。
        """
        from pokeop.domain.battle.ability_effects import (
            AdaptabilityEffect,
            BaseAbilityDamageEffect,
            FilterEffect,
            InnerFocusEffect,
            MultiscaleEffect,
            SniperEffect,
            SolidRockEffect,
            TechnicianEffect,
            ThickFatEffect,
        )

        match self:
            case DamageAbility.UNKNOWN:
                return BaseAbilityDamageEffect()
            case DamageAbility.TECHNICIAN:
                return TechnicianEffect()
            case DamageAbility.ADAPTABILITY:
                return AdaptabilityEffect()
            case DamageAbility.THICK_FAT:
                return ThickFatEffect()
            case DamageAbility.FILTER:
                return FilterEffect()
            case DamageAbility.SOLID_ROCK:
                return SolidRockEffect()
            case DamageAbility.SNIPER:
                return SniperEffect()
            case DamageAbility.MULTISCALE:
                return MultiscaleEffect()
            case DamageAbility.INNER_FOCUS:
                return InnerFocusEffect()
        raise AssertionError(f"unhandled damage ability: {self!r}")

    @classmethod
    def from_identifier(cls, ability: "DamageAbility | str | None") -> "DamageAbility":
        """Parse a user/data-facing ability name into a supported damage ability."""
        if ability is None:
            return cls.UNKNOWN
        if isinstance(ability, DamageAbility):
            return ability

        identifier = _normalize_identifier(ability)
        alias = _ABILITY_ALIASES.get(identifier)
        if alias is not None:
            return alias
        try:
            return cls(identifier)
        except ValueError:
            return cls.UNKNOWN

    @classmethod
    def from_raw(cls, ability: "DamageAbility | str | None") -> "DamageAbility":
        """Compatibility alias for older boundary parser naming."""
        return cls.from_identifier(ability)


_ABILITY_ALIASES: dict[str, DamageAbility] = {
    "技术高手": DamageAbility.TECHNICIAN,
    "適應力": DamageAbility.ADAPTABILITY,
    "适应力": DamageAbility.ADAPTABILITY,
    "厚脂肪": DamageAbility.THICK_FAT,
    "过滤": DamageAbility.FILTER,
    "過濾": DamageAbility.FILTER,
    "坚硬岩石": DamageAbility.SOLID_ROCK,
    "堅硬岩石": DamageAbility.SOLID_ROCK,
    "狙击手": DamageAbility.SNIPER,
    "狙擊手": DamageAbility.SNIPER,
    "多重鳞片": DamageAbility.MULTISCALE,
    "多重鱗片": DamageAbility.MULTISCALE,
    "精神力": DamageAbility.INNER_FOCUS,
}


__all__ = ["DamageAbility"]
