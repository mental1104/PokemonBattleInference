from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from pokeop.domain.models.types import Type

if TYPE_CHECKING:
    from pokeop.domain.battle.environment import BattleEnvironment


class GroundingState(str, Enum):
    """Explicit grounding override for terrain-sensitive mechanics."""

    GROUNDED = "grounded"
    AIRBORNE = "airborne"


def is_grounded(
    pokemon: Any,
    environment: "BattleEnvironment | None" = None,
) -> bool:
    """
    Return whether a Pokemon is affected by terrain for direct damage rules.

    This first version keeps the rule deliberately small: explicit overrides
    win, otherwise Flying-type Pokemon are airborne and all other Pokemon are
    grounded. The environment parameter is reserved for future Gravity-style
    rules without forcing a new call shape later.
    """
    _ = environment
    grounding_state = getattr(pokemon, "grounding_state", None)
    if grounding_state is GroundingState.GROUNDED:
        return True
    if grounding_state is GroundingState.AIRBORNE:
        return False

    return Type.FLYING not in getattr(pokemon, "types")


__all__ = ["GroundingState", "is_grounded"]
