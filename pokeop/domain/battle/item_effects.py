from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pokeop.domain.battle.context import DamageContext, MoveCategory


class DamageItem(str, Enum):
    """Damage-relevant held item identifiers supported by the battle domain."""

    UNKNOWN = "unknown"
    LIFE_ORB = "life_orb"
    CHOICE_BAND = "choice_band"
    CHOICE_SPECS = "choice_specs"
    EXPERT_BELT = "expert_belt"
    EVIOLITE = "eviolite"

    @property
    def trace_key(self) -> str:
        """Return the modifier trace key for this item."""
        return f"item:{self.value}"

    def create_effect(self) -> ItemDamageEffect:
        """Build the damage effect implementation represented by this enum member."""
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
    def from_raw(cls, item: str) -> "DamageItem":
        """Parse a user/data-facing item name into a supported damage item."""
        identifier = _normalize_identifier(item)
        alias = _ITEM_ALIASES.get(identifier)
        if alias is not None:
            return alias
        try:
            return cls(identifier)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class ItemEffectResult:
    """One concrete item multiplier returned to the damage modifier chain."""

    key: str
    multiplier: float
    reason: str


class ItemDamageEffect(Protocol):
    """Interface for held items that participate in damage calculation."""

    @property
    def key(self) -> str:
        """Return the modifier trace key emitted by this item effect."""
        ...

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        """Return an attack-stat-stage multiplier, or None when inactive."""
        ...

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        """Return a defense-stat-stage multiplier, or None when inactive."""
        ...

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        """Return a final-damage-stage multiplier, or None when inactive."""
        ...


class BaseItemDamageEffect:
    """No-op base class for damage-relevant held item implementations."""

    item = DamageItem.UNKNOWN

    @property
    def key(self) -> str:
        return self.item.trace_key

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        return None

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        return None

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        return None


class LifeOrbEffect(BaseItemDamageEffect):
    """Life Orb boosts direct damage dealt by the holder."""

    item = DamageItem.LIFE_ORB

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        _ = context, type_effectiveness
        return ItemEffectResult(
            key=self.key,
            multiplier=1.3,
            reason="Life Orb boosts direct damage.",
        )


class ChoiceBandEffect(BaseItemDamageEffect):
    """Choice Band boosts the holder's Attack for physical damage."""

    item = DamageItem.CHOICE_BAND

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        if context.move.category is not MoveCategory.PHYSICAL:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=1.5,
            reason="Choice Band boosts Attack for physical moves.",
        )


class ChoiceSpecsEffect(BaseItemDamageEffect):
    """Choice Specs boosts the holder's Special Attack for special damage."""

    item = DamageItem.CHOICE_SPECS

    def attack_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        if context.move.category is not MoveCategory.SPECIAL:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=1.5,
            reason="Choice Specs boosts Special Attack for special moves.",
        )


class ExpertBeltEffect(BaseItemDamageEffect):
    """Expert Belt boosts super-effective direct damage."""

    item = DamageItem.EXPERT_BELT

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> ItemEffectResult | None:
        _ = context
        if type_effectiveness <= 1.0:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=1.2,
            reason="Expert Belt boosts super-effective damage.",
        )


class EvioliteEffect(BaseItemDamageEffect):
    """Eviolite boosts Defense and Special Defense for Pokemon that can evolve."""

    item = DamageItem.EVIOLITE

    def defense_stat_multiplier(
        self,
        context: DamageContext,
    ) -> ItemEffectResult | None:
        if not context.defender.can_evolve:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=1.5,
            reason="Eviolite boosts Defense and Special Defense when the holder can evolve.",
        )


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


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


def resolve_item_effect(item: str | None) -> ItemDamageEffect | None:
    """Resolve a held-item effect; unknown items map to a deliberate no-op effect."""
    if not item:
        return None

    return DamageItem.from_raw(item).create_effect()


__all__ = [
    "DamageItem",
    "ItemDamageEffect",
    "ItemEffectResult",
    "resolve_item_effect",
]
