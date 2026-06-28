from __future__ import annotations

from fractions import Fraction
from typing import Protocol


class BattleRandom(Protocol):
    """Randomness boundary for battle-domain rules."""

    def chance(self, probability: Fraction | float) -> bool:
        """Return whether an event with the given probability occurs."""
        ...


__all__ = ["BattleRandom"]
