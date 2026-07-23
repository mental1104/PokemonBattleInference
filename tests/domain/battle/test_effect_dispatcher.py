from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Hashable

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.effects import (
    ActionEffectContext,
    ActionOrder,
    ActionOrderEffectContext,
    ActionValidationResult,
    AbilityEffect,
    BattleEffectAbstractFactory,
    BattleEffectDispatcher,
    BattleEffectFamily,
    BattleSide,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    ItemEffect,
    MoveEffect,
    MoveEffectContext,
    NoOpAbilityEffect,
    NoOpItemEffect,
)
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.transitions import (
    UnnormalizedTransitionSetError,
    WeightedTransition,
)


@dataclass(frozen=True, slots=True)
class StubBattleState:
    """测试用不可变状态，以 value 作为稳定状态键。"""

    value: str

    @property
    def state_key(self) -> Hashable:
        """返回 ``WeightedTransition`` 所需的稳定可哈希键。"""
        return self.value


def _coverage(kind: EffectSourceKind, identifier: str) -> EffectCoverage:
    """创建测试 effect 使用的 supported 覆盖记录。"""
    return EffectCoverage(
        ruleset_id="fake-ruleset",
        source_kind=kind,
        identifier=identifier,
        status=EffectCoverageStatus.SUPPORTED,
        reason="Fake effect for dispatcher tests.",
    )


@dataclass(frozen=True, slots=True)
class MultiPhaseMoveEffect:
    """同时实现多个窄协议的测试 effect，用于验证接口隔离分发。"""

    coverage: EffectCoverage

    def validate_action(
        self,
        context: ActionEffectContext[StubBattleState, str],
    ) -> ActionValidationResult:
        """只允许名称不是 blocked 的测试行动。"""
        return ActionValidationResult(
            allowed=context.action != "blocked",
            source_identifier=self.coverage.identifier,
            reason="blocked action" if context.action == "blocked" else "",
        )

    def modify_action_order(
        self,
        context: ActionOrderEffectContext[StubBattleState, str],
        current: ActionOrder,
    ) -> ActionOrder:
        """为测试行动增加一级优先级，并保留速度和同速键。"""
        _ = context
        return ActionOrder(
            priority=current.priority + 1,
            speed=current.speed,
            tie_break=current.tie_break,
        )

    def after_damage(
        self,
        context: MoveEffectContext[StubBattleState, str],
        transitions: tuple[WeightedTransition[StubBattleState], ...],
    ) -> tuple[WeightedTransition[StubBattleState], ...]:
        """返回状态已追加行动说明的新转移，不修改输入 tuple。"""
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=StubBattleState(
                    f"{transition.state.value}|after:{context.action}"
                ),
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for transition in transitions
        )


class FakeBattleEffectFactory:
    """测试用抽象工厂替身，证明 domain 阶段分发不依赖具体工厂。"""

    @property
    def ruleset_id(self) -> str:
        """返回测试规则集标识。"""
        return "fake-ruleset"

    def create_move_effect(self, identifier: str | None) -> MoveEffect:
        """忽略输入标识并返回多阶段测试招式 effect。"""
        return MultiPhaseMoveEffect(
            _coverage(EffectSourceKind.MOVE, identifier or "fake")
        )

    def create_ability_effect(
        self,
        identifier: DamageAbility | str | None,
    ) -> AbilityEffect:
        """返回显式 no-op 特性产品，避免参与任何窄阶段。"""
        _ = identifier
        return NoOpAbilityEffect(
            EffectCoverage(
                self.ruleset_id,
                EffectSourceKind.ABILITY,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "No fake ability effect.",
            )
        )

    def create_item_effect(
        self,
        identifier: DamageItem | str | None,
    ) -> ItemEffect:
        """返回显式 no-op 道具产品，避免参与任何窄阶段。"""
        _ = identifier
        return NoOpItemEffect(
            EffectCoverage(
                self.ruleset_id,
                EffectSourceKind.ITEM,
                "none",
                EffectCoverageStatus.NO_EFFECT,
                "No fake item effect.",
            )
        )

    def create_effect_family(
        self,
        *,
        move_identifier: str | None,
        ability_identifier: DamageAbility | str | None,
        item_identifier: DamageItem | str | None,
    ) -> BattleEffectFamily:
        """创建测试规则集的一组匹配产品。"""
        return BattleEffectFamily(
            move=self.create_move_effect(move_identifier),
            ability=self.create_ability_effect(ability_identifier),
            item=self.create_item_effect(item_identifier),
        )


def test_fake_factory_can_drive_typed_dispatcher_phases() -> None:
    """替换默认工厂后，dispatcher 仍应按 effect 实现的协议执行各阶段。"""
    factory: BattleEffectAbstractFactory = FakeBattleEffectFactory()
    family = factory.create_effect_family(
        move_identifier="multi-phase",
        ability_identifier=None,
        item_identifier=None,
    )
    dispatcher = BattleEffectDispatcher[StubBattleState, str].from_family(family)
    state = StubBattleState("turn-state")
    action_context = ActionEffectContext(
        state=state,
        actor=BattleSide.ATTACKER,
        action="blocked",
    )
    transitions = (
        WeightedTransition(
            probability=Fraction(1, 1),
            state=StubBattleState("initial"),
        ),
    )

    validation = dispatcher.validate_action(action_context)
    order = dispatcher.modify_action_order(
        ActionOrderEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        ActionOrder(priority=0, speed=100),
    )
    before_move = dispatcher.before_move(
        MoveEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        transitions,
    )
    after_damage = dispatcher.after_damage(
        MoveEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        transitions,
    )

    assert validation.allowed is False
    assert validation.decisions[0].source_identifier == "multi-phase"
    assert order == ActionOrder(priority=1, speed=100)
    assert before_move == transitions
    assert after_damage[0].state == StubBattleState("initial|after:blocked")
    assert after_damage[0].probability == Fraction(1, 1)


def test_dispatcher_rejects_unnormalized_transition_input() -> None:
    """阶段入口必须拒绝概率总和不为一的带权转移集合。"""
    factory: BattleEffectAbstractFactory = FakeBattleEffectFactory()
    family = factory.create_effect_family(
        move_identifier="multi-phase",
        ability_identifier=None,
        item_identifier=None,
    )
    dispatcher = BattleEffectDispatcher[StubBattleState, str].from_family(family)
    state = StubBattleState("turn-state")
    transitions = (
        WeightedTransition(
            probability=Fraction(1, 2),
            state=StubBattleState("incomplete-branch"),
        ),
    )

    with pytest.raises(UnnormalizedTransitionSetError):
        dispatcher.before_move(
            MoveEffectContext(
                state=state,
                actor=BattleSide.ATTACKER,
                action="sample-action",
            ),
            transitions,
        )
