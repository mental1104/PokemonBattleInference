from __future__ import annotations

from enum import Enum
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


class BattleRulesetProfile(str, Enum):
    """Concrete generation ruleset profiles used to build BattleRuleset snapshots."""

    GEN1 = "gen1"
    GEN2 = "gen2"
    GEN3 = "gen3"
    GEN4 = "gen4"
    GEN5 = "gen5"
    GEN6 = "gen6"
    GEN7 = "gen7"
    GEN8 = "gen8"
    GEN9 = "gen9"

    @property
    def generation_id(self) -> int:
        """Return the concrete Pokemon generation id represented by this profile."""
        return int(self.value.removeprefix("gen"))

    @classmethod
    def from_generation_id(cls, generation_id: int) -> "BattleRulesetProfile":
        """Return the concrete profile for one Pokemon generation."""
        if generation_id <= 0:
            raise ValueError("generation_id must be greater than 0")
        try:
            return cls(f"gen{generation_id}")
        except ValueError as exc:
            raise ValueError(
                f"unsupported generation_id for battle ruleset profile: {generation_id}"
            ) from exc

    @classmethod
    def build_for_generation(
        cls,
        generation_id: int,
        *,
        version_group_id: int | None = None,
    ) -> BattleRuleset:
        """Build a BattleRuleset for one concrete generation."""
        return cls.from_generation_id(generation_id).build(
            generation_id=generation_id,
            version_group_id=version_group_id,
        )

    @classmethod
    def modern(cls) -> BattleRuleset:
        """Build the current default modern ruleset."""
        return cls.GEN9.build()

    def build(
        self,
        *,
        generation_id: int | None = None,
        version_group_id: int | None = None,
    ) -> BattleRuleset:
        """Build a fresh immutable ruleset snapshot for this profile."""
        concrete_generation_id = self._generation_id_or_default(generation_id)
        return BattleRuleset(
            ruleset_id=f"gen{concrete_generation_id}",
            generation_id=concrete_generation_id,
            version_group_id=version_group_id,
            status_rules=self._status_rules_for_generation(concrete_generation_id),
            damage_policy=self._damage_policy(),
        )

    def _generation_id_or_default(self, generation_id: int | None) -> int:
        if generation_id is None:
            return self.generation_id
        if BattleRulesetProfile.from_generation_id(generation_id) is not self:
            raise ValueError(
                f"generation_id {generation_id} does not belong to profile {self.value}"
            )
        return generation_id

    def _damage_policy(self) -> DamagePolicy:
        return DamagePolicy.for_generation(self.generation_id)

    def _status_rules_for_generation(self, generation_id: int) -> StatusRules:
        if generation_id <= 6:
            return _status_rules(Fraction(1, 4))
        return _status_rules(Fraction(1, 2))


__all__ = ["BattleRulesetProfile"]
