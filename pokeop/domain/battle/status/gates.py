from __future__ import annotations

from pokeop.domain.battle.flow.action_gate import ActionGateResult
from pokeop.domain.battle.moves.models import MoveFlag, MoveProfile
from pokeop.domain.battle.rng import BattleRandom
from pokeop.domain.battle.rulesets.models import BattleRuleset
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import (
    CombatantStatus,
    FreezeStatus,
    ParalysisStatus,
    SleepStatus,
)


class SleepGate:
    """Blocks action while sleep remains active."""

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        del move
        sleep = status.non_volatile
        if not isinstance(sleep, SleepStatus):
            return ActionGateResult.allow(status)

        result = ruleset.status_rules.sleep_policy.check_before_action(sleep, rng)
        if result.awoke:
            return ActionGateResult.allow(
                status.clear_non_volatile(),
                reason="sleep_woke_up",
                events=result.events,
            )

        return ActionGateResult.block(
            status.set_non_volatile(result.updated_status),
            reason="sleep",
            events=result.events + ("sleep_blocks_action",),
        )


class FreezeGate:
    """Applies freeze thaw checks before action."""

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        frozen = status.non_volatile
        if not isinstance(frozen, FreezeStatus):
            return ActionGateResult.allow(status)

        policy = ruleset.status_rules.freeze_policy
        if (
            policy.allow_thaw_move_override
            and MoveFlag.THAWS_USER_WHEN_FROZEN in move.flags
        ):
            return ActionGateResult.allow(
                status.clear_non_volatile(),
                reason="freeze_thawed_by_move",
                events=("freeze_thawed_by_move",),
            )

        if rng.chance(policy.thaw_chance):
            return ActionGateResult.allow(
                status.clear_non_volatile(),
                reason="freeze_thawed",
                events=("freeze_thawed",),
            )

        return ActionGateResult.block(
            status,
            reason="freeze",
            events=("freeze_blocks_action",),
        )


class ParalysisGate:
    """Blocks action when full paralysis occurs."""

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        del move
        if not isinstance(status.non_volatile, ParalysisStatus):
            return ActionGateResult.allow(status)

        if rng.chance(ruleset.status_rules.paralysis_policy.full_paralysis_chance):
            return ActionGateResult.block(
                status,
                reason="paralysis",
                events=("paralysis_blocks_action",),
            )

        return ActionGateResult.allow(status)


class InfatuationGate:
    """Blocks action when infatuation immobilizes the combatant."""

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        del move
        if not status.has_volatile(VolatileStatusKind.INFATUATION):
            return ActionGateResult.allow(status)

        if rng.chance(ruleset.status_rules.infatuation_policy.immobilize_chance):
            return ActionGateResult.block(
                status,
                reason="infatuation",
                events=("infatuation_blocks_action",),
            )

        return ActionGateResult.allow(status)


class ConfusionGate:
    """Replaces the selected move with self-hit when confusion triggers."""

    def check_before_action(
        self,
        *,
        status: CombatantStatus,
        move: MoveProfile,
        ruleset: BattleRuleset,
        rng: BattleRandom,
    ) -> ActionGateResult:
        del move
        if not status.has_volatile(VolatileStatusKind.CONFUSION):
            return ActionGateResult.allow(status)

        if rng.chance(ruleset.status_rules.confusion_policy.self_hit_chance):
            return ActionGateResult.replace_with_self_hit(
                status,
                reason="confusion",
                events=("confusion_self_hit",),
            )

        return ActionGateResult.allow(status)


__all__ = [
    "ConfusionGate",
    "FreezeGate",
    "InfatuationGate",
    "ParalysisGate",
    "SleepGate",
]
