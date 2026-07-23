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
    AfterDamageVolatileStatusEffect,
    AfterMoveSelectedEffect,
    BattleEffect,
    BeforeMoveEffect,
    DamageEffectApplication,
    DamageEffectContext,
    EffectCapabilityCoverage,
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
    VolatileStatusAttempt,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.transitions import (
    WeightedTransition,
    validate_transition_distribution,
)

ActionT = TypeVar("ActionT")


@dataclass(frozen=True, slots=True)
class BattleEffectDispatcher(Generic[ActionT]):
    """按窄 Protocol 能力分发 battle effect，不识别任何具体机制名称。

    dispatcher 在构建时只检查 effect 实现了哪些阶段方法，并把它放入对应的
    类型化序列。所有状态输入与输出统一使用 #21 的 ``BattleState``，所有随机分支
    统一使用 #23 的 ``WeightedTransition``；具体 effect 可以同时实现多个协议，
    未实现的阶段不会收到调用。
    """

    coverage: tuple[EffectCoverage, ...]
    _validate_action_effects: tuple[ValidateActionEffect[ActionT], ...]
    _modify_action_order_effects: tuple[ModifyActionOrderEffect[ActionT], ...]
    _before_move_effects: tuple[BeforeMoveEffect[ActionT], ...]
    _modify_damage_effects: tuple[ModifyDamageEffect, ...]
    _prevent_volatile_status_effects: tuple[PreventVolatileStatusEffect, ...]
    _after_move_selected_effects: tuple[AfterMoveSelectedEffect[ActionT], ...]
    _after_damage_effects: tuple[AfterDamageEffect[ActionT], ...]
    _after_damage_volatile_status_effects: tuple[
        AfterDamageVolatileStatusEffect[ActionT], ...
    ]
    _turn_end_effects: tuple[TurnEndEffect, ...]

    @classmethod
    def from_effects(
        cls,
        effects: Iterable[BattleEffect],
    ) -> "BattleEffectDispatcher[ActionT]":
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
                cast(ValidateActionEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, ValidateActionEffect)
            ),
            _modify_action_order_effects=tuple(
                cast(ModifyActionOrderEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, ModifyActionOrderEffect)
            ),
            _before_move_effects=tuple(
                cast(BeforeMoveEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, BeforeMoveEffect)
            ),
            _modify_damage_effects=tuple(
                cast(ModifyDamageEffect, effect)
                for effect in effect_tuple
                if isinstance(effect, ModifyDamageEffect)
            ),
            _prevent_volatile_status_effects=tuple(
                cast(PreventVolatileStatusEffect, effect)
                for effect in effect_tuple
                if isinstance(effect, PreventVolatileStatusEffect)
            ),
            _after_move_selected_effects=tuple(
                cast(AfterMoveSelectedEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, AfterMoveSelectedEffect)
            ),
            _after_damage_effects=tuple(
                cast(AfterDamageEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, AfterDamageEffect)
            ),
            _after_damage_volatile_status_effects=tuple(
                cast(AfterDamageVolatileStatusEffect[ActionT], effect)
                for effect in effect_tuple
                if isinstance(effect, AfterDamageVolatileStatusEffect)
            ),
            _turn_end_effects=tuple(
                cast(TurnEndEffect, effect)
                for effect in effect_tuple
                if isinstance(effect, TurnEndEffect)
            ),
        )

    @classmethod
    def from_family(
        cls,
        family: BattleEffectFamily,
    ) -> "BattleEffectDispatcher[ActionT]":
        """由抽象工厂创建的完整产品族构建 dispatcher。

        Args:
            family: 同一规则集下的 move、ability、item effect 产品族。

        Returns:
            可供 TurnResolver 或测试替换使用的阶段 dispatcher。
        """
        return cls.from_effects((family.move, family.ability, family.item))

    @property
    def unsupported_coverage(self) -> tuple[EffectCoverage, ...]:
        """返回所有整体明确标记为 unsupported 的机制覆盖记录。"""
        return tuple(
            coverage
            for coverage in self.coverage
            if coverage.status is EffectCoverageStatus.UNSUPPORTED
        )

    @property
    def unsupported_capabilities(self) -> tuple[EffectCapabilityCoverage, ...]:
        """展开并返回已支持 effect 内部尚未覆盖的结构化子机制。"""
        return tuple(
            capability
            for coverage in self.coverage
            for capability in coverage.unsupported_capabilities
        )

    def validate_action(
        self,
        context: ActionEffectContext[ActionT],
    ) -> ActionValidationReport:
        """调用所有行动校验 effect 并返回聚合报告。

        Args:
            context: 当前 ``BattleState``、行动方和候选行动。

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
        context: ActionOrderEffectContext[ActionT],
        initial: ActionOrder,
    ) -> ActionOrder:
        """按注册顺序串行应用行动排序 effect。

        Args:
            context: 当前 ``BattleState``、行动方和行动。
            initial: 规则集和行动本身已经计算出的基础排序键。

        Returns:
            所有排序 effect 依次处理后的新排序键。
        """
        current = initial
        for effect in self._modify_action_order_effects:
            current = effect.modify_action_order(context, current)
        return current

    @staticmethod
    def _validated_transitions(transitions: TransitionSet) -> TransitionSet:
        """校验阶段 effect 返回的精确概率分布，并冻结为 tuple。

        Args:
            transitions: 一个完整随机事件产生的 ``BattleState`` 后继分支。

        Returns:
            概率严格归一化为 1 的不可变转移元组。

        Raises:
            EmptyTransitionSetError: 阶段没有产生任何后继状态。
            UnnormalizedTransitionSetError: 后继分支概率总和不严格等于 1。
        """
        return validate_transition_distribution(transitions)

    def after_move_selected(
        self,
        context: ActionEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """按注册顺序应用选招后 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._after_move_selected_effects:
            current = self._validated_transitions(
                effect.after_move_selected(context, current)
            )
        return current

    def before_move(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
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
        context: VolatileStatusEffectContext,
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
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """依次应用伤害后状态转换和类型化临时状态请求。

        Args:
            context: 当前行动方、类型化行动和进入伤害后阶段的状态。
            transitions: 已完成直接伤害的局部归一化状态分布。

        Returns:
            先执行现有 ``AfterDamageEffect``，再让临时状态请求经过全部阻止 effect
            裁决并以不可变方式写入目标后的归一化分布。
        """
        current = self._validated_transitions(transitions)
        for effect in self._after_damage_effects:
            current = self._validated_transitions(effect.after_damage(context, current))
        return self._apply_after_damage_volatile_status_attempts(context, current)

    def _apply_after_damage_volatile_status_attempts(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """把伤害后 effect 发出的状态请求交给阻止协议并更新每条分支。

        Args:
            context: 当前行动方和类型化行动；分支状态会由每条 transition 单独替换。
            transitions: 已完成其他伤害后转换的归一化状态分布。

        Returns:
            保留概率、事件摘要和来源键，只按裁决结果更新目标状态的新分布。

        Raises:
            ValueError: effect 发出了来源与当前行动方不一致的状态请求时抛出。
        """
        if not self._after_damage_volatile_status_effects:
            return self._validated_transitions(transitions)

        updated_transitions: list[WeightedTransition] = []
        for transition in self._validated_transitions(transitions):
            branch_context = MoveEffectContext(
                state=transition.state,
                actor=context.actor,
                action=context.action,
            )
            attempts = tuple(
                attempt
                for effect in self._after_damage_volatile_status_effects
                for attempt in effect.after_damage_volatile_status_attempts(
                    branch_context
                )
            )
            state = transition.state
            for attempt in attempts:
                self._validate_status_attempt_source(context, attempt)
                if state.battler(attempt.target).current_hp == 0:
                    # 已濒死目标不会携带一个下一阶段无法消费的临时状态。
                    continue
                prevention = self.prevent_volatile_status(
                    VolatileStatusEffectContext(
                        state=state,
                        source=attempt.source,
                        target=attempt.target,
                        status_identifier=attempt.status.kind.value,
                    )
                )
                if prevention.prevented:
                    # 阻止 effect 只裁决请求；dispatcher 统一负责保持目标状态不变。
                    continue
                target = state.battler(attempt.target)
                state = state.with_battler(
                    attempt.target,
                    target.with_status(target.status.add_volatile(attempt.status)),
                )
            updated_transitions.append(
                WeightedTransition(
                    probability=transition.probability,
                    state=state,
                    event_summary=transition.event_summary,
                    source_key=transition.source_key,
                )
            )
        return self._validated_transitions(tuple(updated_transitions))

    @staticmethod
    def _validate_status_attempt_source(
        context: MoveEffectContext[ActionT],
        attempt: VolatileStatusAttempt,
    ) -> None:
        """确认状态请求只能代表当前正在执行的行动方。

        Args:
            context: 当前伤害后阶段的行动上下文。
            attempt: 具体 effect 发出的类型化状态请求。

        Raises:
            ValueError: 请求来源不是当前行动方时抛出，防止 effect 越权代表另一侧行动。
        """
        if attempt.source is not context.actor:
            raise ValueError(
                "volatile status attempt source must match the acting side"
            )

    def on_turn_end(
        self,
        context: TurnEndEffectContext,
        transitions: TransitionSet,
    ) -> TransitionSet:
        """按注册顺序应用回合结束 effect，并校验每一步的概率分布。"""
        current = self._validated_transitions(transitions)
        for effect in self._turn_end_effects:
            current = self._validated_transitions(effect.on_turn_end(context, current))
        return current


__all__ = ["BattleEffectDispatcher"]
