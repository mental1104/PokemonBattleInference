from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import DamageContext
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.models.types import Type


@dataclass(frozen=True)
class AbilityEffectResult:
    """One concrete ability multiplier returned to the damage modifier chain."""

    key: ModifierKey
    multiplier: float
    reason: str


class AbilityDamageEffect(Protocol):
    """Interface for ability effects that participate in damage calculation."""

    @property
    def key(self) -> ModifierKey:
        """Return the modifier trace key emitted by this ability effect."""
        ...

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


def _damage_policy(context: DamageContext) -> DamagePolicy:
    if context.ruleset is None:
        return DamagePolicy.modern()
    return context.ruleset.damage_policy


class BaseAbilityDamageEffect:
    """No-op base class for damage-relevant ability implementations."""

    ability = DamageAbility.UNKNOWN

    @property
    def key(self) -> ModifierKey:
        return self.ability.trace_key

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

    ability = DamageAbility.TECHNICIAN

    def base_power_multiplier(
        self,
        context: DamageContext,
    ) -> AbilityEffectResult | None:
        policy = _damage_policy(context)
        if context.move.power > policy.technician_base_power_threshold:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=policy.technician_base_power_multiplier,
            reason="Technician boosts moves with base power 60 or lower.",
        )


class AdaptabilityEffect(BaseAbilityDamageEffect):
    """Adaptability raises same-type attack bonus from 1.5 to 2.0."""

    ability = DamageAbility.ADAPTABILITY

    def stab_multiplier(self, context: DamageContext) -> AbilityEffectResult | None:
        if context.move.type not in context.attacker.types:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).adaptability_stab_multiplier,
            reason="Adaptability raises STAB to 2.0.",
        )


class ThickFatEffect(BaseAbilityDamageEffect):
    """Thick Fat halves incoming Fire- and Ice-type direct damage."""

    ability = DamageAbility.THICK_FAT

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
            multiplier=_damage_policy(context).thick_fat_damage_multiplier,
            reason="Thick Fat halves incoming Fire- and Ice-type damage.",
        )


class FilterEffect(BaseAbilityDamageEffect):
    """Filter reduces super-effective direct damage."""

    ability = DamageAbility.FILTER

    def final_damage_multiplier(
        self,
        context: DamageContext,
        type_effectiveness: float,
    ) -> AbilityEffectResult | None:
        if type_effectiveness <= 1.0:
            return None
        return AbilityEffectResult(
            key=self.key,
            multiplier=_damage_policy(context).filter_damage_multiplier,
            reason="Filter reduces super-effective damage.",
        )


class SolidRockEffect(FilterEffect):
    """Solid Rock shares Filter's direct-damage behavior."""

    ability = DamageAbility.SOLID_ROCK

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

    ability = DamageAbility.SNIPER

    def critical_hit_multiplier(
        self,
        context: DamageContext,
        base_multiplier: float,
    ) -> AbilityEffectResult | None:
        return AbilityEffectResult(
            key=self.key,
            multiplier=(
                base_multiplier * _damage_policy(context).sniper_critical_multiplier
            ),
            reason="Sniper increases critical-hit damage by 50%.",
        )


def resolve_ability_effect(
    ability: DamageAbility | str | None,
) -> AbilityDamageEffect:
    """Resolve a known ability effect; unknown abilities are deliberate no-ops."""
    return DamageAbility.from_identifier(ability).create_effect()


__all__ = [
    "AbilityDamageEffect",
    "AbilityEffectResult",
    "DamageAbility",
    "resolve_ability_effect",
]
