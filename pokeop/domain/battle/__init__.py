"""Pure battle-domain models and calculations."""

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import (
    BattleAction,
    InvalidBattleAction,
    LegalActionGenerator,
    PassAction,
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.context import (
    BattleMove,
    BattlePokemon,
    DamageContext,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState, is_grounded
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.specs import (
    InvalidBattleState,
    MoveSpec,
    MoveSpecKey,
    PokemonSpec,
    PokemonSpecKey,
)
from pokeop.domain.battle.state import (
    BattleFieldState,
    BattlePhase,
    BattleState,
    BattlerState,
    BattlerStateKey,
    StateKey,
    StatStageField,
    StatStages,
)
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
from pokeop.domain.battle.turn_phases import (
    DEFAULT_TURN_PHASE_POLICY,
    STABLE_TURN_PHASES,
    TurnPhase,
    TurnPhasePolicy,
)
from pokeop.domain.battle.turn_resolver import (
    AccuracyCheckOutcome,
    AccuracyCheckPolicy,
    ActionOrderPolicy,
    AlwaysHitAccuracyCheckPolicy,
    DamageResolutionPolicy,
    InvalidAccuracyDistributionError,
    NoOpDamageResolutionPolicy,
    PrioritySpeedActionOrderPolicy,
    TurnResolution,
    TurnResolutionError,
    TurnResolver,
)
from pokeop.domain.battle.weather import Weather


__all__ = [
    "AccuracyCheckOutcome",
    "AccuracyCheckPolicy",
    "ActionOrderPolicy",
    "AlwaysHitAccuracyCheckPolicy",
    "BattleAction",
    "BattleEnvironment",
    "BattleFieldState",
    "BattleMove",
    "BattlePhase",
    "BattlePokemon",
    "BattleSide",
    "BattleState",
    "BattlerState",
    "BattlerStateKey",
    "DEFAULT_TURN_PHASE_POLICY",
    "DamageAbility",
    "DamageContext",
    "DamageContextBuilder",
    "DamageItem",
    "DamageResolutionPolicy",
    "GroundingState",
    "InvalidAccuracyDistributionError",
    "InvalidBattleAction",
    "InvalidBattleState",
    "LegalActionGenerator",
    "ModifierKey",
    "MoveCategory",
    "MoveSlotState",
    "MoveSpec",
    "MoveSpecKey",
    "NoOpDamageResolutionPolicy",
    "PassAction",
    "PokemonSpec",
    "PokemonSpecKey",
    "PrioritySpeedActionOrderPolicy",
    "STABLE_TURN_PHASES",
    "SideConditions",
    "StandardLegalActionGenerator",
    "StateKey",
    "StateKeyed",
    "StatStageField",
    "StatStages",
    "StruggleAction",
    "Terrain",
    "TransitionEvent",
    "TransitionEventSummary",
    "TransitionEventType",
    "TurnPhase",
    "TurnPhasePolicy",
    "TurnResolution",
    "TurnResolutionError",
    "TurnResolver",
    "UseMoveAction",
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
