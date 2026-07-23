from __future__ import annotations

import inspect
from dataclasses import dataclass
from fractions import Fraction

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import (
    BattleAction,
    InvalidBattleAction,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects.dispatcher import BattleEffectDispatcher
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    ActionValidationResult,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    MoveEffectContext,
    TransitionSet,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattlePhase, BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import CombatantStatus, FlinchStatus
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
)
from pokeop.domain.battle.turn_phases import STABLE_TURN_PHASES
from pokeop.domain.battle.turn_resolver import (
    AccuracyCheckOutcome,
    TurnResolver,
)
from pokeop.domain.models.types import Type


def _coverage(identifier: str) -> EffectCoverage:
    """构造 fake effect 参与 dispatcher 所需的覆盖记录。"""
    return EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier=identifier,
        status=EffectCoverageStatus.SUPPORTED,
        reason="test effect",
    )


def _move_spec(
    move_id: int,
    *,
    name: str,
    priority: int = 0,
    max_pp: int = 5,
) -> MoveSpec:
    """构造 resolver 测试使用的不可变招式配置。"""
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=name,
            type=Type.STEEL,
            category=MoveCategory.PHYSICAL,
            power=40,
        ),
        max_pp=max_pp,
        priority=priority,
    )


def _battler(
    *,
    pokemon_id: int,
    move_id: int,
    speed: int,
    hp: int = 100,
    pp: int = 5,
    priority: int = 0,
    flinched: bool = False,
) -> BattlerState:
    """构造正式状态模型中的单招式测试战斗方。"""
    move = _move_spec(
        move_id,
        name=f"move-{move_id}",
        priority=priority,
    )
    status = (
        CombatantStatus(volatile=frozenset((FlinchStatus(),)))
        if flinched
        else CombatantStatus()
    )
    spec = PokemonSpec(
        pokemon_id=pokemon_id,
        name=f"pokemon-{pokemon_id}",
        level=50,
        types=(Type.STEEL,),
        stats=StatValues(
            hp=100,
            attack=100,
            defense=100,
            special_attack=100,
            special_defense=100,
            speed=speed,
        ),
        ability=DamageAbility.UNKNOWN,
        item=DamageItem.UNKNOWN,
        moves=(move,),
    )
    return BattlerState(
        spec=spec,
        current_hp=hp,
        move_slots=(
            MoveSlotState(
                move_id=move_id,
                current_pp=pp,
                max_pp=move.max_pp,
            ),
        ),
        status=status,
    )


def _state(
    *,
    attacker_speed: int = 100,
    defender_speed: int = 50,
    attacker_priority: int = 0,
    defender_priority: int = 0,
    attacker_pp: int = 5,
    defender_pp: int = 5,
    attacker_flinched: bool = False,
    defender_flinched: bool = False,
) -> BattleState:
    """构造处于 ACTION_SELECTION 的正式 1v1 测试状态。"""
    return BattleState(
        attacker=_battler(
            pokemon_id=1,
            move_id=101,
            speed=attacker_speed,
            pp=attacker_pp,
            priority=attacker_priority,
            flinched=attacker_flinched,
        ),
        defender=_battler(
            pokemon_id=2,
            move_id=202,
            speed=defender_speed,
            pp=defender_pp,
            priority=defender_priority,
            flinched=defender_flinched,
        ),
        rules=BattleInferenceRules(level=50),
    )


def _actions(
    *,
    attacker_priority: int = 0,
    defender_priority: int = 0,
) -> tuple[UseMoveAction, UseMoveAction]:
    """构造与默认测试状态对应的双方行动。"""
    return (
        UseMoveAction(BattleSide.ATTACKER, 101, priority=attacker_priority),
        UseMoveAction(BattleSide.DEFENDER, 202, priority=defender_priority),
    )


