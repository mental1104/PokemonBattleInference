from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


class Terrain(str, Enum):
    """Battle terrain states that can affect direct damage calculation."""

    ELECTRIC = "electric_terrain"
    PSYCHIC = "psychic_terrain"
    GRASSY = "grassy_terrain"
    MISTY = "misty_terrain"


def terrain_damage_boost_multiplier(ruleset: "BattleRuleset") -> float:
    """Return the terrain boost configured by the supplied battle ruleset."""
    return ruleset.damage_policy.terrain_boost_multiplier


__all__ = ["Terrain", "terrain_damage_boost_multiplier"]
