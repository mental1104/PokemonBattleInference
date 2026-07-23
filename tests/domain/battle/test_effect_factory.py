from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.effects import (
    BattleEffectDispatcher,
    BattleSide,
    DamageEffectContext,
    DamageEffectStage,
    EffectCoverage,
    EffectCoverageStatus,
    EffectRegistration,
    EffectRegistry,
    EffectSourceKind,
    MoveEffect,
    MoveEffectContext,
    PokemonChampionEffectFactory,
)
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.state import BattleState
from pokeop.domain.battle.transitions import WeightedTransition
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    damage_context,
)


@dataclass(frozen=True, slots=True)
class RegisteredMoveEffect:
    """测试用已注册招式 effect，只在 before-move 阶段变换后继状态。"""

    coverage: EffectCoverage

    def before_move(
        self,
        context: MoveEffectContext[str],
        transitions: tuple[WeightedTransition[BattleState], ...],
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """通过不可变更新把行动方 HP 减一，证明 registry 可接入 #21 状态模型。

        Args:
            context: 包含真实 ``BattleState``、行动方和类型化测试行动的上下文。
            transitions: 已归一化的 #23 带权 ``BattleState`` 分支。

        Returns:
            保留概率和事件摘要、仅替换行动方 HP 的新转移集合。
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


def _registered_move_effect() -> RegisteredMoveEffect:
    """创建属于 Pokemon Champion 规则集的测试招式 effect。

    Returns:
        带 supported 覆盖记录且只实现 ``BeforeMoveEffect`` 的测试产品。
    """
    return RegisteredMoveEffect(
        EffectCoverage(
            ruleset_id=PokemonChampionEffectFactory.RULESET_ID,
            source_kind=EffectSourceKind.MOVE,
            identifier="registered_move",
            status=EffectCoverageStatus.SUPPORTED,
            reason="Test-only registered move effect.",
        )
    )


def test_registry_normalizes_identifiers_and_rejects_duplicates() -> None:
    """registry 应使用稳定标识，并在重复注册时尽早失败。"""
    registration = EffectRegistration(
        identifier="Registered-Move",
        provider=_registered_move_effect,
    )
    registry = EffectRegistry[MoveEffect]((registration,))

    assert registry.identifiers == ("registered_move",)
    assert registry.create(" registered move ") is not None
    with pytest.raises(ValueError, match="duplicate effect registration"):
        registry.with_registration(
            EffectRegistration(
                identifier="registered_move",
                provider=_registered_move_effect,
            )
        )


class TestPokemonChampionEffectFactory:
    """验证具体工厂的产品族、registry 扩展和覆盖语义。"""

    def test_creates_move_ability_and_item_products_from_one_ruleset(self) -> None:
        """同一工厂应创建规则集一致的招式、特性和道具产品。"""
        move_registry = EffectRegistry[MoveEffect](
            (
                EffectRegistration(
                    identifier="registered-move",
                    provider=_registered_move_effect,
                ),
            )
        )
        factory = PokemonChampionEffectFactory(move_registry=move_registry)

        family = factory.create_effect_family(
            move_identifier="registered move",
            ability_identifier=DamageAbility.TECHNICIAN,
            item_identifier=DamageItem.CHOICE_BAND,
        )

        assert tuple(item.ruleset_id for item in family.coverage) == (
            factory.ruleset_id,
            factory.ruleset_id,
            factory.ruleset_id,
        )
        assert tuple(item.status for item in family.coverage) == (
            EffectCoverageStatus.SUPPORTED,
            EffectCoverageStatus.SUPPORTED,
            EffectCoverageStatus.SUPPORTED,
        )
        assert family.move.coverage.identifier == "registered_move"

    def test_new_registered_move_effect_is_dispatched_without_dispatcher_changes(
        self,
    ) -> None:
        """新增实现和注册项后，dispatcher 应自动转换真实 ``BattleState``。"""
        factory = PokemonChampionEffectFactory(
            move_registry=EffectRegistry(
                (EffectRegistration("registered_move", _registered_move_effect),)
            )
        )
        family = factory.create_effect_family(
            move_identifier="registered_move",
            ability_identifier=None,
            item_identifier=None,
        )
        dispatcher = BattleEffectDispatcher[str].from_family(family)
        state = build_effect_test_battle_state()
        context = MoveEffectContext(
            state=state,
            actor=BattleSide.ATTACKER,
            action="sample-action",
        )
        transitions = (
            WeightedTransition(
                probability=Fraction(1, 1),
                state=state,
            ),
        )

        result = dispatcher.before_move(context, transitions)

        assert result[0].state.attacker.current_hp == state.attacker.current_hp - 1
        assert result[0].probability == Fraction(1, 1)
        assert state.attacker.current_hp == state.attacker.spec.stats.hp

    def test_unknown_identifiers_are_reported_as_unsupported(self) -> None:
        """未知机制必须进入覆盖结果，不能伪装成 no-op 或完整支持。"""
        family = PokemonChampionEffectFactory().create_effect_family(
            move_identifier="future-move-effect",
            ability_identifier="future-ability",
            item_identifier="future-item",
        )
        dispatcher = BattleEffectDispatcher[object].from_family(family)

        assert tuple(item.status for item in family.coverage) == (
            EffectCoverageStatus.UNSUPPORTED,
            EffectCoverageStatus.UNSUPPORTED,
            EffectCoverageStatus.UNSUPPORTED,
        )
        assert tuple(item.identifier for item in dispatcher.unsupported_coverage) == (
            "future_move_effect",
            "future_ability",
            "future_item",
        )

    def test_missing_identifiers_use_explicit_no_effect_products(self) -> None:
        """未配置机制应与“输入了但尚未实现”保持不同覆盖状态。"""
        family = PokemonChampionEffectFactory().create_effect_family(
            move_identifier=None,
            ability_identifier=None,
            item_identifier=None,
        )

        assert tuple(item.status for item in family.coverage) == (
            EffectCoverageStatus.NO_EFFECT,
            EffectCoverageStatus.NO_EFFECT,
            EffectCoverageStatus.NO_EFFECT,
        )
        assert tuple(item.identifier for item in family.coverage) == (
            "none",
            "none",
            "none",
        )

    def test_existing_damage_effects_are_available_through_typed_adapters(
        self,
    ) -> None:
        """Technician 和 Choice Band 应通过统一协议保留既有伤害倍率。"""
        family = PokemonChampionEffectFactory().create_effect_family(
            move_identifier=None,
            ability_identifier=DamageAbility.TECHNICIAN,
            item_identifier=DamageItem.CHOICE_BAND,
        )
        dispatcher = BattleEffectDispatcher[object].from_family(family)
        context = damage_context(
            attacker=BattlePokemonFactory.scizor("max_atk_neutral"),
            defender=BattlePokemonFactory.sylveon("max_hp"),
            move=BattleMoveFactory.bullet_punch(),
        )

        base_power = dispatcher.modify_damage(
            DamageEffectContext(context, DamageEffectStage.BASE_POWER)
        )
        attack_stat = dispatcher.modify_damage(
            DamageEffectContext(context, DamageEffectStage.ATTACK_STAT)
        )

        assert tuple(item.multiplier for item in base_power) == (1.5,)
        assert tuple(item.key for item in base_power) == ("ability:technician",)
        assert tuple(item.multiplier for item in attack_stat) == (1.5,)
        assert tuple(item.key for item in attack_stat) == ("item:choice_band",)
