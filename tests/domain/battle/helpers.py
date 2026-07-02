from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.domain.battle.context import BattleMove, BattlePokemon, MoveCategory
from pokeop.domain.battle.moves.models import MoveFlag, MoveProfile
from pokeop.domain.battle.stats import (
    NatureModifier,
    StatProfile,
    StatValues,
    calculate_actual_stats,
)
from pokeop.domain.battle.status.state import (
    BadPoisonStatus,
    BurnStatus,
    CombatantStatus,
    ConfusionStatus,
    FreezeStatus,
    InfatuationStatus,
    NonVolatileStatus,
    ParalysisStatus,
    PoisonStatus,
    SleepStatus,
    VolatileStatus,
)
from pokeop.domain.models.pokemon_fields import StatField
from pokeop.domain.models.types import Type


LEVEL_50 = 50


@dataclass(frozen=True)
class PokemonSpec:
    name: str
    types: tuple[Type, ...]
    base_stats: StatValues

    def profile(
        self,
        *,
        evs: StatValues = StatValues.zero(),
        nature_modifier: NatureModifier = NatureModifier.neutral(),
    ) -> StatProfile:
        return StatProfile(
            base_stats=self.base_stats,
            evs=evs,
            nature_modifier=nature_modifier,
        )

    def battle_pokemon(
        self,
        profile: StatProfile,
        *,
        level: int = LEVEL_50,
    ) -> BattlePokemon:
        return BattlePokemon(
            name=self.name,
            level=level,
            types=self.types,
            stats=calculate_actual_stats(profile, level=level),
        )


SCIZOR = PokemonSpec(
    name="scizor",
    types=(Type.BUG, Type.STEEL),
    base_stats=StatValues(
        hp=70,
        attack=130,
        defense=100,
        special_attack=55,
        special_defense=80,
        speed=65,
    ),
)

SYLVEON = PokemonSpec(
    name="sylveon",
    types=(Type.FAIRY,),
    base_stats=StatValues(
        hp=95,
        attack=65,
        defense=65,
        special_attack=110,
        special_defense=130,
        speed=60,
    ),
)

SCIZOR_PROFILES = {
    "max_atk_plus": SCIZOR.profile(
        evs=StatValues(attack=252),
        nature_modifier=NatureModifier.increase(StatField.ATTACK),
    ),
    "max_atk_neutral": SCIZOR.profile(evs=StatValues(attack=252)),
}

SYLVEON_PROFILES = {
    "max_hp": SYLVEON.profile(evs=StatValues(hp=252)),
    "max_hp_def": SYLVEON.profile(evs=StatValues(hp=252, defense=252)),
    "max_hp_def_plus": SYLVEON.profile(
        evs=StatValues(hp=252, defense=252),
        nature_modifier=NatureModifier.increase(StatField.DEFENSE),
    ),
}


class BattlePokemonFactory:
    """Factory for common battle Pokemon used by domain tests."""

    @staticmethod
    def scizor(
        profile_key: str = "max_atk_neutral",
        *,
        level: int = LEVEL_50,
    ) -> BattlePokemon:
        return SCIZOR.battle_pokemon(
            BattlePokemonFactory.scizor_profile(profile_key),
            level=level,
        )

    @staticmethod
    def sylveon(
        profile_key: str = "max_hp",
        *,
        level: int = LEVEL_50,
    ) -> BattlePokemon:
        return SYLVEON.battle_pokemon(
            BattlePokemonFactory.sylveon_profile(profile_key),
            level=level,
        )

    @staticmethod
    def scizor_profile(profile_key: str) -> StatProfile:
        return _profile_from(SCIZOR_PROFILES, "scizor", profile_key)

    @staticmethod
    def sylveon_profile(profile_key: str) -> StatProfile:
        return _profile_from(SYLVEON_PROFILES, "sylveon", profile_key)

    @staticmethod
    def scizor_stats(profile_key: str, *, level: int = LEVEL_50) -> StatValues:
        return calculate_actual_stats(
            BattlePokemonFactory.scizor_profile(profile_key),
            level=level,
        )

    @staticmethod
    def sylveon_stats(profile_key: str, *, level: int = LEVEL_50) -> StatValues:
        return calculate_actual_stats(
            BattlePokemonFactory.sylveon_profile(profile_key),
            level=level,
        )


def _profile_from(
    profiles: dict[str, StatProfile],
    species: str,
    profile_key: str,
) -> StatProfile:
    try:
        return profiles[profile_key]
    except KeyError as exc:
        known_profiles = ", ".join(sorted(profiles))
        raise KeyError(
            f"unknown {species} test profile {profile_key!r}; "
            f"known profiles: {known_profiles}"
        ) from exc


