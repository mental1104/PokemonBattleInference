from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique
from typing import Protocol

from pokeop.domain.battle.moves.models import MoveProfile
from pokeop.domain.battle.rng import BattleRandom
from pokeop.domain.battle.rulesets.models import BattleRuleset
from pokeop.domain.battle.status.state import CombatantStatus


@unique
class ActionDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REPLACE_WITH_SELF_HIT = "replace_with_self_hit"


@dataclass(frozen=True)
class ActionGateResult:
    decision: ActionDecision
    updated_status: CombatantStatus
    reason: str | None = None
    events: tuple[str, ...] = ()

    @classmethod
    def allow(
        cls,
        status: CombatantStatus,
        *,
        reason: str | None = None,
        events: tuple[str, ...] = (),
    ) -> "ActionGateResult":
        return cls(
            decision=ActionDecision.ALLOW,
            reason=reason,
            updated_status=status,
            events=events,
        )

    @classmethod
    def block(
        cls,
        status: CombatantStatus,
        *,
        reason: str,
        events: tuple[str, ...] = (),
    ) -> "ActionGateResult":
        return cls(
            decision=ActionDecision.BLOCK,
            reason=reason,
            updated_status=status,
            events=events,
        )

    @classmethod
    def replace_with_self_hit(
        cls,
        status: CombatantStatus,
        *,
        reason: str,
        events: tuple[str, ...] = (),
    ) -> "ActionGateResult":
        return cls(
            decision=ActionDecision.REPLACE_WITH_SELF_HIT,
            reason=reason,
            updated_status=status,
            events=events,
        )


class ActionGate(Protocol):
    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        ...


class ActionGatePipeline:
    """Stable pre-action gate chain for status effects."""

    def __init__(self, gates: tuple[ActionGate, ...]) -> None:
        if not gates:
            raise ValueError("action gate pipeline must contain at least one gate")
        self._gates = gates

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        current_status = status
        events: tuple[str, ...] = ()

        for gate in self._gates:
            result = gate.check_before_action(
                status=current_status,
                move=move,
                ruleset=ruleset,
                rng=rng,
            )
            events = events + result.events
            current_status = result.updated_status
            if result.decision is not ActionDecision.ALLOW:
                return ActionGateResult(
                    decision=result.decision,
                    reason=result.reason,
                    updated_status=current_status,
                    events=events,
                )

        return ActionGateResult.allow(current_status, events=events)


def default_action_gate_pipeline() -> ActionGatePipeline:
    """Build the default status gate order used before a combatant acts."""
    from pokeop.domain.battle.status.gates import (
        ConfusionGate,
        FreezeGate,
        InfatuationGate,
        ParalysisGate,
        SleepGate,
    )

    return ActionGatePipeline(
        (
            SleepGate(),
            FreezeGate(),
            ParalysisGate(),
            InfatuationGate(),
            ConfusionGate(),
        )
    )


__all__ = [
    "ActionDecision",
    "ActionGate",
    "ActionGatePipeline",
    "ActionGateResult",
    "default_action_gate_pipeline",
]
