from __future__ import annotations

from enum import Enum, unique


@unique
class ModifierKey(str, Enum):
    """Trace keys emitted by damage modifiers."""

    ABILITY_UNKNOWN = "ability:unknown"
    ABILITY_TECHNICIAN = "ability:technician"
    ABILITY_ADAPTABILITY = "ability:adaptability"
    ABILITY_THICK_FAT = "ability:thick_fat"
    ABILITY_FILTER = "ability:filter"
    ABILITY_SOLID_ROCK = "ability:solid_rock"
    ABILITY_SNIPER = "ability:sniper"
    ABILITY_MULTISCALE = "ability:multiscale"
    ABILITY_INNER_FOCUS = "ability:inner_focus"

    ITEM_UNKNOWN = "item:unknown"
    ITEM_LIFE_ORB = "item:life_orb"
    ITEM_CHOICE_BAND = "item:choice_band"
    ITEM_CHOICE_SPECS = "item:choice_specs"
    ITEM_EXPERT_BELT = "item:expert_belt"
    ITEM_EVIOLITE = "item:eviolite"

    STAB = "stab"
    TYPE_EFFECTIVENESS = "type_effectiveness"
    CRITICAL_HIT = "critical_hit"
    SPREAD_MOVE = "spread_move"
    PROTECT_REDUCTION = "protect_reduction"
    RANDOM = "random"

    WEATHER_HARSH_SUNLIGHT = "weather:harsh_sunlight"
    WEATHER_RAIN = "weather:rain"
    WEATHER_SANDSTORM = "weather:sandstorm"
    WEATHER_HAIL = "weather:hail"
    WEATHER_SNOW = "weather:snow"

    TERRAIN_ELECTRIC = "terrain:electric_terrain"
    TERRAIN_PSYCHIC = "terrain:psychic_terrain"
    TERRAIN_GRASSY = "terrain:grassy_terrain"
    TERRAIN_MISTY = "terrain:misty_terrain"

    SCREEN_REFLECT = "screen:reflect"
    SCREEN_LIGHT_SCREEN = "screen:light_screen"
    SCREEN_AURORA_VEIL = "screen:aurora_veil"


ModifierKeyLike = ModifierKey | str


__all__ = ["ModifierKey", "ModifierKeyLike"]
