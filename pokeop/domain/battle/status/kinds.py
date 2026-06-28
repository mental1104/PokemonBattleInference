from __future__ import annotations

from enum import Enum, unique


@unique
class NonVolatileStatusKind(str, Enum):
    """Major statuses that remain after switching out."""

    SLEEP = "sleep"
    PARALYSIS = "paralysis"
    BURN = "burn"
    FREEZE = "freeze"
    POISON = "poison"
    BAD_POISON = "bad_poison"


@unique
class VolatileStatusKind(str, Enum):
    """Temporary statuses that are cleared by switching out."""

    CONFUSION = "confusion"
    INFATUATION = "infatuation"


__all__ = ["NonVolatileStatusKind", "VolatileStatusKind"]
