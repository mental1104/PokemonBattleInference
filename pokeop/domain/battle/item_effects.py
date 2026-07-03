from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.domain.battle.context import DamageContext, MoveCategory
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy


@dataclass(frozen=True)
class ItemEffectResult:
    """One concrete item multiplier returned to the damage modifier chain."""

    key: ModifierKey
    multiplier: float
    reason: str


class ItemDamageEffect(Protocol):
    """Interface for held items that participate in damage calculation."""

    @property
    def key(self) -> ModifierKey:
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


def _damage_policy(context: DamageContext) -> DamagePolicy:
    if context.ruleset is None:
        return DamagePolicy.modern()
    return context.ruleset.damage_policy


class BaseItemDamageEffect:
    """No-op base class for damage-relevant held item implementations."""

    item = DamageItem.UNKNOWN

    @property
    def key(self) -> ModifierKey:
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
        _ = type_effectiveness
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).life_orb_damage_multiplier,
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
            multiplier=_damage_policy(context).choice_item_attack_multiplier,
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
            multiplier=_damage_policy(context).choice_item_attack_multiplier,
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
        if type_effectiveness <= 1.0:
            return None
        return ItemEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).expert_belt_damage_multiplier,
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
            multiplier=_damage_policy(context).eviolite_defense_multiplier,
            reason="Eviolite boosts Defense and Special Defense when the holder can evolve.",
        )


def resolve_item_effect(item: DamageItem | str | None) -> ItemDamageEffect:
    """Resolve a held-item effect; unknown items map to a deliberate no-op effect."""
    return DamageItem.from_identifier(item).create_effect()


__all__ = [
    "BaseItemDamageEffect",
    "ChoiceBandEffect",
    "ChoiceSpecsEffect",
    "DamageItem",
    "EvioliteEffect",
    "ExpertBeltEffect",
    "ItemDamageEffect",
    "ItemEffectResult",
    "LifeOrbEffect",
    "resolve_item_effect",
]
