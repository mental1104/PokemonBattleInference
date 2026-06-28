from __future__ import annotations

from dataclasses import dataclass, field, replace

from pokeop.domain.battle.status.kinds import (
    NonVolatileStatusKind,
    VolatileStatusKind,
)


@dataclass(frozen=True)
class SleepStatus:
    """Sleep state tracked independently from the sleep ruleset policy."""

    turns_asleep: int = 0
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.SLEEP,
        init=False,
    )

    def __post_init__(self) -> None:
        if self.turns_asleep < 0:
            raise ValueError("turns_asleep must not be negative")

    def with_turns_asleep(self, turns_asleep: int) -> "SleepStatus":
        return replace(self, turns_asleep=turns_asleep)


@dataclass(frozen=True)
class ParalysisStatus:
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.PARALYSIS,
        init=False,
    )


@dataclass(frozen=True)
class BurnStatus:
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.BURN,
        init=False,
    )


@dataclass(frozen=True)
class FreezeStatus:
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.FREEZE,
        init=False,
    )


@dataclass(frozen=True)
class PoisonStatus:
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.POISON,
        init=False,
    )


@dataclass(frozen=True)
class BadPoisonStatus:
    toxic_counter: int = 1
    kind: NonVolatileStatusKind = field(
        default=NonVolatileStatusKind.BAD_POISON,
        init=False,
    )

    def __post_init__(self) -> None:
        if self.toxic_counter < 1:
            raise ValueError("toxic_counter must be greater than 0")


@dataclass(frozen=True)
class ConfusionStatus:
    turns_remaining: int | None = None
    kind: VolatileStatusKind = field(
        default=VolatileStatusKind.CONFUSION,
        init=False,
    )

    def __post_init__(self) -> None:
        if self.turns_remaining is not None and self.turns_remaining < 0:
            raise ValueError("turns_remaining must not be negative")


@dataclass(frozen=True)
class InfatuationStatus:
    source_id: str | None = None
    kind: VolatileStatusKind = field(
        default=VolatileStatusKind.INFATUATION,
        init=False,
    )


NonVolatileStatus = (
    SleepStatus
    | ParalysisStatus
    | BurnStatus
    | FreezeStatus
    | PoisonStatus
    | BadPoisonStatus
)
VolatileStatus = ConfusionStatus | InfatuationStatus


@dataclass(frozen=True)
class CombatantStatus:
    """Immutable status snapshot for one active combatant."""

    non_volatile: NonVolatileStatus | None = None
    volatile: frozenset[VolatileStatus] = frozenset()

    def __post_init__(self) -> None:
        volatile = frozenset(self.volatile)
        kinds = [status.kind for status in volatile]
        if len(kinds) != len(set(kinds)):
            raise ValueError("volatile statuses must have unique kinds")
        object.__setattr__(self, "volatile", volatile)

    def has_non_volatile(self, kind: NonVolatileStatusKind) -> bool:
        return self.non_volatile is not None and self.non_volatile.kind is kind

    def has_volatile(self, kind: VolatileStatusKind) -> bool:
        return any(status.kind is kind for status in self.volatile)

    def volatile_status(self, kind: VolatileStatusKind) -> VolatileStatus | None:
        for status in self.volatile:
            if status.kind is kind:
                return status
        return None

    def set_non_volatile(
        self,
        status: NonVolatileStatus | None,
    ) -> "CombatantStatus":
        return replace(self, non_volatile=status)

    def clear_non_volatile(self) -> "CombatantStatus":
        return self.set_non_volatile(None)

    def add_volatile(self, status: VolatileStatus) -> "CombatantStatus":
        return replace(
            self,
            volatile=frozenset(
                existing
                for existing in self.volatile
                if existing.kind is not status.kind
            )
            | frozenset((status,)),
        )

    def clear_volatile(self) -> "CombatantStatus":
        return replace(self, volatile=frozenset())

    def clear_volatile_status(
        self,
        kind: VolatileStatusKind,
    ) -> "CombatantStatus":
        return replace(
            self,
            volatile=frozenset(
                status for status in self.volatile if status.kind is not kind
            ),
        )


__all__ = [
    "BadPoisonStatus",
    "BurnStatus",
    "CombatantStatus",
    "ConfusionStatus",
    "FreezeStatus",
    "InfatuationStatus",
    "NonVolatileStatus",
    "ParalysisStatus",
    "PoisonStatus",
    "SleepStatus",
    "VolatileStatus",
]
