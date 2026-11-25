from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

from pokeop.domain.battle.moves.models import DamageClass, MoveProfile
from pokeop.domain.battle.status.state import BurnStatus, CombatantStatus, ParalysisStatus

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


def _fraction_from_policy_multiplier(multiplier: float) -> Fraction:
    return Fraction(str(multiplier))


def apply_paralysis_speed_modifier(
    base_speed: int,
    status: CombatantStatus,
    ruleset: BattleRuleset,
) -> int:
    """Apply the ruleset's paralysis speed multiplier if paralysis is active."""
    if base_speed < 0:
        raise ValueError("base_speed must not be negative")
    if not isinstance(status.non_volatile, ParalysisStatus):
        return base_speed

    multiplier = ruleset.status_rules.paralysis_policy.speed_multiplier
    return base_speed * multiplier.numerator // multiplier.denominator


def burn_physical_damage_multiplier(
    status: CombatantStatus,
    ruleset: BattleRuleset,
    move: MoveProfile,
) -> Fraction:
    """Return the burn damage multiplier for the given move profile."""
    if (
        isinstance(status.non_volatile, BurnStatus)
        and move.damage_class is DamageClass.PHYSICAL
    ):
        return _fraction_from_policy_multiplier(
            ruleset.damage_policy.burn_physical_attack_multiplier
        )
    return Fraction(1, 1)


def apply_burn_physical_damage_modifier(
    base_multiplier: Fraction,
    status: CombatantStatus,
    ruleset: BattleRuleset,
    move: MoveProfile,
) -> Fraction:
    """Apply burn's physical damage modifier to an existing multiplier."""
    return base_multiplier * burn_physical_damage_multiplier(status, ruleset, move)


__all__ = [
    "apply_burn_physical_damage_modifier",
    "apply_paralysis_speed_modifier",
    "burn_physical_damage_multiplier",
]
