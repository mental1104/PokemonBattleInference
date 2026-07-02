from __future__ import annotations

from dataclasses import dataclass


def _validate_positive_multiplier(value: float | None, field_name: str) -> None:
    if value is None:
        return
    if value < 0:
        raise ValueError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class EnvironmentPolicy:
    """
    Rule differences for environment effects that can affect direct damage.

    Future environment hooks belong here before they are wired into the damage
    chain, including Reflect, Light Screen, Aurora Veil, Gravity, Protect,
    spread moves, critical hits, Tera, Z-Move, and Dynamax differences.
    """

    terrain_boost_multiplier: float = 1.3
    misty_terrain_dragon_multiplier: float = 0.5
    weather_boost_multiplier: float = 1.5
    weather_weaken_multiplier: float = 0.5
    sandstorm_rock_spdef_multiplier: float = 1.5
    snow_ice_defense_multiplier: float | None = 1.5
    hail_ice_defense_multiplier: float | None = None
    screen_single_target_multiplier: float = 0.5
    screen_multi_target_multiplier: float = 2 / 3
    aurora_veil_single_target_multiplier: float = 0.5
    aurora_veil_multi_target_multiplier: float = 2 / 3
    critical_hit_multiplier: float = 1.5
    spread_move_multiplier: float = 0.75
    protect_damage_multiplier: float = 0.25

    def __post_init__(self) -> None:
        _validate_positive_multiplier(
            self.terrain_boost_multiplier,
            "terrain_boost_multiplier",
        )
        _validate_positive_multiplier(
            self.misty_terrain_dragon_multiplier,
            "misty_terrain_dragon_multiplier",
        )
        _validate_positive_multiplier(
            self.weather_boost_multiplier,
            "weather_boost_multiplier",
        )
        _validate_positive_multiplier(
            self.weather_weaken_multiplier,
            "weather_weaken_multiplier",
        )
        _validate_positive_multiplier(
            self.sandstorm_rock_spdef_multiplier,
            "sandstorm_rock_spdef_multiplier",
        )
        _validate_positive_multiplier(
            self.snow_ice_defense_multiplier,
            "snow_ice_defense_multiplier",
        )
        _validate_positive_multiplier(
            self.hail_ice_defense_multiplier,
            "hail_ice_defense_multiplier",
        )
        _validate_positive_multiplier(
            self.screen_single_target_multiplier,
            "screen_single_target_multiplier",
        )
        _validate_positive_multiplier(
            self.screen_multi_target_multiplier,
            "screen_multi_target_multiplier",
        )
        _validate_positive_multiplier(
            self.aurora_veil_single_target_multiplier,
            "aurora_veil_single_target_multiplier",
        )
        _validate_positive_multiplier(
            self.aurora_veil_multi_target_multiplier,
            "aurora_veil_multi_target_multiplier",
        )
        _validate_positive_multiplier(
            self.critical_hit_multiplier,
            "critical_hit_multiplier",
        )
        _validate_positive_multiplier(
            self.spread_move_multiplier,
            "spread_move_multiplier",
        )
        _validate_positive_multiplier(
            self.protect_damage_multiplier,
            "protect_damage_multiplier",
        )


@dataclass(frozen=True)
class DamagePolicy(EnvironmentPolicy):
    """Battle ruleset policy for direct-damage multipliers and feature gates."""

    burn_physical_attack_multiplier: float = 0.5

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_positive_multiplier(
            self.burn_physical_attack_multiplier,
            "burn_physical_attack_multiplier",
        )

    @classmethod
    def modern(cls) -> "DamagePolicy":
        """Return the current default modern damage policy."""
        return cls(
            terrain_boost_multiplier=1.3,
            weather_boost_multiplier=1.5,
            weather_weaken_multiplier=0.5,
            burn_physical_attack_multiplier=0.5,
            sandstorm_rock_spdef_multiplier=1.5,
            snow_ice_defense_multiplier=1.5,
            hail_ice_defense_multiplier=None,
            screen_single_target_multiplier=0.5,
            screen_multi_target_multiplier=2 / 3,
            aurora_veil_single_target_multiplier=0.5,
            aurora_veil_multi_target_multiplier=2 / 3,
            critical_hit_multiplier=1.5,
            spread_move_multiplier=0.75,
            protect_damage_multiplier=0.25,
        )

    @classmethod
    def gen6_or_gen7(cls) -> "DamagePolicy":
        """Return a policy shape for Gen6/Gen7-style terrain and hail rules."""
        return cls(
            terrain_boost_multiplier=1.5,
            weather_boost_multiplier=1.5,
            weather_weaken_multiplier=0.5,
            burn_physical_attack_multiplier=0.5,
            sandstorm_rock_spdef_multiplier=1.5,
            snow_ice_defense_multiplier=None,
            hail_ice_defense_multiplier=None,
            screen_single_target_multiplier=0.5,
            screen_multi_target_multiplier=2 / 3,
            aurora_veil_single_target_multiplier=0.5,
            aurora_veil_multi_target_multiplier=2 / 3,
            critical_hit_multiplier=1.5,
            spread_move_multiplier=0.75,
            protect_damage_multiplier=0.25,
        )

    @classmethod
    def gen5(cls) -> "DamagePolicy":
        """Return a pre-terrain policy shape with old hail behavior."""
        return cls(
            terrain_boost_multiplier=1.0,
            weather_boost_multiplier=1.5,
            weather_weaken_multiplier=0.5,
            burn_physical_attack_multiplier=0.5,
            sandstorm_rock_spdef_multiplier=1.5,
            snow_ice_defense_multiplier=None,
            hail_ice_defense_multiplier=None,
            screen_single_target_multiplier=0.5,
            screen_multi_target_multiplier=2 / 3,
            aurora_veil_single_target_multiplier=0.5,
            aurora_veil_multi_target_multiplier=2 / 3,
            critical_hit_multiplier=1.5,
            spread_move_multiplier=0.75,
            protect_damage_multiplier=0.25,
        )


__all__ = ["DamagePolicy", "EnvironmentPolicy"]