class BattleMoveFactory:
    """Factory for damage-calculation move snapshots."""

    @staticmethod
    def bullet_punch() -> BattleMove:
        return BattleMove(
            name="bullet-punch",
            type=Type.STEEL,
            category=MoveCategory.PHYSICAL,
            power=40,
        )

    @staticmethod
    def physical(
        *,
        name: str = "physical-test-move",
        move_type: Type = Type.NORMAL,
        power: int = 80,
    ) -> BattleMove:
        return BattleMove(
            name=name,
            type=move_type,
            category=MoveCategory.PHYSICAL,
            power=power,
        )

    @staticmethod
    def special(
        *,
        name: str = "special-test-move",
        move_type: Type = Type.NORMAL,
        power: int = 80,
    ) -> BattleMove:
        return BattleMove(
            name=name,
            type=move_type,
            category=MoveCategory.SPECIAL,
            power=power,
        )


class MoveProfileFactory:
    """Factory for minimal status-gate move profiles."""

    @staticmethod
    def physical(name: str = "tackle") -> MoveProfile:
        return MoveProfile(name=name, damage_class=MoveCategory.PHYSICAL)

    @staticmethod
    def special(name: str = "water-gun") -> MoveProfile:
        return MoveProfile(name=name, damage_class=MoveCategory.SPECIAL)

    @staticmethod
    def status(name: str = "tail-whip") -> MoveProfile:
        return MoveProfile(name=name, damage_class=MoveCategory.STATUS)

    @staticmethod
    def thawing_physical(name: str = "flame-wheel-like") -> MoveProfile:
        return MoveProfile(
            name=name,
            damage_class=MoveCategory.PHYSICAL,
            flags=frozenset((MoveFlag.THAWS_USER_WHEN_FROZEN,)),
        )


class CombatantStatusFactory:
    """Factory for common combatant status snapshots."""

    @staticmethod
    def sleeping(turns_asleep: int = 0) -> CombatantStatus:
        return CombatantStatus(non_volatile=SleepStatus(turns_asleep=turns_asleep))

    @staticmethod
    def paralyzed() -> CombatantStatus:
        return CombatantStatus(non_volatile=ParalysisStatus())

    @staticmethod
    def burned() -> CombatantStatus:
        return CombatantStatus(non_volatile=BurnStatus())

    @staticmethod
    def frozen() -> CombatantStatus:
        return CombatantStatus(non_volatile=FreezeStatus())

    @staticmethod
    def confused() -> CombatantStatus:
        return CombatantStatus(volatile=frozenset((ConfusionStatus(),)))

    @staticmethod
    def infatuated() -> CombatantStatus:
        return CombatantStatus(volatile=frozenset((InfatuationStatus(),)))

    @staticmethod
    def confused_and_infatuated(
        non_volatile: NonVolatileStatus | None = None,
    ) -> CombatantStatus:
        return CombatantStatus(
            non_volatile=non_volatile,
            volatile=frozenset((ConfusionStatus(), InfatuationStatus())),
        )

    @staticmethod
    def paralyzed_and_confused() -> CombatantStatus:
        return CombatantStatus(
            non_volatile=ParalysisStatus(),
            volatile=frozenset((ConfusionStatus(),)),
        )

    @staticmethod
    def with_statuses(
        *,
        non_volatile: NonVolatileStatus | None = None,
        volatile: tuple[VolatileStatus, ...] = (),
    ) -> CombatantStatus:
        return CombatantStatus(
            non_volatile=non_volatile,
            volatile=frozenset(volatile),
        )

    @staticmethod
    def persistent_non_volatile_statuses() -> tuple[NonVolatileStatus, ...]:
        return (
            SleepStatus(),
            ParalysisStatus(),
            BurnStatus(),
            FreezeStatus(),
            PoisonStatus(),
            BadPoisonStatus(),
        )


class FixedBattleRandom:
    """Deterministic RNG for status-policy tests."""

    def __init__(self, results: list[bool]):
        self.results = list(results)
        self.probabilities: list[Fraction | float] = []

    def chance(self, probability: Fraction | float) -> bool:
        self.probabilities.append(probability)
        if not self.results:
            raise AssertionError("unexpected random chance call")
        return self.results.pop(0)


__all__ = [
    "BattleMoveFactory",
    "BattlePokemonFactory",
    "CombatantStatusFactory",
    "FixedBattleRandom",
    "LEVEL_50",
    "MoveProfileFactory",
    "PokemonSpec",
]
