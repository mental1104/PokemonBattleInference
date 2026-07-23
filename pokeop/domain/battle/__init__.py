"""Pure battle-domain models and calculations."""

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import (
    BattleMove,
    BattlePokemon,
    DamageContext,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState, is_grounded
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.transitions import (
    StateKeyed,
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
    branch_transitions,
    combine_independent_transitions,
    damage_rolls_to_transitions,
    merge_equivalent_transitions,
    normalize_transition_weights,
    validate_transition_distribution,
)
from pokeop.domain.battle.weather import Weather


__all__ = [
    "BattleEnvironment",
    "BattleMove",
    "BattlePokemon",
    "DamageAbility",
    "DamageContext",
    "DamageContextBuilder",
    "DamageItem",
    "GroundingState",
    "ModifierKey",
    "MoveCategory",
    "SideConditions",
    "StateKeyed",
    "Terrain",
    "TransitionEvent",
    "TransitionEventSummary",
    "TransitionEventType",
    "Weather",
    "WeightedTransition",
    "branch_transitions",
    "combine_independent_transitions",
    "damage_rolls_to_transitions",
    "is_grounded",
    "merge_equivalent_transitions",
    "normalize_transition_weights",
    "validate_transition_distribution",
]
