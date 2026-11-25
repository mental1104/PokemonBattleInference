from __future__ import annotations

from dataclasses import dataclass, field

from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather


@dataclass(frozen=True)
class BattleEnvironment:
    """Pure battle environment snapshot used by one damage calculation."""

    weather: Weather | None = None
    terrain: Terrain | None = None
    attacker_side: SideConditions = field(default_factory=SideConditions)
    defender_side: SideConditions = field(default_factory=SideConditions)


__all__ = ["BattleEnvironment"]
