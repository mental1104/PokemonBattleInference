from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

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
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


def _coverage(kind: EffectSourceKind, identifier: str) -> EffectCoverage:
    """创建测试 effect 使用的 supported 覆盖记录。

    Args:
        kind: 测试产品所属的 move、ability 或 item 来源类型。
        identifier: 用于断言 dispatcher 分发来源的稳定机制标识。

    Returns:
        属于 fake ruleset 的 supported ``EffectCoverage``。
    """
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
        context: ActionEffectContext[str],
    ) -> ActionValidationResult:
        """只允许名称不是 blocked 的测试行动。

        Args:
            context: 包含真实 ``BattleState``、行动方和字符串测试行动的上下文。

        Returns:
            blocked 行动返回拒绝，其余行动返回允许。
        """
        return ActionValidationResult(
            allowed=context.action != "blocked",
            source_identifier=self.coverage.identifier,
            reason="blocked action" if context.action == "blocked" else "",
        )

    def modify_action_order(
        self,
        context: ActionOrderEffectContext[str],
        current: ActionOrder,
    ) -> ActionOrder:
        """为测试行动增加一级优先级，并保留速度和同速键。

        Args:
            context: 当前真实战斗节点和待排序行动；本测试不读取其具体字段。
            current: 已由行动本身和规则集产生的基础排序键。

        Returns:
            priority 增加一的新 ``ActionOrder``。
        """
        _ = context
        return ActionOrder(
            priority=current.priority + 1,
            speed=current.speed,
            tie_break=current.tie_break,
        )

    def after_damage(
        self,
        context: MoveEffectContext[str],
        transitions: tuple[WeightedTransition, ...],
    ) -> tuple[WeightedTransition, ...]:
        """通过不可变更新把行动方 HP 减一，模拟伤害后续效果。

        Args:
            context: 指出当前行动方和行动的真实 ``BattleState`` 上下文。
            transitions: 已归一化的 #23 带权 ``BattleState`` 后继分支。

        Returns:
            保留概率和事件摘要、仅替换行动方 HP 的新带权分支集合。
        """
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=transition.state.with_battler(
                    context.actor,
                    transition.state.battler(context.actor).with_current_hp(
                        transition.state.battler(context.actor).current_hp - 1
                    ),
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
        """忽略具体业务实现并返回多阶段测试招式 effect。

        Args:
            identifier: 测试机制标识；None 时使用 fake 作为稳定默认值。

        Returns:
            同时实现行动校验、顺序修改和伤害后处理的测试 effect。
        """
        return MultiPhaseMoveEffect(
            _coverage(EffectSourceKind.MOVE, identifier or "fake")
        )

    def create_ability_effect(
        self,
        identifier: DamageAbility | str | None,
    ) -> AbilityEffect:
        """返回显式 no-op 特性产品，避免参与任何窄阶段。

        Args:
            identifier: 调用方提供的特性标识；测试替身不读取该值。

        Returns:
            不实现阶段协议的 ``NoOpAbilityEffect``。
        """
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
        """返回显式 no-op 道具产品，避免参与任何窄阶段。

        Args:
            identifier: 调用方提供的道具标识；测试替身不读取该值。

        Returns:
            不实现阶段协议的 ``NoOpItemEffect``。
        """
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
        """创建测试规则集的一组匹配产品。

        Args:
            move_identifier: 招式机制标识。
            ability_identifier: 特性机制标识。
            item_identifier: 道具机制标识。

        Returns:
            一个多阶段招式 effect 和两个 no-op 产品组成的产品族。
        """
        return BattleEffectFamily(
            move=self.create_move_effect(move_identifier),
            ability=self.create_ability_effect(ability_identifier),
            item=self.create_item_effect(item_identifier),
        )


def test_fake_factory_can_drive_typed_dispatcher_phases() -> None:
    """替换默认工厂后，dispatcher 应直接推进真实 ``BattleState`` 分支。"""
    factory: BattleEffectAbstractFactory = FakeBattleEffectFactory()
    family = factory.create_effect_family(
        move_identifier="multi-phase",
        ability_identifier=None,
        item_identifier=None,
    )
    dispatcher = BattleEffectDispatcher[str].from_family(family)
    state = build_effect_test_battle_state()
    action_context = ActionEffectContext(
        state=state,
        actor=BattleSide.ATTACKER,
        action="blocked",
    )
    transitions = (
        WeightedTransition(
            probability=Fraction(1, 1),
            state=state,
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
    assert after_damage[0].state.attacker.current_hp == state.attacker.current_hp - 1
    assert after_damage[0].probability == Fraction(1, 1)
    assert state.attacker.current_hp == state.attacker.spec.stats.hp


def test_dispatcher_rejects_unnormalized_transition_input() -> None:
    """阶段入口必须拒绝概率总和不为一的真实 ``BattleState`` 分支集合。"""
    factory: BattleEffectAbstractFactory = FakeBattleEffectFactory()
    family = factory.create_effect_family(
        move_identifier="multi-phase",
        ability_identifier=None,
        item_identifier=None,
    )
    dispatcher = BattleEffectDispatcher[str].from_family(family)
    state = build_effect_test_battle_state()
    transitions = (
        WeightedTransition(
            probability=Fraction(1, 2),
            state=state,
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
