from __future__ import annotations

from enum import Enum, unique
from typing import TYPE_CHECKING

from pokeop.domain.battle.modifier_keys import ModifierKey

if TYPE_CHECKING:
    from pokeop.domain.battle.item_effects import ItemDamageEffect


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


@unique
class DamageItem(str, Enum):
    """Damage-relevant held item identifiers supported by the battle domain."""

    UNKNOWN = "unknown"
    LIFE_ORB = "life_orb"
    CHOICE_BAND = "choice_band"
    CHOICE_SPECS = "choice_specs"
    EXPERT_BELT = "expert_belt"
    EVIOLITE = "eviolite"

    @property
    def trace_key(self) -> ModifierKey:
        """Return the modifier trace key for this item."""
        match self:
            case DamageItem.UNKNOWN:
                return ModifierKey.ITEM_UNKNOWN
            case DamageItem.LIFE_ORB:
                return ModifierKey.ITEM_LIFE_ORB
            case DamageItem.CHOICE_BAND:
                return ModifierKey.ITEM_CHOICE_BAND
            case DamageItem.CHOICE_SPECS:
                return ModifierKey.ITEM_CHOICE_SPECS
            case DamageItem.EXPERT_BELT:
                return ModifierKey.ITEM_EXPERT_BELT
            case DamageItem.EVIOLITE:
                return ModifierKey.ITEM_EVIOLITE
        raise AssertionError(f"unhandled damage item: {self!r}")

    def create_effect(self) -> "ItemDamageEffect":
        """Build the damage effect implementation represented by this enum member."""
        from pokeop.domain.battle.item_effects import (
            BaseItemDamageEffect,
            ChoiceBandEffect,
            ChoiceSpecsEffect,
            EvioliteEffect,
            ExpertBeltEffect,
            LifeOrbEffect,
        )

        match self:
            case DamageItem.UNKNOWN:
                return BaseItemDamageEffect()
            case DamageItem.LIFE_ORB:
                return LifeOrbEffect()
            case DamageItem.CHOICE_BAND:
                return ChoiceBandEffect()
            case DamageItem.CHOICE_SPECS:
                return ChoiceSpecsEffect()
            case DamageItem.EXPERT_BELT:
                return ExpertBeltEffect()
            case DamageItem.EVIOLITE:
                return EvioliteEffect()
        raise AssertionError(f"unhandled damage item: {self!r}")

    @classmethod
    def from_identifier(cls, item: "DamageItem | str | None") -> "DamageItem":
        """Parse a user/data-facing item name into a supported damage item."""
        if item is None:
            return cls.UNKNOWN
        if isinstance(item, DamageItem):
            return item

        identifier = _normalize_identifier(item)
        alias = _ITEM_ALIASES.get(identifier)
        if alias is not None:
            return alias
        try:
            return cls(identifier)
        except ValueError:
            return cls.UNKNOWN

    @classmethod
    def from_raw(cls, item: "DamageItem | str | None") -> "DamageItem":
        """Compatibility alias for older boundary parser naming."""
        return cls.from_identifier(item)


_ITEM_ALIASES: dict[str, DamageItem] = {
    "生命宝珠": DamageItem.LIFE_ORB,
    "生命寶珠": DamageItem.LIFE_ORB,
    "讲究头带": DamageItem.CHOICE_BAND,
    "講究頭帶": DamageItem.CHOICE_BAND,
    "讲究眼镜": DamageItem.CHOICE_SPECS,
    "講究眼鏡": DamageItem.CHOICE_SPECS,
    "达人带": DamageItem.EXPERT_BELT,
    "達人帶": DamageItem.EXPERT_BELT,
    "进化奇石": DamageItem.EVIOLITE,
    "進化奇石": DamageItem.EVIOLITE,
}


__all__ = ["DamageItem"]
