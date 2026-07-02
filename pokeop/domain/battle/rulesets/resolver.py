from __future__ import annotations

from pokeop.domain.battle.rulesets.errors import (
    UnknownGenerationError,
    UnknownVersionGroupError,
)
from pokeop.domain.battle.rulesets.models import BattleRuleset
from pokeop.domain.battle.rulesets.profiles import (
    gen5_ruleset,
    gen6_or_gen7_ruleset,
    modern_ruleset,
)


# Static copy of pokeop/assets_data/version_groups.csv generation_id values.
# Runtime domain ruleset resolution deliberately does not read CSV, database,
# DAO, or persistence objects. A future persistence-backed resolver can replace
# this table once version-group data becomes part of an application use case.
VERSION_GROUP_TO_GENERATION: dict[int, int] = {
    1: 1,  # red-blue
    2: 1,  # yellow
    3: 2,  # gold-silver
    4: 2,  # crystal
    5: 3,  # ruby-sapphire
    6: 3,  # emerald
    7: 3,  # firered-leafgreen
    8: 4,  # diamond-pearl
    9: 4,  # platinum
    10: 4,  # heartgold-soulsilver
    11: 5,  # black-white
    12: 3,  # colosseum
    13: 3,  # xd
    14: 5,  # black-2-white-2
    15: 6,  # x-y
    16: 6,  # omega-ruby-alpha-sapphire
    17: 7,  # sun-moon
    18: 7,  # ultra-sun-ultra-moon
    19: 7,  # lets-go-pikachu-lets-go-eevee
    20: 8,  # sword-shield
    21: 8,  # the-isle-of-armor
    22: 8,  # the-crown-tundra
    23: 8,  # brilliant-diamond-shining-pearl
    24: 8,  # legends-arceus
    25: 9,  # scarlet-violet
    26: 9,  # the-teal-mask
    27: 9,  # the-indigo-disk
    28: 1,  # red-green-japan
    29: 1,  # blue-japan
    30: 9,  # legends-za
    31: 9,  # mega-dimension
}


def resolve_ruleset_by_generation(generation_id: int) -> BattleRuleset:
    """
    Resolve the current domain ruleset profile for a Pokemon generation.

    The profile granularity is intentionally coarse in this first resolver:
    Gen1-Gen5 use the current legacy Gen5-style damage policy, Gen6-Gen7 share
    the terrain-era pre-modern policy, and Gen8-Gen9 use the modern policy.
    """
    if generation_id < 1 or generation_id > 9:
        raise UnknownGenerationError(generation_id)

    if generation_id <= 5:
        return gen5_ruleset(generation_id=generation_id)
    if generation_id <= 7:
        return gen6_or_gen7_ruleset(generation_id=generation_id)
    return modern_ruleset(generation_id=generation_id)


def resolve_ruleset_by_version_group(version_group_id: int) -> BattleRuleset:
    """Resolve the current domain ruleset profile for a PokeAPI version group."""
    try:
        generation_id = VERSION_GROUP_TO_GENERATION[version_group_id]
    except KeyError as exc:
        raise UnknownVersionGroupError(version_group_id) from exc

    if generation_id <= 5:
        return gen5_ruleset(
            generation_id=generation_id,
            version_group_id=version_group_id,
        )
    if generation_id <= 7:
        return gen6_or_gen7_ruleset(
            generation_id=generation_id,
            version_group_id=version_group_id,
        )
    return modern_ruleset(
        generation_id=generation_id,
        version_group_id=version_group_id,
    )


__all__ = [
    "VERSION_GROUP_TO_GENERATION",
    "resolve_ruleset_by_generation",
    "resolve_ruleset_by_version_group",
]
