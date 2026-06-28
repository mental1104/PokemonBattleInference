from __future__ import annotations

from fractions import Fraction

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


GEN6_RULESET = BattleRuleset(
    ruleset_id="gen6",
    generation_id=6,
    version_group_id=None,
    status_rules=_status_rules(Fraction(1, 4)),
)

GEN7_RULESET = BattleRuleset(
    ruleset_id="gen7",
    generation_id=7,
    version_group_id=None,
    status_rules=_status_rules(Fraction(1, 2)),
)

GEN9_RULESET = BattleRuleset(
    ruleset_id="gen9",
    generation_id=9,
    version_group_id=None,
    status_rules=_status_rules(Fraction(1, 2)),
)


__all__ = ["GEN6_RULESET", "GEN7_RULESET", "GEN9_RULESET"]
