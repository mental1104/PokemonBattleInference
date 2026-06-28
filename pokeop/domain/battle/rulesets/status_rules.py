from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol

from pokeop.domain.battle.rng import BattleRandom
from pokeop.domain.battle.status.state import SleepStatus


def _validate_probability(value: Fraction, field_name: str) -> None:
    if value < 0 or value > 1:
        raise ValueError(f"{field_name} must be between 0 and 1")


def _validate_positive_fraction(value: Fraction, field_name: str) -> None:
    if value < 0:
        raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class SleepCheckResult:
    """Result of applying a sleep policy before action."""

    awoke: bool
    updated_status: SleepStatus | None
    events: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.awoke and self.updated_status is not None:
            raise ValueError("awoken sleep result must not keep a sleep status")
        if not self.awoke and self.updated_status is None:
            raise ValueError("sleeping result must include an updated sleep status")


class SleepPolicy(Protocol):
    """Extensible sleep behavior boundary for generation-specific rules."""

    def check_before_action(
        self,
        status: SleepStatus,
        rng: BattleRandom,
    ) -> SleepCheckResult:
        ...


@dataclass(frozen=True)
class TurnBasedSleepPolicy:
    """
    Simple sleep policy backed by a per-turn wake chance table.

    turns_asleep is used as the table index. If the table is exhausted, the last
    configured probability remains in effect.
    """

    wake_chances: tuple[Fraction, ...]

    def __post_init__(self) -> None:
        if not self.wake_chances:
            raise ValueError("wake_chances must not be empty")
        for chance in self.wake_chances:
            _validate_probability(chance, "wake_chances")

    def check_before_action(
        self,
        status: SleepStatus,
        rng: BattleRandom,
    ) -> SleepCheckResult:
        index = min(status.turns_asleep, len(self.wake_chances) - 1)
        if rng.chance(self.wake_chances[index]):
            return SleepCheckResult(
                awoke=True,
                updated_status=None,
                events=("sleep_woke_up",),
            )

        return SleepCheckResult(
            awoke=False,
            updated_status=status.with_turns_asleep(status.turns_asleep + 1),
            events=("sleep_continues",),
        )


@dataclass(frozen=True)
class FreezePolicy:
    thaw_chance: Fraction
    allow_thaw_move_override: bool

    def __post_init__(self) -> None:
        _validate_probability(self.thaw_chance, "thaw_chance")


@dataclass(frozen=True)
class ParalysisPolicy:
    speed_multiplier: Fraction
    full_paralysis_chance: Fraction

    def __post_init__(self) -> None:
        _validate_positive_fraction(self.speed_multiplier, "speed_multiplier")
        _validate_probability(self.full_paralysis_chance, "full_paralysis_chance")


@dataclass(frozen=True)
class BurnPolicy:
    physical_damage_multiplier: Fraction
    residual_damage_fraction: Fraction

    def __post_init__(self) -> None:
        _validate_positive_fraction(
            self.physical_damage_multiplier,
            "physical_damage_multiplier",
        )
        _validate_probability(
            self.residual_damage_fraction,
            "residual_damage_fraction",
        )


@dataclass(frozen=True)
class PoisonPolicy:
    residual_damage_fraction: Fraction
    bad_poison_base_fraction: Fraction

    def __post_init__(self) -> None:
        _validate_probability(
            self.residual_damage_fraction,
            "residual_damage_fraction",
        )
        _validate_probability(
            self.bad_poison_base_fraction,
            "bad_poison_base_fraction",
        )


@dataclass(frozen=True)
class ConfusionPolicy:
    self_hit_chance: Fraction

    def __post_init__(self) -> None:
        _validate_probability(self.self_hit_chance, "self_hit_chance")


@dataclass(frozen=True)
class InfatuationPolicy:
    immobilize_chance: Fraction

    def __post_init__(self) -> None:
        _validate_probability(self.immobilize_chance, "immobilize_chance")


@dataclass(frozen=True)
class StatusRules:
    sleep_policy: SleepPolicy
    freeze_policy: FreezePolicy
    paralysis_policy: ParalysisPolicy
    burn_policy: BurnPolicy
    poison_policy: PoisonPolicy
    confusion_policy: ConfusionPolicy
    infatuation_policy: InfatuationPolicy


__all__ = [
    "BurnPolicy",
    "ConfusionPolicy",
    "FreezePolicy",
    "InfatuationPolicy",
    "ParalysisPolicy",
    "PoisonPolicy",
    "SleepCheckResult",
    "SleepPolicy",
    "StatusRules",
    "TurnBasedSleepPolicy",
]
