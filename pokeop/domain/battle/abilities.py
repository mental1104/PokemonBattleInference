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
    """Damage-relevant ability identifiers supported by the battle domain."""

    UNKNOWN = "unknown"
    TECHNICIAN = "technician"
    ADAPTABILITY = "adaptability"
    THICK_FAT = "thick_fat"
    FILTER = "filter"
    SOLID_ROCK = "solid_rock"
    SNIPER = "sniper"

    @property
    def trace_key(self) -> ModifierKey:
        """Return the modifier trace key for this ability."""
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
        raise AssertionError(f"unhandled damage ability: {self!r}")

    def create_effect(self) -> "AbilityDamageEffect":
        """Build the damage effect implementation represented by this enum member."""
        from pokeop.domain.battle.ability_effects import (
            AdaptabilityEffect,
            BaseAbilityDamageEffect,
            FilterEffect,
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
}


__all__ = ["DamageAbility"]
