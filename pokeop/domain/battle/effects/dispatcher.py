from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Iterable, TypeVar, cast

from pokeop.domain.battle.effects.factories import BattleEffectFamily
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    ActionOrder,
    ActionOrderEffectContext,
    ActionValidationReport,
    AfterDamageEffect,
    AfterMoveSelectedEffect,
    BattleEffect,
    BeforeMoveEffect,
    DamageEffectApplication,
    DamageEffectContext,
    EffectCoverage,
    EffectCoverageStatus,
    ModifyActionOrderEffect,
    ModifyDamageEffect,
    MoveEffectContext,
    PreventVolatileStatusEffect,
    StatusPreventionReport,
    TransitionSet,
    TurnEndEffect,
    TurnEndEffectContext,
    ValidateActionEffect,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.transitions import StateKeyed, validate_transition_distribution

StateT = TypeVar("StateT", bound=StateKeyed)
ActionT = TypeVar("ActionT")


@dataclass(frozen=True, slots=True)
class BattleEffectDispatcher(Generic[StateT, ActionT]):
    """按窄 Protocol 能力分发 battle effect，不识别任何具体机制名称。

    dispatcher 在构建时只检查 effect 实现了哪些阶段方法，并把它放入对应的
    类型化序列。具体 effect 可以同时实现多个协议；未实现的阶段不会收到调用。
    """

    coverage: tuple[EffectCoverage, ...]
    _validate_action_effects: tuple[ValidateActionEffect[StateT, ActionT], ...]
    _modify_action_order_effects: tuple[
        ModifyActionOrderEffect[StateT, ActionT], ...
    ]
    _before_move_effects: tuple[BeforeMoveEffect[StateT, ActionT], ...]
    _modify_damage_effects: tuple[ModifyDamageEffect, ...]
    _prevent_volatile_status_effects: tuple[
        PreventVolatileStatusEffect[StateT], ...
    ]
    _after_move_selected_effects: tuple[
        AfterMoveSelectedEffect[StateT, ActionT], ...
    ]
    _after_damage_effects: tuple[AfterDamageEffect[StateT, ActionT], ...]
    _turn_end_effects: tuple[TurnEndEffect[StateT], ...]

    @classmethod
    def from_effects(
        cls,
        effects: Iterable[BattleEffect],
    ) -> "BattleEffectDispatcher[StateT, ActionT]":
        """根据 effect 实际实现的窄协议构建 dispatcher。

        Args:
            effects: 抽象工厂创建的 move、ability、item effect 序列。

        Returns:
            仅向实现了对应 Protocol 的 effect 分发阶段事件的新 dispatcher。
        """
        effect_tuple = tuple(effects)
        return cls(
            coverage=tuple(effect.coverage for effect in effect_tuple),
            _validate_action_effects=tuple(
                cast(ValidateActionEffect[StateT, ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, ValidateActionEffect)
            ),
            _modify_action_order_effects=tuple(
                cast(ModifyActionOrderEffect[StateT, ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, ModifyActionOrderEffect)
            ),
            _before_move_effects=tuple(
                cast(BeforeMoveEffect[StateT, ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, BeforeMoveEffect)
            ),
            _modify_damage_effects=tuple(
                cast(ModifyDamageEffect, effect)
                for effect in effect_tuple
                if isinstance(effect, ModifyDamageEffect)
            ),
            _prevent_volatile_status_effects=tuple(
                cast(PreventVolatileStatusEffect[StateT], effect)
                for effect in effect_tuple
                if isinstance(effect, PreventVolatileStatusEffect)
            ),
            _after_move_selected_effects=tuple(
                cast(AfterMoveSelectedEffect[StateT, ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, AfterMoveSelectedEffect)
            ),
            _after_damage_effects=tuple(
                cast(AfterDamageEffect[StateT, ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, AfterDamageEffect)
            ),
            _turn_end_effects=tuple(
                cast(TurnEndEffect[StateT], effect)
                for effect in effect_tuple
                if isinstance(effect, TurnEndEffect)
            ),
        )

    @classmethod
    def from_family(
        cls,
        family: BattleEffectFamily,
    ) -> "BattleEffectDispatcher[StateT, ActionT]":
        """由抽象工厂创建的完整产品族构建 dispatcher。

        Args:
            family: 同一规则集下的 move、ability、item effect 产品族。

        Returns:
            可供 TurnResolver 或测试替换使用的阶段 dispatcher。
        """
        return cls.from_effects((family.move, family.ability, family.item))

    @property
    def unsupported_coverage(self) -> tuple[EffectCoverage, ...]:
        """返回所有明确标记为 unsupported 的机制覆盖记录。"""
        return tuple(
            coverage
            for coverage in self.coverage
            if coverage.status is EffectCoverageStatus.UNSUPPORTED
        )

    def validate_action(
        self,
        context: ActionEffectContext[StateT, ActionT],
    ) -> ActionValidationReport:
        """调用所有行动校验 effect 并返回聚合报告。

        Args:
            context: 当前状态、行动方和候选行动。

        Returns:
            包含每个参与校验 effect 独立结论的不可变报告。
        """
        return ActionValidationReport(
            tuple(
                effect.validate_action(context)
                for effect in self._validate_action_effects
            )
        )

    def modify_action_order(
        self,
        context: ActionOrderEffectContext[StateT, ActionT],
        initial: ActionOrder,
    ) -> ActionOrder:
        """按注册顺序串行应用行动排序 effect。

        Args:
            context: 当前状态、行动方和行动。
            initial: 规则集和行动本身已经计算出的基础排序键。

        Returns:
            所有排序 effect 依次处理后的新排序键。
        """
        current = initial
        for effect in self._modify_action_order_effects:
            current = effect.modify_action_order(context, current)
        return current

    @staticmethod
    def _validated_transitions(
        transitions: TransitionSet[StateT],
    ) -> TransitionSet[StateT]:
        """校验阶段 effect 返回的精确概率分布，并冻结为 tuple。

        Args:
            transitions: 一个完整随机事件产生的带权后继状态集合。

        Returns:
            概率严格归一化为 1 的不可变转移元组。
        """
        return validate_transition_distribution(transitions)

    def after_move_selected(
        self,
        context: ActionEffectContext[StateT, ActionT],
        transitions: TransitionSet[StateT],
    ) -> TransitionSet[StateT]:
        """按注册顺序应用选招后 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._after_move_selected_effects:
            current = self._validated_transitions(
                effect.after_move_selected(context, current)
            )
        return current

    def before_move(
        self,
        context: MoveEffectContext[StateT, ActionT],
        transitions: TransitionSet[StateT],
    ) -> TransitionSet[StateT]:
        """按注册顺序应用招式执行前 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._before_move_effects:
            current = self._validated_transitions(effect.before_move(context, current))
        return current

    def modify_damage(
        self,
        context: DamageEffectContext,
    ) -> tuple[DamageEffectApplication, ...]:
        """调用所有伤害协议 effect，并只收集当前阶段实际生效的结果。

        Args:
            context: 当前伤害阶段及现有 ``DamageContext``。

        Returns:
            按 effect 注册顺序排列的统一倍率修正；未生效结果不会进入集合。
        """
        applications: list[DamageEffectApplication] = []
        for effect in self._modify_damage_effects:
            result = effect.modify_damage(context)
            if result.application is not None:
                applications.append(result.application)
        return tuple(applications)

    def prevent_volatile_status(
        self,
        context: VolatileStatusEffectContext[StateT],
    ) -> StatusPreventionReport:
        """调用所有临时状态阻止 effect 并返回聚合报告。"""
        return StatusPreventionReport(
            tuple(
                effect.prevent_volatile_status(context)
                for effect in self._prevent_volatile_status_effects
            )
        )

    def after_damage(
        self,
        context: MoveEffectContext[StateT, ActionT],
        transitions: TransitionSet[StateT],
    ) -> TransitionSet[StateT]:
        """按注册顺序应用伤害结算后 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._after_damage_effects:
            current = self._validated_transitions(effect.after_damage(context, current))
        return current

    def on_turn_end(
        self,
        context: TurnEndEffectContext[StateT],
        transitions: TransitionSet[StateT],
    ) -> TransitionSet[StateT]:
        """按注册顺序应用回合结束 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._turn_end_effects:
            current = self._validated_transitions(effect.on_turn_end(context, current))
        return current


__all__ = ["BattleEffectDispatcher"]
