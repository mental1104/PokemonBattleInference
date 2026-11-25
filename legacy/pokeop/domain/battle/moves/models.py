from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique

from pokeop.domain.battle.context import MoveCategory as DamageClass


@unique
class MoveFlag(str, Enum):
    """Data-driven move flags used by battle policies."""

    THAWS_USER_WHEN_FROZEN = "thaws_user_when_frozen"


@dataclass(frozen=True)
class MoveProfile:
    """Minimal move snapshot needed by status gates and modifiers."""

    name: str
    damage_class: DamageClass
    flags: frozenset[MoveFlag] = frozenset()
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("move name must not be empty")
        if self.id is not None and self.id <= 0:
            raise ValueError("move id must be greater than 0")
        object.__setattr__(self, "flags", frozenset(self.flags))


__all__ = ["DamageClass", "MoveFlag", "MoveProfile"]
