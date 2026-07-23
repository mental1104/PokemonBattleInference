from __future__ import annotations

from dataclasses import dataclass

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
    TransitionBatch,
)
from pokeop.domain.battle.items import DamageItem
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    damage_context,
)


@dataclass(frozen=True, slots=True)
class RegisteredMoveEffect:
    """测试用已注册招式 effect，只在 before-move 阶段追加新转移。"""

    coverage: EffectCoverage

    def before_move(
        self,
        context: MoveEffectContext[str, str],
        transitions: TransitionBatch[str],
    ) -> TransitionBatch[str]:
        """返回追加 actor/action 说明的新批次，证明注册实现可以参与阶段分发。"""
        return TransitionBatch(
            transitions.transitions + (f"{context.actor.value}:{context.action}",)
        )


def _registered_move_effect() -> RegisteredMoveEffect:
    """创建属于 Pokemon Champion 规则集的测试招式 effect。"""
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
        """新增实现和注册项后，既有 dispatcher 应自动识别其窄阶段协议。"""
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
        dispatcher = BattleEffectDispatcher[str, str, str].from_family(family)
        context = MoveEffectContext(
            state="turn-state",
            actor=BattleSide.ATTACKER,
            action="sample-action",
        )

        result = dispatcher.before_move(context, TransitionBatch(("initial",)))

        assert result.transitions == ("initial", "attacker:sample-action")

    def test_unknown_identifiers_are_reported_as_unsupported(self) -> None:
        """未知机制必须进入覆盖结果，不能伪装成 no-op 或完整支持。"""
        family = PokemonChampionEffectFactory().create_effect_family(
            move_identifier="future-move-effect",
            ability_identifier="future-ability",
            item_identifier="future-item",
        )
        dispatcher = BattleEffectDispatcher[object, object, object].from_family(family)

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
        dispatcher = BattleEffectDispatcher[object, object, object].from_family(family)
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
