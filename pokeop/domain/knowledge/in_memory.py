from __future__ import annotations

import re

from pokeop.domain.knowledge.models import BaseStats, MoveKnowledge, PokemonKnowledge
from pokeop.domain.knowledge.provider import (
    BattleKnowledgeProvider,
    UnknownMoveError,
    UnknownPokemonError,
    UnknownRulesetError,
    UnknownTypeError,
    UnsupportedKnowledgeError,
)
from pokeop.domain.knowledge.ruleset import Ruleset
from pokeop.domain.knowledge.type_chart import (
    MODERN_TYPES,
    supported_types_for_ruleset,
    type_pair_multiplier,
)


_IDENTIFIER_SEPARATOR_PATTERN = re.compile(r"[\s_]+")


def _normalize_identifier(value: str) -> str:
    normalized = _IDENTIFIER_SEPARATOR_PATTERN.sub("-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized)
    return normalized


_RULESETS: dict[str, Ruleset] = {
    "bw": Ruleset(identifier="bw", generation=5, version_group="black-white"),
    "xy": Ruleset(identifier="xy", generation=6, version_group="x-y"),
    "sv": Ruleset(identifier="sv", generation=9, version_group="scarlet-violet"),
}

_POKEMON: dict[str, PokemonKnowledge] = {
    "scizor": PokemonKnowledge(
        identifier="scizor",
        display_name="Scizor",
        types=("bug", "steel"),
        base_stats=BaseStats(
            hp=70,
            attack=130,
            defense=100,
            special_attack=55,
            special_defense=80,
            speed=65,
        ),
    ),
    "sylveon": PokemonKnowledge(
        identifier="sylveon",
        display_name="Sylveon",
        types=("fairy",),
        base_stats=BaseStats(
            hp=95,
            attack=65,
            defense=65,
            special_attack=110,
            special_defense=130,
            speed=60,
        ),
    ),
    "garchomp": PokemonKnowledge(
        identifier="garchomp",
        display_name="Garchomp",
        types=("dragon", "ground"),
        base_stats=BaseStats(
            hp=108,
            attack=130,
            defense=95,
            special_attack=80,
            special_defense=85,
            speed=102,
        ),
    ),
    "gengar": PokemonKnowledge(
        identifier="gengar",
        display_name="Gengar",
        types=("ghost", "poison"),
        base_stats=BaseStats(
            hp=60,
            attack=65,
            defense=60,
            special_attack=130,
            special_defense=75,
            speed=110,
        ),
    ),
}

_MOVES: dict[str, MoveKnowledge] = {
    "bullet-punch": MoveKnowledge(
        identifier="bullet-punch",
        display_name="Bullet Punch",
        type="steel",
        damage_class="physical",
        power=40,
        accuracy=100,
        priority=1,
    ),
    "moonblast": MoveKnowledge(
        identifier="moonblast",
        display_name="Moonblast",
        type="fairy",
        damage_class="special",
        power=95,
        accuracy=100,
        priority=0,
    ),
    "earthquake": MoveKnowledge(
        identifier="earthquake",
        display_name="Earthquake",
        type="ground",
        damage_class="physical",
        power=100,
        accuracy=100,
        priority=0,
    ),
    "shadow-ball": MoveKnowledge(
        identifier="shadow-ball",
        display_name="Shadow Ball",
        type="ghost",
        damage_class="special",
        power=80,
        accuracy=100,
        priority=0,
    ),
    "swords-dance": MoveKnowledge(
        identifier="swords-dance",
        display_name="Swords Dance",
        type="normal",
        damage_class="status",
        power=None,
        accuracy=None,
        priority=0,
    ),
}

_LEARNSETS: dict[tuple[str, str], frozenset[str]] = {
    ("xy", "scizor"): frozenset({"bullet-punch", "swords-dance"}),
    ("xy", "sylveon"): frozenset({"moonblast"}),
    ("xy", "gengar"): frozenset({"shadow-ball"}),
    ("sv", "garchomp"): frozenset({"earthquake"}),
}


class InMemoryBattleKnowledgeProvider(BattleKnowledgeProvider):
    """Small in-memory battle knowledge provider for domain tests."""

    def get_ruleset(self, ruleset: str) -> Ruleset:
        ruleset_id = _normalize_identifier(ruleset)
        try:
            return _RULESETS[ruleset_id]
        except KeyError as error:
            raise UnknownRulesetError(f"unknown ruleset: {ruleset}") from error

    def get_pokemon(self, identifier: str, ruleset: str) -> PokemonKnowledge:
        ruleset_profile = self.get_ruleset(ruleset)
        pokemon_id = _normalize_identifier(identifier)
        try:
            pokemon = _POKEMON[pokemon_id]
        except KeyError as error:
            raise UnknownPokemonError(f"unknown pokemon: {identifier}") from error
        self._validate_types(pokemon.types, ruleset_profile)
        return pokemon

    def get_move(self, identifier: str, ruleset: str) -> MoveKnowledge:
        ruleset_profile = self.get_ruleset(ruleset)
        move_id = _normalize_identifier(identifier)
        try:
            move = _MOVES[move_id]
        except KeyError as error:
            raise UnknownMoveError(f"unknown move: {identifier}") from error
        self._validate_types((move.type,), ruleset_profile)
        return move

    def type_multiplier(
        self,
        attacking_type: str,
        defending_types: tuple[str, ...],
        ruleset: str,
    ) -> float:
        ruleset_profile = self.get_ruleset(ruleset)
        if len(defending_types) not in (1, 2):
            raise UnsupportedKnowledgeError(
                "type multiplier supports one or two defending types"
            )

        attack = _normalize_identifier(attacking_type)
        defenses = tuple(
            _normalize_identifier(defending) for defending in defending_types
        )
        self._validate_types((attack, *defenses), ruleset_profile)

        multiplier = 1.0
        for defending in defenses:
            multiplier *= self._type_pair_multiplier(attack, defending, ruleset_profile)
        return multiplier

    def can_learn_move(self, pokemon: str, move: str, ruleset: str) -> bool:
        ruleset_profile = self.get_ruleset(ruleset)
        pokemon_profile = self.get_pokemon(pokemon, ruleset_profile.identifier)
        move_profile = self.get_move(move, ruleset_profile.identifier)
        return (
            move_profile.identifier
            in _LEARNSETS.get(
                (ruleset_profile.identifier, pokemon_profile.identifier),
                frozenset(),
            )
        )

    def _type_pair_multiplier(
        self,
        attacking_type: str,
        defending_type: str,
        ruleset: Ruleset,
    ) -> float:
        return type_pair_multiplier(attacking_type, defending_type, ruleset)

    def _validate_types(self, types: tuple[str, ...], ruleset: Ruleset) -> None:
        available_types = supported_types_for_ruleset(ruleset)
        for type_ in types:
            if type_ not in MODERN_TYPES:
                raise UnknownTypeError(f"unknown type: {type_!r}")
            if type_ not in available_types:
                raise UnsupportedKnowledgeError(
                    f"type {type_!r} is not available in ruleset {ruleset.identifier!r}"
                )


__all__ = ["InMemoryBattleKnowledgeProvider"]
