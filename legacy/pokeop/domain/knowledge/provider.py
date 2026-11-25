from __future__ import annotations

from typing import Protocol

from pokeop.domain.knowledge.models import MoveKnowledge, PokemonKnowledge
from pokeop.domain.knowledge.ruleset import Ruleset


class KnowledgeError(Exception):
    """Base class for knowledge-provider lookup failures."""


class UnknownRulesetError(KnowledgeError):
    """Raised when a ruleset identifier is not known."""


class UnknownPokemonError(KnowledgeError):
    """Raised when a Pokemon identifier is not known."""


class UnknownMoveError(KnowledgeError):
    """Raised when a move identifier is not known."""


class UnknownTypeError(KnowledgeError):
    """Raised when a type identifier is not known."""


class UnsupportedKnowledgeError(KnowledgeError):
    """Raised when known knowledge is unavailable for the requested ruleset."""


class BattleKnowledgeProvider(Protocol):
    def get_ruleset(self, ruleset: str) -> Ruleset:
        """Return metadata for a battle ruleset."""

    def get_pokemon(self, identifier: str, ruleset: str) -> PokemonKnowledge:
        """Return Pokemon knowledge valid under the requested ruleset."""

    def get_move(self, identifier: str, ruleset: str) -> MoveKnowledge:
        """Return move knowledge valid under the requested ruleset."""

    def type_multiplier(
        self,
        attacking_type: str,
        defending_types: tuple[str, ...],
        ruleset: str,
    ) -> float:
        """Return total type effectiveness for one attacking type."""

    def can_learn_move(self, pokemon: str, move: str, ruleset: str) -> bool:
        """Return whether the Pokemon can learn the move in the ruleset."""


__all__ = [
    "BattleKnowledgeProvider",
    "KnowledgeError",
    "UnknownMoveError",
    "UnknownPokemonError",
    "UnknownRulesetError",
    "UnknownTypeError",
    "UnsupportedKnowledgeError",
]
