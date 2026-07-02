from __future__ import annotations

from fractions import Fraction

from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.models import BattleRuleset
from pokeop.domain.battle.rulesets.status_rules import (
    BurnPolicy,
    ConfusionPolicy,
    FreezePolicy,
    InfatuationPolicy,
    ParalysisPolicy,
    PoisonPolicy,
    StatusRules,
    TurnBasedSleepPolicy,
)


def _status_rules(paralysis_speed_multiplier: Fraction) -> StatusRules:
    return StatusRules(
        sleep_policy=TurnBasedSleepPolicy(
            wake_chances=(
                Fraction(0, 1),
                Fraction(1, 3),
                Fraction(1, 2),
                Fraction(1, 1),
            )
        ),
        freeze_policy=FreezePolicy(
            thaw_chance=Fraction(1, 5),
            allow_thaw_move_override=True,
        ),
        paralysis_policy=ParalysisPolicy(
            speed_multiplier=paralysis_speed_multiplier,
            full_paralysis_chance=Fraction(1, 4),
        ),
        burn_policy=BurnPolicy(
            physical_damage_multiplier=Fraction(1, 2),
            residual_damage_fraction=Fraction(1, 16),
        ),
        poison_policy=PoisonPolicy(
            residual_damage_fraction=Fraction(1, 8),
            bad_poison_base_fraction=Fraction(1, 16),
        ),
        confusion_policy=ConfusionPolicy(self_hit_chance=Fraction(1, 3)),
        infatuation_policy=InfatuationPolicy(immobilize_chance=Fraction(1, 2)),
    )


def gen5_ruleset(
    *,
    generation_id: int = 5,
    version_group_id: int | None = None,
) -> BattleRuleset:
    """Build the current legacy Gen1-Gen5 damage-policy profile."""
    return BattleRuleset(
        ruleset_id=f"gen{generation_id}",
        generation_id=generation_id,
        version_group_id=version_group_id,
        status_rules=_status_rules(Fraction(1, 4)),
        damage_policy=DamagePolicy.gen5(),
    )


def gen6_or_gen7_ruleset(
    *,
    generation_id: int = 6,
    version_group_id: int | None = None,
) -> BattleRuleset:
    """Build the current Gen6/Gen7 damage-policy profile."""
    paralysis_multiplier = Fraction(1, 4) if generation_id == 6 else Fraction(1, 2)
    return BattleRuleset(
        ruleset_id=f"gen{generation_id}",
        generation_id=generation_id,
        version_group_id=version_group_id,
        status_rules=_status_rules(paralysis_multiplier),
        damage_policy=DamagePolicy.gen6_or_gen7(),
    )


def modern_ruleset(
    *,
    generation_id: int = 9,
    version_group_id: int | None = None,
) -> BattleRuleset:
    """Build the current modern Gen8/Gen9 damage-policy profile."""
    return BattleRuleset(
        ruleset_id=f"gen{generation_id}",
        generation_id=generation_id,
        version_group_id=version_group_id,
        status_rules=_status_rules(Fraction(1, 2)),
        damage_policy=DamagePolicy.modern(),
    )


GEN5_RULESET = gen5_ruleset()

GEN6_RULESET = gen6_or_gen7_ruleset(generation_id=6)

GEN7_RULESET = gen6_or_gen7_ruleset(generation_id=7)

GEN9_RULESET = modern_ruleset(generation_id=9)


__all__ = [
    "GEN5_RULESET",
    "GEN6_RULESET",
    "GEN7_RULESET",
    "GEN9_RULESET",
    "gen5_ruleset",
    "gen6_or_gen7_ruleset",
    "modern_ruleset",
]