@dataclass(frozen=True, slots=True)
class KnockOutTargetAfterDamage:
    """在 AFTER_DAMAGE 阶段把当前行动目标 HP 置零的 fake effect。"""

    coverage: EffectCoverage = _coverage("fake-knockout")

    def after_damage(
        self,
        context: MoveEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """返回目标濒死的新状态，并保持输入分支概率和事件摘要。"""
        target_side = (
            BattleSide.DEFENDER
            if context.actor is BattleSide.ATTACKER
            else BattleSide.ATTACKER
        )
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=transition.state.with_battler(
                    target_side,
                    transition.state.battler(target_side).with_current_hp(0),
                ),
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for transition in transitions
        )


@dataclass(frozen=True, slots=True)
class BlockAttackerAction:
    """在 ValidateActionEffect 阶段阻止攻击方行动的 fake effect。"""

    coverage: EffectCoverage = _coverage("fake-block-attacker")

    def validate_action(
        self,
        context: ActionEffectContext[BattleAction],
    ) -> ActionValidationResult:
        """攻击方返回拒绝裁决，防守方保持允许。"""
        return ActionValidationResult(
            allowed=context.actor is not BattleSide.ATTACKER,
            source_identifier=self.coverage.identifier,
            reason="blocked in test" if context.actor is BattleSide.ATTACKER else "",
        )


@dataclass(frozen=True, slots=True)
class AttackerHitOrMissPolicy:
    """让攻击方以各 1/2 命中或未命中，防守方确定命中的 fake policy。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[AccuracyCheckOutcome, ...]:
        """返回当前行动完整且严格归一化的命中分布。"""
        if context.actor is BattleSide.DEFENDER:
            return (
                AccuracyCheckOutcome(
                    hit=True,
                    transition=WeightedTransition(
                        probability=Fraction(1, 1),
                        state=context.state,
                    ),
                ),
            )
        return (
            self._outcome(context.state, hit=True),
            self._outcome(context.state, hit=False),
        )

    @staticmethod
    def _outcome(state: BattleState, *, hit: bool) -> AccuracyCheckOutcome:
        """为攻击方单个命中结果构造 1/2 概率与类型化事件摘要。"""
        outcome_id = "hit" if hit else "miss"
        event = TransitionEvent(
            event_type=TransitionEventType.HIT_CHECK,
            event_id="attacker-accuracy",
            outcome_id=outcome_id,
        )
        return AccuracyCheckOutcome(
            hit=hit,
            transition=WeightedTransition(
                probability=Fraction(1, 2),
                state=state,
                event_summary=TransitionEventSummary.single(event),
                source_key="turn.accuracy",
            ),
        )


def test_resolver_advances_a_complete_turn_with_formal_state() -> None:
    """完整回合应扣除双方 PP、清理回合状态并进入下一回合。"""
    state = _state(attacker_flinched=True, defender_flinched=True)
    resolution = TurnResolver().resolve(state, *_actions())

    assert resolution.phase_order == STABLE_TURN_PHASES
    assert len(resolution.transitions) == 1
    transition = resolution.transitions[0]
    next_state = transition.state
    assert transition.probability == Fraction(1, 1)
    assert next_state.turn_number == 2
    assert next_state.phase is BattlePhase.ACTION_SELECTION
    assert next_state.attacker.move_slot(101).current_pp == 4
    assert next_state.defender.move_slot(202).current_pp == 4
    assert not next_state.attacker.status.has_volatile(VolatileStatusKind.FLINCH)
    assert not next_state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
    assert next_state.attacker.is_first_turn is False
    assert next_state.defender.is_first_turn is False
    assert hash(next_state.state_key)

    assert state.turn_number == 1
    assert state.attacker.move_slot(101).current_pp == 5
    assert state.defender.move_slot(202).current_pp == 5
    assert state.attacker.status.has_volatile(VolatileStatusKind.FLINCH)
    assert state.defender.status.has_volatile(VolatileStatusKind.FLINCH)


def test_faster_knockout_skips_fainted_sides_action_and_pp_consumption() -> None:
    """先手在 AFTER_DAMAGE 击倒目标后，后手不得行动或消耗 PP。"""
    state = _state(attacker_speed=120, defender_speed=80)
    dispatcher = BattleEffectDispatcher.from_effects((KnockOutTargetAfterDamage(),))

    transition = TurnResolver(effects=dispatcher).resolve(
        state,
        *_actions(),
    ).transitions[0]

    assert transition.state.phase is BattlePhase.TERMINAL
    assert transition.state.defender.current_hp == 0
    assert transition.state.attacker.move_slot(101).current_pp == 4
    assert transition.state.defender.move_slot(202).current_pp == 5


def test_fake_accuracy_policy_creates_weighted_successors() -> None:
    """命中与未命中分支应使用 #23 Fraction 权重并保持最终总和为 1。"""
    dispatcher = BattleEffectDispatcher.from_effects((KnockOutTargetAfterDamage(),))
    resolution = TurnResolver(
        effects=dispatcher,
        accuracy_policy=AttackerHitOrMissPolicy(),
    ).resolve(_state(), *_actions())

    assert len(resolution.transitions) == 2
    assert {transition.probability for transition in resolution.transitions} == {
        Fraction(1, 2)
    }
    assert {
        (
            transition.state.attacker.current_hp,
            transition.state.defender.current_hp,
        )
        for transition in resolution.transitions
    } == {(100, 0), (0, 100)}


