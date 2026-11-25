from __future__ import annotations

from dataclasses import dataclass, field

from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.status_rules import StatusRules


@dataclass(frozen=True)
class BattleRuleset:
    """Rule profile for one battle ruleset or generation slice."""

    ruleset_id: str
    generation_id: int
    version_group_id: int | None
    status_rules: StatusRules
    damage_policy: DamagePolicy = field(default_factory=DamagePolicy.modern)

    def __post_init__(self) -> None:
        if not self.ruleset_id:
            raise ValueError("ruleset_id must not be empty")
        if self.generation_id < 1:
            raise ValueError("generation_id must be greater than 0")
        if self.version_group_id is not None and self.version_group_id < 1:
            raise ValueError("version_group_id must be greater than 0")


__all__ = ["BattleRuleset"]
