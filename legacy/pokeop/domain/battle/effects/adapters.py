from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

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
    EffectCoverageStatus,
    StatusPreventionResult,
    TransitionSet,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.item_effects import (
    ItemCoverageDetailEffect,
    ItemDamageEffect,
    ItemEffectResult,
)


@runtime_checkable
class _BattleAwareAbilityEffect(Protocol):
    """标记需要读取当前 ``BattleState`` 的特性伤害 effect。

    该私有协议只负责把动态战斗状态暴露给特性实现，不替代旧
    ``AbilityDamageEffect`` 的静态伤害阶段接口。
    """

    def modify_battle_damage(
        self,
        context: DamageEffectContext,
    ) -> DamageEffectResult:
        """返回当前多回合伤害阶段的显式修正结果。

        Args:
            context: 包含旧 ``DamageContext``、当前伤害阶段以及可选动态战斗状态的
                不可变输入。

        Returns:
            当前特性在该阶段产生的统一结果；未生效时返回 explicit inactive。
        """
        ...


@runtime_checkable
class _VolatileStatusPreventingAbilityEffect(Protocol):
    """标记能够阻止临时状态写入的特性 effect。"""

    def prevent_volatile_status(
        self,
        context: VolatileStatusEffectContext,
    ) -> StatusPreventionResult:
        """返回指定临时状态是否应被该特性阻止。

        Args:
            context: 当前状态来源、目标与规范化临时状态标识。

        Returns:
            包含是否阻止、特性来源标识和可选原因的独立裁决。
        """
        ...


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
    """把既有特性效果接入统一伤害与临时状态阶段协议。

    适配器保留 Technician、Adaptability、Thick Fat、Filter、Solid Rock 和 Sniper
    的旧伤害行为；当具体特性额外实现动态伤害或状态阻止协议时，再按结构化能力
    转发。该兼容层不识别任何特性 identifier，也不自行判断具体宝可梦。
    """

    coverage: EffectCoverage
    wrapped: AbilityDamageEffect

    def __post_init__(self) -> None:
        """把具体特性声明的未覆盖能力合并进工厂覆盖记录。

        具体 effect 可以通过 ``unsupported_aspects`` 与 ``partial_support_reason``
        声明垂直切片边界。适配器只负责把该元数据转换为结构化 ``PARTIAL``，不会
        根据 identifier 硬编码某个特性。
        """
        unsupported_aspects = tuple(
            getattr(self.wrapped, "unsupported_aspects", ())
        )
        partial_support_reason = getattr(
            self.wrapped,
            "partial_support_reason",
            "",
        )
        if not unsupported_aspects or not partial_support_reason:
            # 未声明缺口的旧特性继续沿用工厂给出的完整支持记录。
            return
        object.__setattr__(
            self,
            "coverage",
            replace(
                self.coverage,
                status=EffectCoverageStatus.PARTIAL,
                reason=partial_support_reason,
                unsupported_aspects=unsupported_aspects,
            ),
        )

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """按显式伤害阶段调用具体 ability effect 对应能力。

        Args:
            context: 当前伤害上下文、阶段、阶段附加倍率以及可选动态战斗状态。

        Returns:
            当前 ability 在该阶段产生的统一倍率结果；不支持或未生效时返回 inactive。
        """
        if context.battle_state is not None:
            if isinstance(self.wrapped, _BattleAwareAbilityEffect):
                # 实时阶段只分发会自行校验持有者和当前状态的窄 effect，避免把另一侧
                # 的 Filter、Life Orb 等旧快照 effect 错套到当前伤害。
                return self.wrapped.modify_battle_damage(context)
            return DamageEffectResult.inactive()

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

    def prevent_volatile_status(
        self,
        context: VolatileStatusEffectContext,
    ) -> StatusPreventionResult:
        """把临时状态阻止阶段转发给确实实现该窄协议的特性。

        Args:
            context: 当前不可变战斗状态、状态来源、目标方和临时状态标识。

        Returns:
            具体特性的阻止结论；旧伤害特性未实现该协议时返回显式不阻止。
        """
        if isinstance(self.wrapped, _VolatileStatusPreventingAbilityEffect):
            return self.wrapped.prevent_volatile_status(context)
        return StatusPreventionResult(
            prevented=False,
            source_identifier=self.coverage.identifier,
        )


@dataclass(frozen=True, slots=True)
class ItemDamageEffectAdapter:
    """把既有道具效果接入伤害与选招后的类型化阶段协议。

    适配器保留 Choice Band、Choice Specs、Eviolite、Life Orb 和 Expert Belt 的旧伤害
    入口；当被包装的具体效果额外实现 ``AfterMoveSelectedEffect`` 时，再显式转发选招
    后状态转换。该兼容层不理解任何道具 identifier，也不自行创建锁招状态。
    """

    coverage: EffectCoverage
    wrapped: ItemDamageEffect

    def __post_init__(self) -> None:
        """把具体效果声明的覆盖边界合并进工厂所属规则集记录。

        工厂继续负责 ruleset、来源、identifier 与 supported 状态；具体效果只补充 reason。
        合并后的同一份记录会同时写入 adapter 和具体效果副本，保证产品族内外看到的
        规则集与覆盖状态完全一致。
        """
        if not isinstance(self.wrapped, ItemCoverageDetailEffect):
            return
        resolved_coverage = replace(
            self.coverage,
            reason=self.wrapped.coverage_reason,
        )
        object.__setattr__(self, "coverage", resolved_coverage)
        object.__setattr__(
            self,
            "wrapped",
            self.wrapped.with_coverage(resolved_coverage),
        )

    def modify_damage(self, context: DamageEffectContext) -> DamageEffectResult:
        """按显式伤害阶段调用旧 item effect 对应能力。

        Args:
            context: 当前伤害上下文、阶段和属性克制倍率。

        Returns:
            当前 item 在该阶段产生的统一倍率结果；不支持的阶段返回 inactive。
        """
        if context.battle_state is not None:
            # 当前没有读取实时 BattleState 的道具伤害窄协议；旧道具继续只由原伤害链
            # 根据攻击方和防守方快照解析，避免无归属 adapter 在这里重复或错侧生效。
            return DamageEffectResult.inactive()

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
