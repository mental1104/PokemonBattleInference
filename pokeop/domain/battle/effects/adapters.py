from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.ability_effects import (
    AbilityDamageEffect,
    AbilityEffectResult,
)
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    AfterMoveSelectedEffect,
    DamageEffectApplication,
    DamageEffectContext,
    DamageEffectResult,
    DamageEffectStage,
    EffectCoverage,
    TransitionSet,
)
from pokeop.domain.battle.item_effects import ItemDamageEffect, ItemEffectResult


def _ability_result(result: AbilityEffectResult | None) -> DamageEffectResult:
    """把旧 ability damage effect 的可空结果转换为统一显式结果。

    Args:
        result: 旧 damage effect 返回的倍率结果；None 表示当前阶段未生效。

    Returns:
        统一 ``DamageEffectResult``，未生效时返回 explicit inactive。
    """
    if result is None:
        return DamageEffectResult.inactive()
    return DamageEffectResult(
        DamageEffectApplication(
            key=result.key,
            multiplier=result.multiplier,
            reason=result.reason,
        )
    )


def _item_result(result: ItemEffectResult | None) -> DamageEffectResult:
    """把旧 item damage effect 的可空结果转换为统一显式结果。

    Args:
        result: 旧 item effect 返回的倍率结果；None 表示当前阶段未生效。

    Returns:
        统一 ``DamageEffectResult``，未生效时返回 explicit inactive。
    """
    if result is None:
        return DamageEffectResult.inactive()
    return DamageEffectResult(
        DamageEffectApplication(
            key=result.key,
            multiplier=result.multiplier,
            reason=result.reason,
        )
    )


@dataclass(frozen=True, slots=True)
class AbilityDamageEffectAdapter:
    """把现有 ``AbilityDamageEffect`` 接入新的窄 ``ModifyDamageEffect`` 协议。

    适配器只翻译阶段调用与结果类型，不改变 Technician、Adaptability、Thick Fat、
    Filter、Solid Rock 或 Sniper 的既有规则实现。
    """

    coverage: EffectCoverage
    wrapped: AbilityDamageEffect

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """按显式伤害阶段调用旧 ability effect 对应能力。

        Args:
            context: 当前伤害上下文、阶段和阶段附加倍率输入。

        Returns:
            当前 ability 在该阶段产生的统一倍率结果；不支持的阶段返回 inactive。
        """
        match context.stage:
            case DamageEffectStage.BASE_POWER:
                return _ability_result(
                    self.wrapped.base_power_multiplier(context.damage_context)
                )
            case DamageEffectStage.STAB:
                return _ability_result(
                    self.wrapped.stab_multiplier(context.damage_context)
                )
            case DamageEffectStage.CRITICAL_HIT:
                return _ability_result(
                    self.wrapped.critical_hit_multiplier(
                        context.damage_context,
                        context.base_multiplier,
                    )
                )
            case DamageEffectStage.FINAL_DAMAGE:
                return _ability_result(
                    self.wrapped.final_damage_multiplier(
                        context.damage_context,
                        context.type_effectiveness,
                    )
                )
            case DamageEffectStage.ATTACK_STAT | DamageEffectStage.DEFENSE_STAT:
                return DamageEffectResult.inactive()
        raise AssertionError(f"unhandled damage effect stage: {context.stage!r}")


@dataclass(frozen=True, slots=True)
class ItemDamageEffectAdapter:
    """把既有道具效果接入伤害与选招后的类型化阶段协议。

    适配器保留 Choice Band、Choice Specs、Eviolite、Life Orb 和 Expert Belt 的旧伤害
    入口；当被包装的具体效果额外实现 ``AfterMoveSelectedEffect`` 时，再显式转发选招
    后状态转换。该兼容层不理解任何道具 identifier，也不自行创建锁招状态。
    """

    coverage: EffectCoverage
    wrapped: ItemDamageEffect

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """按显式伤害阶段调用旧 item effect 对应能力。

        Args:
            context: 当前伤害上下文、阶段和属性克制倍率。

        Returns:
            当前 item 在该阶段产生的统一倍率结果；不支持的阶段返回 inactive。
        """
        match context.stage:
            case DamageEffectStage.ATTACK_STAT:
                return _item_result(
                    self.wrapped.attack_stat_multiplier(context.damage_context)
                )
            case DamageEffectStage.DEFENSE_STAT:
                return _item_result(
                    self.wrapped.defense_stat_multiplier(context.damage_context)
                )
            case DamageEffectStage.FINAL_DAMAGE:
                return _item_result(
                    self.wrapped.final_damage_multiplier(
                        context.damage_context,
                        context.type_effectiveness,
                    )
                )
            case (
                DamageEffectStage.BASE_POWER
                | DamageEffectStage.STAB
                | DamageEffectStage.CRITICAL_HIT
            ):
                return DamageEffectResult.inactive()
        raise AssertionError(f"unhandled damage effect stage: {context.stage!r}")

    def after_move_selected(
        self,
        context: ActionEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """把选招后阶段转发给确实实现该窄协议的具体道具效果。

        Args:
            context: 当前不可变战斗状态、行动方和已选定行动。
            transitions: 当前完整且已归一化的状态转移集合。

        Returns:
            具体道具效果转换后的新转移集合；旧道具只支持伤害阶段时原样返回输入。
        """
        if not isinstance(self.wrapped, AfterMoveSelectedEffect):
            # 兼容旧伤害道具时保持显式 no-op，不把锁招逻辑散落到通用适配器。
            return transitions
        return self.wrapped.after_move_selected(context, transitions)


__all__ = ["AbilityDamageEffectAdapter", "ItemDamageEffectAdapter"]
