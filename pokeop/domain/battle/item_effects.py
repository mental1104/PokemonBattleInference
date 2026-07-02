from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.domain.battle.context import DamageContext, MoveCategory


@dataclass(frozen=True)
class ItemEffectResult:
    """One concrete item multiplier returned to the damage modifier chain."""

    key: str
    multiplier: float
    reason: str


class ItemDamageEffect(Protocol):
    """Interface for held items that participate in damage calculation."""

    key: str

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

    key = "item:unknown"

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

    key = "item:life_orb"

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

    key = "item:choice_band"

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

    key = "item:choice_specs"

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

    key = "item:expert_belt"

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

    key = "item:eviolite"

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


_ITEM_EFFECTS: dict[str, ItemDamageEffect] = {
    "life_orb": LifeOrbEffect(),
    "choice_band": ChoiceBandEffect(),
    "choice_specs": ChoiceSpecsEffect(),
    "expert_belt": ExpertBeltEffect(),
    "eviolite": EvioliteEffect(),
}

_ITEM_ALIASES: dict[str, str] = {
    "生命宝珠": "life_orb",
    "生命寶珠": "life_orb",
    "讲究头带": "choice_band",
    "講究頭帶": "choice_band",
    "讲究眼镜": "choice_specs",
    "講究眼鏡": "choice_specs",
    "达人带": "expert_belt",
    "達人帶": "expert_belt",
    "进化奇石": "eviolite",
    "進化奇石": "eviolite",
}


def resolve_item_effect(item: str | None) -> ItemDamageEffect | None:
    """Resolve a known held-item effect; unknown items are deliberate no-ops."""
    if not item:
        return None

    identifier = _normalize_identifier(item)
    identifier = _ITEM_ALIASES.get(identifier, identifier)
    return _ITEM_EFFECTS.get(identifier)


__all__ = ["ItemDamageEffect", "ItemEffectResult", "resolve_item_effect"]
