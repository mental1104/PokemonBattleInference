from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.domain.battle.context import DamageContext
from pokeop.domain.models.types import Type


@dataclass(frozen=True)
class AbilityEffectResult:
    """One concrete ability multiplier returned to the damage modifier chain."""

    key: str
    multiplier: float
    reason: str


class AbilityDamageEffect(Protocol):
    """Interface for ability effects that participate in damage calculation."""

    key: str

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        """Return a base-power-stage multiplier, or None when inactive."""
        ...

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        """Return the final STAB multiplier, or None when this ability is inactive."""
        ...

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        """Return a final-damage-stage multiplier, or None when inactive."""
        ...

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        """Return the final critical-hit multiplier, or None when inactive."""
        ...


class BaseAbilityDamageEffect:
    """No-op base class for damage-relevant ability implementations."""

    key = "ability:unknown"

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        return None

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        return None

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        return None

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        return None


class TechnicianEffect(BaseAbilityDamageEffect):
    """Technician boosts moves with base power 60 or lower."""

    key = "ability:technician"

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        if context.move.power > 60:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=1.5,
            reason="Technician boosts moves with base power 60 or lower.",
        )


class AdaptabilityEffect(BaseAbilityDamageEffect):
    """Adaptability raises same-type attack bonus from 1.5 to 2.0."""

    key = "ability:adaptability"

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        if context.move.type not in context.attacker.types:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=2.0,
            reason="Adaptability raises STAB to 2.0.",
        )


class ThickFatEffect(BaseAbilityDamageEffect):
    """Thick Fat halves incoming Fire- and Ice-type direct damage."""

    key = "ability:thick_fat"

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        _ = type_effectiveness
        if context.move.type not in (Type.FIRE, Type.ICE):
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=0.5,
            reason="Thick Fat halves incoming Fire- and Ice-type damage.",
        )


class FilterEffect(BaseAbilityDamageEffect):
    """Filter reduces super-effective direct damage."""

    key = "ability:filter"

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        _ = context
        if type_effectiveness <= 1.0:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=0.75,
            reason="Filter reduces super-effective damage.",
        )


class SolidRockEffect(FilterEffect):
    """Solid Rock shares Filter's direct-damage behavior."""

    key = "ability:solid_rock"

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        result = super().final_damage_multiplier(context, type_effectiveness)
        if result is None:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=result.multiplier,
            reason="Solid Rock reduces super-effective damage.",
        )


class SniperEffect(BaseAbilityDamageEffect):
    """Sniper increases the critical-hit damage multiplier by 50%."""

    key = "ability:sniper"

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        _ = context
        return AbilityEffectResult(
            key=self.key,
            multiplier=base_multiplier * 1.5,
            reason="Sniper increases critical-hit damage by 50%.",
        )


def _normalize_identifier(identifier: str) -> str:
    return identifier.strip().lower().replace("-", "_").replace(" ", "_")


_ABILITY_EFFECTS: dict[str, AbilityDamageEffect] = {
    "technician": TechnicianEffect(),
    "adaptability": AdaptabilityEffect(),
    "thick_fat": ThickFatEffect(),
    "filter": FilterEffect(),
    "solid_rock": SolidRockEffect(),
    "sniper": SniperEffect(),
}

_ABILITY_ALIASES: dict[str, str] = {
    "技术高手": "technician",
    "適應力": "adaptability",
    "适应力": "adaptability",
    "厚脂肪": "thick_fat",
    "过滤": "filter",
    "過濾": "filter",
    "坚硬岩石": "solid_rock",
    "堅硬岩石": "solid_rock",
    "狙击手": "sniper",
    "狙擊手": "sniper",
}


def resolve_ability_effect(ability: str | None) -> AbilityDamageEffect | None:
    """Resolve a known ability effect; unknown abilities are deliberate no-ops."""
    if not ability:
        return None

    identifier = _normalize_identifier(ability)
    identifier = _ABILITY_ALIASES.get(identifier, identifier)
    return _ABILITY_EFFECTS.get(identifier)


__all__ = [
    "AbilityDamageEffect",
    "AbilityEffectResult",
    "resolve_ability_effect",
]
