from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from math import floor

from pokeop.domain.battle.actions import (
    BattleAction,
    LegalActionGenerator,
    PassAction,
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.context import (
    BattlePokemon,
    DamageContext,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.damage import DamageRollResult, calculate_damage_rolls
from pokeop.domain.battle.effects.dispatcher import BattleEffectDispatcher
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    ActionOrder,
    ActionValidationResult,
    BattleEffect,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    MoveEffectContext,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import calculate_base_damage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
    damage_rolls_to_transitions,
)
from pokeop.domain.battle.turn_resolver import (
    AccuracyCheckOutcome,
    ActionOrderPolicy,
    DamageResolutionPolicy,
    TurnResolution,
    TurnResolver,
)


def _deterministic_transition(state: BattleState) -> WeightedTransition[BattleState]:
    """把确定性的执行结果包装为概率 1 的战斗随机转移。

    Args:
        state: 需要继续进入回合管线的不可变战斗状态。

    Returns:
        不附带随机事件摘要、概率严格为 1 的 ``WeightedTransition``。
    """
    return WeightedTransition(probability=Fraction(1, 1), state=state)


def _opponent_side(side: BattleSide) -> BattleSide:
    """返回指定 1v1 战斗侧的对手侧。

    Args:
        side: 当前行动所属的稳定战斗侧。

    Returns:
        与输入相反的另一侧。
    """
    return (
        BattleSide.DEFENDER
        if side is BattleSide.ATTACKER
        else BattleSide.ATTACKER
    )


def _action_priority(action: BattleAction) -> int:
    """读取类型化行动的基础优先级。

    Args:
        action: 普通招式、挣扎或内部 Pass 行动。

    Returns:
        普通招式声明的优先级；挣扎为 0；Pass 使用极低值保证最后处理。
    """
    if isinstance(action, UseMoveAction):
        return action.priority
    if isinstance(action, StruggleAction):
        return 0
    return -10_000


def _effective_speed(battler: BattlerState) -> int:
    """按当前速度能力等级计算首版有效速度。

    首版只处理 ``StatStages.speed``，不提前实现麻痹、顺风、天气特性或道具修正；
    这些差异应继续通过 ``ModifyActionOrderEffect`` 接入。

    Args:
        battler: 需要计算行动顺序的当前战斗方状态。

    Returns:
        应用 -6 到 +6 速度等级后的正整数速度。
    """
    base_speed = battler.spec.stats.speed
    stage = battler.stat_stages.speed
    if stage >= 0:
        return max(1, base_speed * (2 + stage) // 2)
    return max(1, base_speed * 2 // (2 - stage))


@dataclass(frozen=True, slots=True)
class EffectiveSpeedActionOrderPolicy(ActionOrderPolicy):
    """按招式优先级和速度能力等级后的有效速度构造基础行动顺序。"""

    def base_order(self, state: BattleState, action: BattleAction) -> ActionOrder:
        """为单个行动生成可继续交给排序 effect 调整的基础键。

        Args:
            state: 当前不可变战斗节点。
            action: 需要排序的类型化行动。

        Returns:
            包含行动优先级与行动方有效速度的 ``ActionOrder``。
        """
        return ActionOrder(
            priority=_action_priority(action),
            speed=_effective_speed(state.battler(action.side)),
        )


@dataclass(frozen=True, slots=True)
class MoveAccuracyCheckPolicy:
    """把 ``MoveSpec.accuracy`` 转换为精确命中与未命中分支。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[AccuracyCheckOutcome, ...]:
        """返回当前行动的完整命中概率分布。

        Args:
            context: 已完成执行前校验与 PP 消耗的招式执行上下文。

        Returns:
            挣扎、Pass 或 ``accuracy=None`` 的招式返回确定命中；普通百分制命中率
            返回使用 ``Fraction`` 表达的命中与未命中分支。
        """
        action = context.action
        if not isinstance(action, UseMoveAction):
            return (
                AccuracyCheckOutcome(
                    hit=True,
                    transition=_deterministic_transition(context.state),
                ),
            )

        move = context.state.battler(context.actor).spec.move_spec(action.move_id)
        denominator = context.state.rules.move_execution_policy.accuracy_denominator
        if move.accuracy is None or move.accuracy == denominator:
            return (
                AccuracyCheckOutcome(
                    hit=True,
                    transition=_deterministic_transition(context.state),
                ),
            )

        hit_probability = Fraction(move.accuracy, denominator)
        return (
            self._outcome(context, hit=True, probability=hit_probability),
            self._outcome(
                context,
                hit=False,
                probability=Fraction(1, 1) - hit_probability,
            ),
        )

    @staticmethod
    def _outcome(
        context: MoveEffectContext[BattleAction],
        *,
        hit: bool,
        probability: Fraction,
    ) -> AccuracyCheckOutcome:
        """构造一条带类型化命中事件的局部概率分支。

        Args:
            context: 当前行动的状态与行动方。
            hit: 当前分支是否命中。
            probability: 当前分支的精确概率，必须大于 0。

        Returns:
            可由 ``TurnResolver`` 与父路径继续组合的 ``AccuracyCheckOutcome``。
        """
        action = context.action
        move_id = action.move_id if isinstance(action, UseMoveAction) else 0
        outcome_id = "hit" if hit else "miss"
        event = TransitionEvent(
            event_type=TransitionEventType.HIT_CHECK,
            event_id=(
                f"turn-{context.state.turn_number}-"
                f"{context.actor.value}-move-{move_id}-accuracy"
            ),
            outcome_id=outcome_id,
        )
        return AccuracyCheckOutcome(
            hit=hit,
            transition=WeightedTransition(
                probability=probability,
                state=context.state,
                event_summary=TransitionEventSummary.single(event),
                source_key="turn.accuracy",
            ),
        )


@dataclass(frozen=True, slots=True)
class FlinchActionGateEffect:
    """实现通用畏缩状态对尚未行动一方的执行前阻断。

    该 effect 不负责施加畏缩，也不识别产生畏缩的具体招式。先行动作通过其他
    ``AfterDamageEffect`` 写入 ``FlinchStatus`` 后，后手在自己的校验阶段读取该状态；
    已经完成行动的一方不会被追溯取消。回合末清理由稳定 ``TurnResolver`` 负责。
    """

    coverage: EffectCoverage = EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier="flinch",
        status=EffectCoverageStatus.SUPPORTED,
        reason="Core volatile flinch action gate.",
    )

    def validate_action(
        self,
        context: ActionEffectContext[BattleAction],
    ) -> ActionValidationResult:
        """判断行动方当前是否因畏缩而不能执行行动。

        Args:
            context: 当前战斗状态、行动方与待执行行动。

        Returns:
            没有畏缩时允许执行；存在畏缩时拒绝，并由 resolver 保持 PP 不变。
        """
        flinched = context.state.battler(context.actor).status.has_volatile(
            VolatileStatusKind.FLINCH
        )
        return ActionValidationResult(
            allowed=not flinched,
            source_identifier=self.coverage.identifier,
            reason="Actor flinched before acting." if flinched else "",
        )


@dataclass(frozen=True, slots=True)
class StandardMoveDamagePolicy(DamageResolutionPolicy):
    """复用现有伤害链生成普通招式和挣扎的精确 HP 状态转移。

    普通物理/特殊招式继续调用 ``calculate_damage_rolls``，不会复制第二套完整伤害
    公式。挣扎只使用首版 policy 声明的基础威力、现有随机伤害档位和最大 HP 反伤；
    接触、多段、会心、吸血、固定伤害与 OHKO 保留给后续窄策略或 effect。
    """

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """把已命中的行动转换为伤害和反伤后的状态分布。

        Args:
            context: 已完成 PP 消耗和命中判定的行动上下文。

        Returns:
            概率严格归一化、按 ``StateKey`` 合并的伤害后继状态。变化招式当前返回
            不改变 HP 的确定性分支。
        """
        if isinstance(context.action, StruggleAction):
            return self._resolve_struggle(context)
        if isinstance(context.action, UseMoveAction):
            return self._resolve_configured_move(context)
        return (_deterministic_transition(context.state),)

    def _resolve_configured_move(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """调用现有伤害计算入口处理一项普通配置招式。

        Args:
            context: 当前行动必须是 ``UseMoveAction`` 的执行上下文。

        Returns:
            16 档伤害转换并归并后的 HP 状态分布；变化招式返回确定性原状态。
        """
        action = context.action
        if not isinstance(action, UseMoveAction):
            raise TypeError("configured move damage requires UseMoveAction")
        move_spec = context.state.battler(context.actor).spec.move_spec(action.move_id)
        if move_spec.move.category is MoveCategory.STATUS:
            return (_deterministic_transition(context.state),)

        damage_result = calculate_damage_rolls(
            self._damage_context(
                state=context.state,
                actor=context.actor,
                move_id=action.move_id,
            )
        )
        target_side = _opponent_side(context.actor)
        return damage_rolls_to_transitions(
            state=context.state,
            damage_result=damage_result,
            apply_damage=lambda state, damage: self._apply_direct_damage(
                state,
                target_side=target_side,
                damage=damage,
            ),
            event_id=(
                f"turn-{context.state.turn_number}-"
                f"{context.actor.value}-move-{action.move_id}-damage"
            ),
            source_key="damage.random-roll",
        )

    def _resolve_struggle(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """计算挣扎的基础伤害、16 档随机伤害和最大 HP 反伤。

        Args:
            context: 当前行动必须是 ``StruggleAction`` 的执行上下文。

        Returns:
            每个伤害档同时更新目标 HP 和使用者反伤后的状态分布。多个档位导致相同
            双方 HP 时会由 ``damage_rolls_to_transitions`` 自动归并。
        """
        if not isinstance(context.action, StruggleAction):
            raise TypeError("struggle damage requires StruggleAction")
        actor = context.state.battler(context.actor)
        target = context.state.opponent(context.actor)
        policy = context.state.rules.move_execution_policy
        base_damage = calculate_base_damage(
            level=actor.spec.level,
            power=policy.struggle_power,
            attack=actor.spec.stats.attack,
            defense=target.spec.stats.defense,
        )
        rolls = tuple(
            floor(base_damage * multiplier)
            for multiplier in context.state.rules.damage_policy.random_damage_multipliers
        )
        damage_result = DamageRollResult(
            rolls=rolls,
            defender_hp=target.spec.stats.hp,
            applied_modifiers=(),
        )
        target_side = _opponent_side(context.actor)
        recoil = max(
            1,
            floor(actor.spec.stats.hp * policy.struggle_recoil_fraction),
        )
        return damage_rolls_to_transitions(
            state=context.state,
            damage_result=damage_result,
            apply_damage=lambda state, damage: self._apply_struggle_damage(
                state,
                actor_side=context.actor,
                target_side=target_side,
                damage=damage,
                recoil=recoil,
            ),
            event_id=(
                f"turn-{context.state.turn_number}-"
                f"{context.actor.value}-struggle-damage"
            ),
            source_key="damage.struggle",
        )

    @staticmethod
    def _damage_context(
        *,
        state: BattleState,
        actor: BattleSide,
        move_id: int,
    ) -> DamageContext:
        """在 PP 已扣除后构造可交给旧伤害链的只读快照。

        ``BattleState.damage_context_for`` 会拒绝 PP 已降到 0 的槽位，适合行动选择前
        的查询边界；通用执行器需要允许最后 1 PP 在扣除后继续完成伤害，因此在这里
        从已验证的配置招式和双方快照直接构造上下文。

        Args:
            state: PP 消耗完成后的不可变战斗状态。
            actor: 当前行动方。
            move_id: 已由合法行动生成器验证的配置招式 ID。

        Returns:
            使用当前场地和 ``BattleInferenceRules.damage_policy`` 的 ``DamageContext``。
        """
        attacker = state.battler(actor)
        defender = state.opponent(actor)
        configured_move = attacker.spec.move_spec(move_id)
        modern = BattleRulesetProfile.modern()
        damage_ruleset = replace(
            modern,
            ruleset_id=state.rules.ruleset_id,
            version_group_id=state.rules.version_group_id,
            damage_policy=state.rules.damage_policy,
        )
        return (
            DamageContextBuilder.for_move(
                attacker=StandardMoveDamagePolicy._pokemon_snapshot(attacker),
                defender=StandardMoveDamagePolicy._pokemon_snapshot(defender),
                move=configured_move.move,
            )
            .with_ruleset(damage_ruleset)
            .with_environment(state.field.damage_environment_for(actor))
            .build()
        )

    @staticmethod
    def _pokemon_snapshot(battler: BattlerState) -> BattlePokemon:
        """把当前战斗方状态转换为现有伤害入口使用的快照。

        Args:
            battler: 当前不可变战斗方状态。

        Returns:
            保留等级、属性、最终能力、有效特性和未消耗道具的 ``BattlePokemon``。
        """
        return BattlePokemon(
            name=battler.spec.name,
            level=battler.spec.level,
            types=battler.spec.types,
            stats=battler.spec.stats,
            ability=battler.spec.ability,
            item=DamageItem.UNKNOWN if battler.item_consumed else battler.spec.item,
            can_evolve=battler.spec.can_evolve,
            grounding_state=battler.spec.grounding_state,
        )

    @staticmethod
    def _apply_direct_damage(
        state: BattleState,
        *,
        target_side: BattleSide,
        damage: int,
    ) -> BattleState:
        """对目标 HP 应用一档非负直接伤害。

        Args:
            state: 伤害发生前的不可变状态。
            target_side: 接收本次直接伤害的一方。
            damage: 当前随机档位的非负伤害值。

        Returns:
            目标 HP 在 0 处截断后的新 ``BattleState``。
        """
        target = state.battler(target_side)
        return state.with_battler(
            target_side,
            target.with_current_hp(max(0, target.current_hp - damage)),
        )

    @staticmethod
    def _apply_struggle_damage(
        state: BattleState,
        *,
        actor_side: BattleSide,
        target_side: BattleSide,
        damage: int,
        recoil: int,
    ) -> BattleState:
        """在同一伤害档中依次写入挣扎目标伤害和使用者反伤。

        Args:
            state: 挣扎伤害发生前的不可变状态。
            actor_side: 使用挣扎的一方。
            target_side: 接收挣扎直接伤害的一方。
            damage: 当前随机档位对目标造成的非负伤害。
            recoil: 按最大 HP 和 ruleset policy 计算出的正整数反伤。

        Returns:
            双方 HP 均在 0 处截断后的新状态，可明确表达同时濒死。
        """
        damaged = StandardMoveDamagePolicy._apply_direct_damage(
            state,
            target_side=target_side,
            damage=damage,
        )
        actor = damaged.battler(actor_side)
        return damaged.with_battler(
            actor_side,
            actor.with_current_hp(max(0, actor.current_hp - recoil)),
        )


@dataclass(frozen=True, slots=True)
class StandardMoveTurnResolver:
    """组装 #27 通用招式执行策略并委托稳定 ``TurnResolver`` 推进完整回合。

    Args:
        effects: 当前规则集抽象工厂创建的招式、特性和道具 effect。通用畏缩门禁会在
            这些 effect 之前自动接入；调用方不需要为每个具体招式重复实现 PP、命中、
            行动顺序、伤害、濒死或回合末清理。
        legal_action_generator: 生成 PP、禁用和讲究锁招约束下合法行动的策略。
    """

    effects: tuple[BattleEffect, ...] = ()
    legal_action_generator: LegalActionGenerator = StandardLegalActionGenerator()

    def __post_init__(self) -> None:
        """冻结调用方提供的 effect 序列，避免外部集合后续变化。"""
        object.__setattr__(self, "effects", tuple(self.effects))

    def legal_actions(
        self,
        state: BattleState,
        side: BattleSide,
    ) -> tuple[BattleAction, ...]:
        """返回一侧当前可由行动策略选择的稳定合法行动集合。

        Args:
            state: 当前行动选择阶段的不可变战斗状态。
            side: 需要生成合法行动的一方。

        Returns:
            普通招式、唯一挣扎或濒死 Pass 组成的非空元组。
        """
        return self.legal_action_generator.generate(state, side)

    def resolve(
        self,
        state: BattleState,
        attacker_action: BattleAction,
        defender_action: BattleAction,
    ) -> TurnResolution:
        """使用标准命中、伤害、有效速度和畏缩语义推进完整回合。

        Args:
            state: 必须处于 ``BattlePhase.ACTION_SELECTION`` 的战斗状态。
            attacker_action: 攻击方从当前合法集合中选择的行动。
            defender_action: 防守方从当前合法集合中选择的行动。

        Returns:
            精确归一化、按状态键归并的完整回合后继状态分布。
        """
        dispatcher = BattleEffectDispatcher.from_effects(
            (FlinchActionGateEffect(), *self.effects)
        )
        return TurnResolver(
            legal_action_generator=self.legal_action_generator,
            action_order_policy=EffectiveSpeedActionOrderPolicy(),
            effects=dispatcher,
            accuracy_policy=MoveAccuracyCheckPolicy(),
            damage_policy=StandardMoveDamagePolicy(),
        ).resolve(state, attacker_action, defender_action)


__all__ = [
    "EffectiveSpeedActionOrderPolicy",
    "FlinchActionGateEffect",
    "MoveAccuracyCheckPolicy",
    "StandardMoveDamagePolicy",
    "StandardMoveTurnResolver",
]