def test_speed_tie_keeps_both_possible_action_orders() -> None:
    """完全同速时应生成双方各 1/2 先手的精确状态转移。"""
    dispatcher = BattleEffectDispatcher.from_effects((KnockOutTargetAfterDamage(),))
    resolution = TurnResolver(effects=dispatcher).resolve(
        _state(attacker_speed=100, defender_speed=100),
        *_actions(),
    )

    assert len(resolution.transitions) == 2
    assert {transition.probability for transition in resolution.transitions} == {
        Fraction(1, 2)
    }
    assert {
        (
            transition.state.attacker.current_hp,
            transition.state.defender.current_hp,
        )
        for transition in resolution.transitions
    } == {(100, 0), (0, 100)}
    assert all(
        any(
            event.event_type is TransitionEventType.SPEED_TIE
            for path in transition.event_summary.paths
            for event in path
        )
        for transition in resolution.transitions
    )


def test_validate_action_effect_blocks_without_consuming_pp() -> None:
    """执行前被类型化 effect 阻断的行动不得消耗 PP。"""
    dispatcher = BattleEffectDispatcher.from_effects((BlockAttackerAction(),))
    transition = TurnResolver(effects=dispatcher).resolve(
        _state(),
        *_actions(),
    ).transitions[0]

    assert transition.state.attacker.move_slot(101).current_pp == 5
    assert transition.state.defender.move_slot(202).current_pp == 4


def test_resolver_rejects_action_outside_generated_legal_set() -> None:
    """调用方不能通过伪造 move_id 或 priority 绕过合法行动生成器。"""
    _, defender_action = _actions()

    with pytest.raises(InvalidBattleAction):
        TurnResolver().resolve(
            _state(),
            UseMoveAction(BattleSide.ATTACKER, 999),
            defender_action,
        )


def test_struggle_executes_without_consuming_move_slot_pp() -> None:
    """所有普通槽位无 PP 时，挣扎应执行但不继续扣减普通槽位。"""
    state = _state(attacker_pp=0)
    _, defender_action = _actions()

    transition = TurnResolver().resolve(
        state,
        StruggleAction(BattleSide.ATTACKER),
        defender_action,
    ).transitions[0]

    assert transition.state.attacker.move_slot(101).current_pp == 0
    assert transition.state.defender.move_slot(202).current_pp == 4


def test_resolver_source_contains_no_concrete_mechanism_branches() -> None:
    """稳定模板方法不得出现具体宝可梦或机制 identifier 分支。"""
    source = inspect.getsource(TurnResolver).lower()

    assert "dragonite" not in source
    assert "weavile" not in source
    assert "multiscale" not in source
    assert "fake-out" not in source
