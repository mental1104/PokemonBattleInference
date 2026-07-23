from __future__ import annotations

from dataclasses import dataclass

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
    TransitionBatch,
)
from pokeop.domain.battle.items import DamageItem


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
        context: ActionEffectContext[str, str],
    ) -> ActionValidationResult:
        """只允许名称不是 blocked 的测试行动。"""
        return ActionValidationResult(
            allowed=context.action != "blocked",
            source_identifier=self.coverage.identifier,
            reason="blocked action" if context.action == "blocked" else "",
        )

    def modify_action_order(
        self,
        context: ActionOrderEffectContext[str, str],
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
        context: MoveEffectContext[str, str],
        transitions: TransitionBatch[str],
    ) -> TransitionBatch[str]:
        """在伤害后返回追加说明的新批次，不修改输入 tuple。"""
        return TransitionBatch(
            transitions.transitions + (f"after:{context.action}",)
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
        """返回显式 no-op 特性产品，避免参与任何窄阶段。

        Args:
            identifier: 测试不使用的特性标识。

        Returns:
            不实现任何阶段协议的 no-op 特性产品。
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
            identifier: 测试不使用的道具标识。

        Returns:
            不实现任何阶段协议的 no-op 道具产品。
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
    dispatcher = BattleEffectDispatcher[str, str, str].from_family(family)
    action_context = ActionEffectContext(
        state="turn-state",
        actor=BattleSide.ATTACKER,
        action="blocked",
    )

    validation = dispatcher.validate_action(action_context)
    order = dispatcher.modify_action_order(
        ActionOrderEffectContext(
            state="turn-state",
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        ActionOrder(priority=0, speed=100),
    )
    before_move = dispatcher.before_move(
        MoveEffectContext(
            state="turn-state",
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        TransitionBatch(("initial",)),
    )
    after_damage = dispatcher.after_damage(
        MoveEffectContext(
            state="turn-state",
            actor=BattleSide.ATTACKER,
            action="blocked",
        ),
        TransitionBatch(("initial",)),
    )

    assert validation.allowed is False
    assert validation.decisions[0].source_identifier == "multi-phase"
    assert order == ActionOrder(priority=1, speed=100)
    assert before_move.transitions == ("initial",)
    assert after_damage.transitions == ("initial", "after:blocked")
