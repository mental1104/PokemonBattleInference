from __future__ import annotations

from pokeop.domain.knowledge.ruleset import Ruleset


PRE_FAIRY_TYPES = frozenset(
    {
        "normal",
        "fire",
        "water",
        "electric",
        "grass",
        "ice",
        "fighting",
        "poison",
        "ground",
        "flying",
        "psychic",
        "bug",
        "rock",
        "ghost",
        "dragon",
        "dark",
        "steel",
    }
)
MODERN_TYPES = PRE_FAIRY_TYPES | {"fairy"}

_SUPER_EFFECTIVE: dict[str, frozenset[str]] = {
    "normal": frozenset(),
    "fire": frozenset({"grass", "ice", "bug", "steel"}),
    "water": frozenset({"fire", "ground", "rock"}),
    "electric": frozenset({"water", "flying"}),
    "grass": frozenset({"water", "ground", "rock"}),
    "ice": frozenset({"grass", "ground", "flying", "dragon"}),
    "fighting": frozenset({"normal", "ice", "rock", "dark", "steel"}),
    "poison": frozenset({"grass", "fairy"}),
    "ground": frozenset({"fire", "electric", "poison", "rock", "steel"}),
    "flying": frozenset({"grass", "fighting", "bug"}),
    "psychic": frozenset({"fighting", "poison"}),
    "bug": frozenset({"grass", "psychic", "dark"}),
    "rock": frozenset({"fire", "ice", "flying", "bug"}),
    "ghost": frozenset({"psychic", "ghost"}),
    "dragon": frozenset({"dragon"}),
    "dark": frozenset({"psychic", "ghost"}),
    "steel": frozenset({"ice", "rock", "fairy"}),
    "fairy": frozenset({"fighting", "dragon", "dark"}),
}

_NOT_VERY_EFFECTIVE: dict[str, frozenset[str]] = {
    "normal": frozenset({"rock", "steel"}),
    "fire": frozenset({"fire", "water", "rock", "dragon"}),
    "water": frozenset({"water", "grass", "dragon"}),
    "electric": frozenset({"electric", "grass", "dragon"}),
    "grass": frozenset(
        {"fire", "grass", "poison", "flying", "bug", "dragon", "steel"}
    ),
    "ice": frozenset({"fire", "water", "ice", "steel"}),
    "fighting": frozenset({"poison", "flying", "psychic", "bug", "fairy"}),
    "poison": frozenset({"poison", "ground", "rock", "ghost"}),
    "ground": frozenset({"grass", "bug"}),
    "flying": frozenset({"electric", "rock", "steel"}),
    "psychic": frozenset({"psychic", "steel"}),
    "bug": frozenset(
        {"fire", "fighting", "poison", "flying", "ghost", "steel", "fairy"}
    ),
    "rock": frozenset({"fighting", "ground", "steel"}),
    "ghost": frozenset({"dark"}),
    "dragon": frozenset({"steel"}),
    "dark": frozenset({"fighting", "dark", "fairy"}),
    "steel": frozenset({"fire", "water", "electric", "steel"}),
    "fairy": frozenset({"fire", "poison", "steel"}),
}

_IMMUNE: dict[str, frozenset[str]] = {
    "normal": frozenset({"ghost"}),
    "fire": frozenset(),
    "water": frozenset(),
    "electric": frozenset({"ground"}),
    "grass": frozenset(),
    "ice": frozenset(),
    "fighting": frozenset({"ghost"}),
    "poison": frozenset({"steel"}),
    "ground": frozenset({"flying"}),
    "flying": frozenset(),
    "psychic": frozenset({"dark"}),
    "bug": frozenset(),
    "rock": frozenset(),
    "ghost": frozenset({"normal"}),
    "dragon": frozenset({"fairy"}),
    "dark": frozenset(),
    "steel": frozenset(),
    "fairy": frozenset(),
}

_PRE_FAIRY_STEEL_RESISTANCES: dict[tuple[str, str], float] = {
    ("ghost", "steel"): 0.5,
    ("dark", "steel"): 0.5,
}


def supported_types_for_ruleset(ruleset: Ruleset) -> frozenset[str]:
    if ruleset.generation <= 5:
        return PRE_FAIRY_TYPES
    return MODERN_TYPES


def type_pair_multiplier(
    attacking_type: str,
    defending_type: str,
    ruleset: Ruleset,
) -> float:
    if ruleset.generation <= 5:
        override = _PRE_FAIRY_STEEL_RESISTANCES.get((attacking_type, defending_type))
        if override is not None:
            return override

    if defending_type in _IMMUNE[attacking_type]:
        return 0.0
    if defending_type in _SUPER_EFFECTIVE[attacking_type]:
        return 2.0
    if defending_type in _NOT_VERY_EFFECTIVE[attacking_type]:
        return 0.5
    return 1.0


__all__ = [
    "MODERN_TYPES",
    "PRE_FAIRY_TYPES",
    "supported_types_for_ruleset",
    "type_pair_multiplier",
]
