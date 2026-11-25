from __future__ import annotations

from dataclasses import dataclass


STANDARD_RANDOM_DAMAGE_MULTIPLIERS: tuple[float, ...] = tuple(
    value / 100 for value in range(85, 101)
)


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
    sandstorm_rock_spdef_multiplier: float | None = 1.5
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
    """集中声明直接伤害阶段使用的规则集倍率和功能边界。

    Attributes:
        multiscale_damage_multiplier: 多重鳞片在持有者满 HP 时应用于直接伤害的倍率；
            默认 0.5，具体规则集可以显式覆盖。
    """

    same_type_attack_bonus_multiplier: float = 1.5
    technician_base_power_threshold: int = 60
    technician_base_power_multiplier: float = 1.5
    adaptability_stab_multiplier: float = 2.0
    thick_fat_damage_multiplier: float = 0.5
    filter_damage_multiplier: float = 0.75
    sniper_critical_multiplier: float = 1.5
    multiscale_damage_multiplier: float = 0.5
    life_orb_damage_multiplier: float = 1.3
    choice_item_attack_multiplier: float = 1.5
    expert_belt_damage_multiplier: float = 1.2
    eviolite_defense_multiplier: float = 1.5
    burn_physical_attack_multiplier: float = 0.5
    random_damage_multipliers: tuple[float, ...] = STANDARD_RANDOM_DAMAGE_MULTIPLIERS

    def __post_init__(self) -> None:
        """校验全部伤害倍率、阈值和随机档位都可安全参与计算。

        Raises:
            ValueError: 任一倍率或技术高手阈值为负，或随机伤害档位为空。
        """
        super().__post_init__()
        _validate_positive_multiplier(
            self.same_type_attack_bonus_multiplier,
            "same_type_attack_bonus_multiplier",
        )
        if self.technician_base_power_threshold < 0:
            raise ValueError("technician_base_power_threshold must not be negative")
        _validate_positive_multiplier(
            self.technician_base_power_multiplier,
            "technician_base_power_multiplier",
        )
        _validate_positive_multiplier(
            self.adaptability_stab_multiplier,
            "adaptability_stab_multiplier",
        )
        _validate_positive_multiplier(
            self.thick_fat_damage_multiplier,
            "thick_fat_damage_multiplier",
        )
        _validate_positive_multiplier(
            self.filter_damage_multiplier,
            "filter_damage_multiplier",
        )
        _validate_positive_multiplier(
            self.sniper_critical_multiplier,
            "sniper_critical_multiplier",
        )
        _validate_positive_multiplier(
            self.multiscale_damage_multiplier,
            "multiscale_damage_multiplier",
        )
        _validate_positive_multiplier(
            self.life_orb_damage_multiplier,
            "life_orb_damage_multiplier",
        )
        _validate_positive_multiplier(
            self.choice_item_attack_multiplier,
            "choice_item_attack_multiplier",
        )
        _validate_positive_multiplier(
            self.expert_belt_damage_multiplier,
            "expert_belt_damage_multiplier",
        )
        _validate_positive_multiplier(
            self.eviolite_defense_multiplier,
            "eviolite_defense_multiplier",
        )
        _validate_positive_multiplier(
            self.burn_physical_attack_multiplier,
            "burn_physical_attack_multiplier",
        )
        if not self.random_damage_multipliers:
            raise ValueError("random_damage_multipliers must not be empty")
        for multiplier in self.random_damage_multipliers:
            _validate_positive_multiplier(multiplier, "random_damage_multipliers")

    @classmethod
    def modern(cls) -> "DamagePolicy":
        """Return the current default Gen9 damage policy."""
        return cls.gen9()

    @classmethod
    def for_generation(cls, generation_id: int) -> "DamagePolicy":
        """Return the damage policy for one concrete Pokemon generation."""
        if generation_id < 1 or generation_id > 9:
            raise ValueError(
                f"unsupported generation_id for damage policy: {generation_id}"
            )
        return getattr(cls, f"gen{generation_id}")()

    @classmethod
    def gen1(cls) -> "DamagePolicy":
        """Return the current Gen1-compatible damage policy profile."""
        return cls._without_sandstorm_spdef()

    @classmethod
    def gen2(cls) -> "DamagePolicy":
        """Return the current Gen2-compatible damage policy profile."""
        return cls._without_sandstorm_spdef()

    @classmethod
    def gen3(cls) -> "DamagePolicy":
        """Return the current Gen3-compatible damage policy profile."""
        return cls._without_sandstorm_spdef()

    @classmethod
    def gen4(cls) -> "DamagePolicy":
        """Return the current Gen4-compatible damage policy profile."""
        return cls._with_sandstorm_spdef_without_terrain()

    @classmethod
    def gen5(cls) -> "DamagePolicy":
        """Return the current Gen5-compatible damage policy profile."""
        return cls._with_sandstorm_spdef_without_terrain()

    @classmethod
    def gen6(cls) -> "DamagePolicy":
        """Return the current Gen6-compatible damage policy profile."""
        return cls._legacy_terrain_without_snow_defense()

    @classmethod
    def gen7(cls) -> "DamagePolicy":
        """Return the current Gen7-compatible damage policy profile."""
        return cls._legacy_terrain_without_snow_defense()

    @classmethod
    def gen8(cls) -> "DamagePolicy":
        """Return the current Gen8-compatible damage policy profile."""
        return cls._modern_terrain_without_snow_defense()

    @classmethod
    def gen9(cls) -> "DamagePolicy":
        """Return the current Gen9-compatible damage policy profile."""
        return cls._modern_terrain_with_snow_defense()

    @classmethod
    def _modern_terrain_with_snow_defense(cls) -> "DamagePolicy":
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
    def _modern_terrain_without_snow_defense(cls) -> "DamagePolicy":
        return cls(
            terrain_boost_multiplier=1.3,
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
    def _legacy_terrain_without_snow_defense(cls) -> "DamagePolicy":
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
    def _with_sandstorm_spdef_without_terrain(cls) -> "DamagePolicy":
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
            critical_hit_multiplier=2.0,
            spread_move_multiplier=0.75,
            protect_damage_multiplier=0.25,
        )

    @classmethod
    def _without_sandstorm_spdef(cls) -> "DamagePolicy":
        return cls(
            terrain_boost_multiplier=1.0,
            weather_boost_multiplier=1.5,
            weather_weaken_multiplier=0.5,
            burn_physical_attack_multiplier=0.5,
            sandstorm_rock_spdef_multiplier=None,
            snow_ice_defense_multiplier=None,
            hail_ice_defense_multiplier=None,
            screen_single_target_multiplier=0.5,
            screen_multi_target_multiplier=2 / 3,
            aurora_veil_single_target_multiplier=0.5,
            aurora_veil_multi_target_multiplier=2 / 3,
            critical_hit_multiplier=2.0,
            spread_move_multiplier=0.75,
            protect_damage_multiplier=0.25,
        )


__all__ = [
    "DamagePolicy",
    "EnvironmentPolicy",
    "STANDARD_RANDOM_DAMAGE_MULTIPLIERS",
]
