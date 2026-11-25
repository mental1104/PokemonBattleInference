from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Protocol, runtime_checkable

from pokeop.domain.battle.actions import (
    BattleAction,
    InvalidBattleAction,
    LegalActionGenerator,
    PassAction,
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.effects.dispatcher import BattleEffectDispatcher
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    ActionOrder,
    ActionOrderEffectContext,
    MoveEffectContext,
    TransitionSet,
    TurnEndEffectContext,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.state import BattlePhase, BattleState
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
    WeightedTransition,
    merge_equivalent_transitions,
    validate_transition_distribution,
)
from pokeop.domain.battle.turn_phases import (
    DEFAULT_TURN_PHASE_POLICY,
    STABLE_TURN_PHASES,
    TurnPhase,
    TurnPhasePolicy,
)


class TurnResolutionError(ValueError):
    """完整回合无法按稳定合同推进时的基础异常。"""


class InvalidAccuracyDistributionError(TurnResolutionError):
    """表示命中判定没有返回完整、精确且非空的概率分布。"""


@dataclass(frozen=True, slots=True)
class AccuracyCheckOutcome:
    """表示一次命中判定中的单条精确带权结果。

    Args:
        hit: True 表示继续进入伤害阶段，False 表示本次行动未命中。
        transition: #23 ``WeightedTransition``，概率只描述本次命中随机事件；其状态
            是命中判定完成后的不可变 ``BattleState``。
    """

    hit: bool
    transition: WeightedTransition[BattleState]

    def __post_init__(self) -> None:
        """校验命中标记和后继状态转移使用显式领域类型。

        Raises:
            InvalidAccuracyDistributionError: 字段不是稳定类型时抛出。
        """
        if not isinstance(self.hit, bool):
            raise InvalidAccuracyDistributionError("hit must be a bool")
        if not isinstance(self.transition, WeightedTransition):
            raise InvalidAccuracyDistributionError(
                "transition must be a WeightedTransition"
            )


@runtime_checkable
class AccuracyCheckPolicy(Protocol):
    """负责把一次已允许执行的行动转换为命中或未命中的概率分支。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[AccuracyCheckOutcome, ...]:
        """返回本次命中事件的完整概率分布。

        Args:
            context: 当前不可变战斗状态、行动方和已通过执行前校验的行动。

        Returns:
            非空命中结果元组；各 ``transition.probability`` 之和必须严格等于 1。
        """


@dataclass(frozen=True, slots=True)
class AlwaysHitAccuracyCheckPolicy:
    """提供确定命中的默认策略，等待 version-aware 命中率数据接入。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[AccuracyCheckOutcome, ...]:
        """返回概率为 1 的命中分支，且不修改输入状态。

        Args:
            context: 当前行动的不可变招式执行上下文。

        Returns:
            只包含一个确定命中结果的元组。
        """
        return (
            AccuracyCheckOutcome(
                hit=True,
                transition=_deterministic_transition(context.state),
            ),
        )


@runtime_checkable
class DamageResolutionPolicy(Protocol):
    """负责把已命中的行动转换为精确带权伤害后继状态。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> TransitionSet:
        """返回本次伤害随机事件的完整状态分布。

        Args:
            context: 当前不可变战斗状态、行动方和已命中的类型化行动。

        Returns:
            概率严格归一化的 ``WeightedTransition[BattleState]`` 元组。实现可以调用
            现有伤害计算器及 #26 ``ModifyDamageEffect``，但不得原地修改输入状态。
        """


@dataclass(frozen=True, slots=True)
class NoOpDamageResolutionPolicy:
    """提供不改变 HP 的默认伤害骨架，供管线测试和后续适配器替换。"""

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> TransitionSet:
        """返回概率为 1 的原状态。

        Args:
            context: 已命中行动的不可变执行上下文。

        Returns:
            不改变 HP 的确定性转移；具体伤害策略可通过依赖注入替换本实现。
        """
        return (_deterministic_transition(context.state),)


@runtime_checkable
class ActionOrderPolicy(Protocol):
    """负责为单个行动构造尚未应用机制 effect 的基础排序键。"""

    def base_order(self, state: BattleState, action: BattleAction) -> ActionOrder:
        """返回优先级、有效速度和基础同速键。

        Args:
            state: 当前正式 ``BattleState`` 节点。
            action: 需要计算基础顺序的类型化行动。

        Returns:
            供 #26 ``ModifyActionOrderEffect`` 继续调整的 ``ActionOrder``。
        """


@dataclass(frozen=True, slots=True)
class PrioritySpeedActionOrderPolicy:
    """按行动优先级和 ``PokemonSpec`` 最终速度构造首版基础顺序。"""

    def base_order(self, state: BattleState, action: BattleAction) -> ActionOrder:
        """读取行动优先级和行动方最终速度。

        Args:
            state: 当前不可变战斗状态。
            action: 需要排序的类型化行动；内部 Pass 会使用极低优先级。

        Returns:
            未应用特性、道具、状态或场地修正的基础排序键。
        """
        return ActionOrder(
            priority=_action_priority(action),
            speed=state.battler(action.side).spec.stats.speed,
        )


@dataclass(frozen=True, slots=True)
class TurnResolution:
    """表示完整回合产生的精确带权后继状态集合。

    Args:
        transitions: #23 定义的完整战斗随机分布，已经按 ``StateKey`` 合并等价状态。
        phase_order: resolver 使用的稳定阶段模板；首版固定为十一阶段顺序。
    """

    transitions: TransitionSet
    phase_order: tuple[TurnPhase, ...] = STABLE_TURN_PHASES

    def __post_init__(self) -> None:
        """冻结并校验转移概率与阶段顺序。

        Raises:
            TurnResolutionError: 阶段顺序不是首版稳定模板时抛出。
            EmptyTransitionSetError: 没有任何后继状态时由 #23 校验抛出。
            UnnormalizedTransitionSetError: 概率总和不严格等于 1 时由 #23 校验抛出。
        """
        object.__setattr__(
            self,
            "transitions",
            validate_transition_distribution(self.transitions),
        )
        if self.phase_order != STABLE_TURN_PHASES:
            raise TurnResolutionError("turn resolution must expose the stable phase order")


@dataclass(frozen=True, slots=True)
class _Branch:
    """保存 resolver 内尚未完成回合的带权状态。

    Attributes:
        probability: 从回合根节点到当前状态的精确战斗随机概率。
        state: 当前不可变战斗状态。
        event_summary: 到达当前状态的轻量随机事件路径。
        source_key: 可选的顶层解释来源键；不同来源归并时由 #23 清除歧义。
    """

    probability: Fraction
    state: BattleState
    event_summary: TransitionEventSummary = TransitionEventSummary.empty()
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class _OrderedBranch:
    """保存一条状态分支及该分支确定的双方行动执行顺序。

    Attributes:
        probability: 包含选招 effect 与同速事件后的累计概率。
        state: 排序完成时的不可变状态。
        actions: 严格包含双方原始行动的一种执行顺序。
        event_summary: 到达该顺序分支的随机事件路径。
        source_key: 可选的解释来源键。
    """

    probability: Fraction
    state: BattleState
    actions: tuple[BattleAction, BattleAction]
    event_summary: TransitionEventSummary
    source_key: str | None


@dataclass(frozen=True, slots=True)
class TurnResolver:
    """以稳定模板管线把双方合法行动推进为完整回合后继状态。

    resolver 位于纯 domain 层，只理解类型化行动、正式 ``BattleState``、#23 概率转移
    和 #26 effect dispatcher。它不判断任何 Pokémon、招式、特性或道具 identifier；
    具体命中、伤害与机制效果分别通过窄策略或 dispatcher 注入。

    Args:
        legal_action_generator: 只负责从当前状态生成一侧合法行动的策略。
        action_order_policy: 计算未应用 effect 的基础行动排序键。
        effects: #26 类型化 effect dispatcher；默认不包含任何机制产品。
        accuracy_policy: 产生命中/未命中局部分布的策略。
        damage_policy: 产生伤害后继状态局部分布的策略。
        phase_policy: 稳定阶段模板，插件不能通过该入口任意重排首版管线。
    """

    legal_action_generator: LegalActionGenerator = StandardLegalActionGenerator()
    action_order_policy: ActionOrderPolicy = PrioritySpeedActionOrderPolicy()
    effects: BattleEffectDispatcher[BattleAction] = field(
        default_factory=lambda: BattleEffectDispatcher.from_effects(())
    )
    accuracy_policy: AccuracyCheckPolicy = AlwaysHitAccuracyCheckPolicy()
    damage_policy: DamageResolutionPolicy = NoOpDamageResolutionPolicy()
    phase_policy: TurnPhasePolicy = DEFAULT_TURN_PHASE_POLICY

    def resolve(
        self,
        state: BattleState,
        attacker_action: BattleAction,
        defender_action: BattleAction,
    ) -> TurnResolution:
        """从行动选择节点推进一个完整 1v1 回合。

        Args:
            state: #21 正式不可变状态，必须处于 ``BattlePhase.ACTION_SELECTION``。
            attacker_action: 攻击方从当前合法行动集合选择的行动。
            defender_action: 防守方从当前合法行动集合选择的行动。

        Returns:
            完整、精确归一化且按状态键归并的回合后继转移集合。非终局进入下一回合
            ``ACTION_SELECTION``，任一方濒死时进入 ``TERMINAL``。

        Raises:
            TurnResolutionError: 输入状态阶段不允许开始完整回合时抛出。
            InvalidBattleAction: 行动侧错误、行动不合法或执行期 PP 不变量被破坏时抛出。
        """
        if state.phase is not BattlePhase.ACTION_SELECTION:
            raise TurnResolutionError(
                "turn resolution must start from BattlePhase.ACTION_SELECTION"
            )

        supplied_actions = (attacker_action, defender_action)
        self._validate_action_sides(supplied_actions)
        self._validate_legal_actions(state, supplied_actions)

        branches = (_Branch(probability=Fraction(1, 1), state=state),)
        branches = self._run_action_selection(branches, supplied_actions)
        ordered = self._run_action_order(branches, supplied_actions)

        completed: list[_Branch] = []
        for ordered_branch in ordered:
            action_branches = (
                _Branch(
                    probability=ordered_branch.probability,
                    state=ordered_branch.state,
                    event_summary=ordered_branch.event_summary,
                    source_key=ordered_branch.source_key,
                ),
            )
            for action in ordered_branch.actions:
                action_branches = self._execute_action(action_branches, action)
            completed.extend(action_branches)

        turn_end = self._run_turn_end(tuple(completed))
        finished = tuple(
            _Branch(
                probability=branch.probability,
                state=self._finish_turn_state(branch.state),
                event_summary=branch.event_summary,
                source_key=branch.source_key,
            )
            for branch in turn_end
        )
        transitions = merge_equivalent_transitions(_branches_to_transitions(finished))
        return TurnResolution(
            transitions=transitions,
            phase_order=self.phase_policy.phases,
        )

    def _validate_action_sides(
        self,
        actions: tuple[BattleAction, BattleAction],
    ) -> None:
        """确认 resolve 参数严格按攻击方、防守方顺序传入。

        Args:
            actions: 调用方提供的攻击方行动和防守方行动。

        Raises:
            InvalidBattleAction: 行动侧顺序不匹配稳定双方枚举时抛出。
        """
        expected = (BattleSide.ATTACKER, BattleSide.DEFENDER)
        actual = tuple(action.side for action in actions)
        if actual != expected:
            raise InvalidBattleAction(
                "resolve requires attacker_action followed by defender_action"
            )

    def _validate_legal_actions(
        self,
        state: BattleState,
        actions: tuple[BattleAction, BattleAction],
    ) -> None:
        """确认双方策略只选择生成器给出的合法行动。

        Args:
            state: 行动选择发生时的不可变状态。
            actions: 双方已经选择的类型化行动。

        Raises:
            InvalidBattleAction: 任一行动不属于对应侧当前合法集合时抛出。
        """
        for side, action in zip(
            (BattleSide.ATTACKER, BattleSide.DEFENDER),
            actions,
            strict=True,
        ):
            legal_actions = self.legal_action_generator.generate(state, side)
            if action not in legal_actions:
                raise InvalidBattleAction(
                    f"{action!r} is not legal for side {side.value}"
                )

    def _run_action_selection(
        self,
        branches: tuple[_Branch, ...],
        actions: tuple[BattleAction, BattleAction],
    ) -> tuple[_Branch, ...]:
        """按双方选择顺序调用 #26 选招后 effect。

        Args:
            branches: 进入行动选择阶段的全局概率分支。
            actions: 双方在根节点已经选择的合法行动。

        Returns:
            应用选招后 effect 并进入 ``ACTION_RESOLUTION`` 粗阶段的分支。
        """
        current = branches
        for action in actions:
            if isinstance(action, PassAction):
                # 已濒死一侧的内部占位行动不应触发锁招或其他选招后机制。
                continue
            current = self._expand_transition_stage(
                current,
                lambda state, selected=action: self.effects.after_move_selected(
                    ActionEffectContext(
                        state=state,
                        actor=selected.side,
                        action=selected,
                    ),
                    (_deterministic_transition(state),),
                ),
            )
        return tuple(
            _Branch(
                probability=branch.probability,
                state=branch.state.with_phase(BattlePhase.ACTION_RESOLUTION),
                event_summary=branch.event_summary,
                source_key=branch.source_key,
            )
            for branch in current
        )

    def _run_action_order(
        self,
        branches: tuple[_Branch, ...],
        actions: tuple[BattleAction, BattleAction],
    ) -> tuple[_OrderedBranch, ...]:
        """为每条状态分支计算 effect 调整后的行动顺序和同速概率。

        Args:
            branches: 完成选招后 effect 的状态分支。
            actions: 双方原始行动；排序只能改变顺序，不能替换行动。

        Returns:
            已确定行动顺序的分支。同优先级、同速度、同 tie_break 时产生双方各
            ``1/2`` 先手的 #23 精确转移语义。
        """
        ordered: list[_OrderedBranch] = []
        for branch in branches:
            left, right = actions
            left_order = self.effects.modify_action_order(
                ActionOrderEffectContext(
                    state=branch.state,
                    actor=left.side,
                    action=left,
                ),
                self.action_order_policy.base_order(branch.state, left),
            )
            right_order = self.effects.modify_action_order(
                ActionOrderEffectContext(
                    state=branch.state,
                    actor=right.side,
                    action=right,
                ),
                self.action_order_policy.base_order(branch.state, right),
            )
            comparison = _compare_action_orders(left_order, right_order)
            if comparison != 0:
                action_order = (left, right) if comparison > 0 else (right, left)
                ordered.append(
                    _OrderedBranch(
                        probability=branch.probability,
                        state=branch.state,
                        actions=action_order,
                        event_summary=branch.event_summary,
                        source_key=branch.source_key,
                    )
                )
                continue

            # 同优先级、同速度且 effect 未提供 tie_break 时，保留双方各 1/2 先手分支。
            for first, second in ((left, right), (right, left)):
                event = TransitionEvent(
                    event_type=TransitionEventType.SPEED_TIE,
                    event_id=f"turn-{branch.state.turn_number}-action-order",
                    outcome_id=f"{first.side.value}-first",
                )
                ordered.append(
                    _OrderedBranch(
                        probability=branch.probability * Fraction(1, 2),
                        state=branch.state,
                        actions=(first, second),
                        event_summary=branch.event_summary.concatenate(
                            TransitionEventSummary.single(event)
                        ),
                        source_key="turn.speed-tie",
                    )
                )
        return tuple(ordered)

    def _execute_action(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[_Branch, ...]:
        """在每条概率分支中执行一方行动，并在濒死、Pass 或 effect 阻断时短路。

        Args:
            branches: 当前行动开始前的全局概率分支。
            action: 本轮行动顺序中的当前行动。

        Returns:
            当前行动完成后的分支。未命中仍保留 PP 消耗；执行前被阻断时不消耗 PP；
            先手已造成任一方濒死时后手不会进入执行阶段。
        """
        completed: list[_Branch] = []
        for branch in branches:
            actor = branch.state.battler(action.side)
            target = branch.state.opponent(action.side)
            if (
                actor.current_hp == 0
                or target.current_hp == 0
                or isinstance(action, PassAction)
            ):
                # 先手已经造成濒死时直接保留状态，后手不会进入 PP 消耗和效果阶段。
                completed.append(branch)
                continue

            validation = self.effects.validate_action(
                ActionEffectContext(
                    state=branch.state,
                    actor=action.side,
                    action=action,
                )
            )
            if not validation.allowed:
                # 畏缩等执行前阻断不消耗 PP；裁决理由由 effect report 保留给解释层。
                completed.append(branch)
                continue

            before_move = self._expand_transition_stage(
                (branch,),
                lambda state: self.effects.before_move(
                    MoveEffectContext(
                        state=state,
                        actor=action.side,
                        action=action,
                    ),
                    (_deterministic_transition(state),),
                ),
            )
            consumed: list[_Branch] = []
            for item in before_move:
                if (
                    item.state.battler(action.side).current_hp == 0
                    or item.state.opponent(action.side).current_hp == 0
                ):
                    completed.append(item)
                    continue
                consumed.append(
                    _Branch(
                        probability=item.probability,
                        state=self._consume_action(item.state, action),
                        event_summary=item.event_summary,
                        source_key=item.source_key,
                    )
                )
            if not consumed:
                continue

            missed, hit = self._run_accuracy_check(tuple(consumed), action)
            damaged = self._run_damage(hit, action) if hit else ()
            after_damage = (
                self._expand_transition_stage(
                    damaged,
                    lambda state: self.effects.after_damage(
                        MoveEffectContext(
                            state=state,
                            actor=action.side,
                            action=action,
                        ),
                        (_deterministic_transition(state),),
                    ),
                )
                if damaged
                else ()
            )
            # AFTER_MOVE 与 FAINT_CHECK 当前没有额外 dispatcher 协议；阶段顺序仍由模板锁定。
            completed.extend((*missed, *after_damage))
        return tuple(completed)

    def _run_accuracy_check(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[tuple[_Branch, ...], tuple[_Branch, ...]]:
        """展开每条父分支的命中分布，并在伤害前分离命中与未命中路径。

        Args:
            branches: 已完成 PP 消耗的父分支。
            action: 当前正在执行的行动。

        Returns:
            二元组 ``(missed, hit)``；两组联合后的概率等于输入分支概率。

        Raises:
            InvalidAccuracyDistributionError: 任一父状态的局部命中分布非法时抛出。
        """
        missed: list[_Branch] = []
        hit: list[_Branch] = []
        for branch in branches:
            outcomes = self.accuracy_policy.resolve(
                MoveEffectContext(
                    state=branch.state,
                    actor=action.side,
                    action=action,
                )
            )
            _validate_accuracy_outcomes(outcomes)
            for outcome in outcomes:
                child = outcome.transition
                expanded = _Branch(
                    probability=branch.probability * child.probability,
                    state=child.state,
                    event_summary=branch.event_summary.concatenate(
                        child.event_summary
                    ),
                    source_key=child.source_key or branch.source_key,
                )
                (hit if outcome.hit else missed).append(expanded)
        return tuple(missed), tuple(hit)

    def _run_damage(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[_Branch, ...]:
        """调用注入的伤害策略，并把局部概率与父路径概率精确相乘。

        Args:
            branches: 命中判定成功的父分支。
            action: 当前已命中的行动。

        Returns:
            应用伤害策略后的全局概率分支。
        """
        return self._expand_transition_stage(
            branches,
            lambda state: self.damage_policy.resolve(
                MoveEffectContext(
                    state=state,
                    actor=action.side,
                    action=action,
                )
            ),
        )

    def _run_turn_end(self, branches: tuple[_Branch, ...]) -> tuple[_Branch, ...]:
        """进入回合结束粗阶段，并按每条状态调用 #26 TurnEndEffect。

        Args:
            branches: 双方行动均已完成或因濒死而短路的分支。

        Returns:
            处于 ``BattlePhase.END_OF_TURN`` 且已应用回合末 effect 的分支。
        """
        entered = tuple(
            _Branch(
                probability=branch.probability,
                state=branch.state.with_phase(BattlePhase.END_OF_TURN),
                event_summary=branch.event_summary,
                source_key=branch.source_key,
            )
            for branch in branches
        )
        return self._expand_transition_stage(
            entered,
            lambda state: self.effects.on_turn_end(
                TurnEndEffectContext(state=state),
                (_deterministic_transition(state),),
            ),
        )

    def _expand_transition_stage(
        self,
        branches: tuple[_Branch, ...],
        stage: Callable[[BattleState], TransitionSet],
    ) -> tuple[_Branch, ...]:
        """逐父状态展开一个要求局部分布归一化的状态转换阶段。

        Args:
            branches: 当前全局概率分支；单个分支概率可以小于 1，例如同速父分支。
            stage: 接收一个 ``BattleState`` 并返回局部概率和严格为 1 的转移集合。

        Returns:
            父概率与局部概率相乘、事件路径按执行顺序连接后的全局分支。

        Raises:
            EmptyTransitionSetError: 阶段没有为某个父状态返回后继分支时由 #23 抛出。
            UnnormalizedTransitionSetError: 局部概率和不为 1 时由 #23 抛出。
        """
        expanded: list[_Branch] = []
        for parent in branches:
            children = validate_transition_distribution(stage(parent.state))
            for child in children:
                expanded.append(
                    _Branch(
                        probability=parent.probability * child.probability,
                        state=child.state,
                        event_summary=parent.event_summary.concatenate(
                            child.event_summary
                        ),
                        source_key=child.source_key or parent.source_key,
                    )
                )
        return tuple(expanded)

    @staticmethod
    def _consume_action(state: BattleState, action: BattleAction) -> BattleState:
        """扣除普通招式一点 PP 并记录上一招；挣扎不修改普通招式槽。

        Args:
            state: 扣除 PP 前的不可变状态。
            action: 已通过合法行动和执行前 effect 校验的行动。

        Returns:
            更新行动方招式槽和 ``last_move_id`` 后的新状态。

        Raises:
            InvalidBattleAction: Pass 进入执行，或普通招式槽已无 PP/被禁用时抛出。
        """
        if isinstance(action, UseMoveAction):
            battler = state.battler(action.side)
            slot = battler.move_slot(action.move_id)
            if slot.current_pp <= 0 or slot.is_disabled:
                raise InvalidBattleAction(
                    "selected move became unusable before pp consumption"
                )
            if (
                battler.choice_lock_move_id is not None
                and battler.choice_lock_move_id != action.move_id
            ):
                raise InvalidBattleAction(
                    "selected move violates the current choice lock"
                )
            updated_battler = battler.with_move_slot(
                slot.with_current_pp(slot.current_pp - 1)
            ).with_last_move(action.move_id)
            return state.with_battler(action.side, updated_battler)
        if isinstance(action, StruggleAction):
            return state
        raise InvalidBattleAction("PassAction cannot enter move execution")

    @staticmethod
    def _finish_turn_state(state: BattleState) -> BattleState:
        """清理回合级状态，并进入下一回合或终局。

        Args:
            state: 已完成所有行动和回合结束 effect 的 ``END_OF_TURN`` 状态。

        Returns:
            清除双方畏缩并完成首次出场标记后的新节点。任一方 HP 为 0 时进入
            ``TERMINAL`` 且保留当前回合号；否则回合号加一并进入行动选择阶段。
        """
        current = state
        for side in (BattleSide.ATTACKER, BattleSide.DEFENDER):
            battler = current.battler(side)
            status = battler.status.clear_volatile_status(VolatileStatusKind.FLINCH)
            updated = battler.with_status(status).mark_first_turn_complete()
            current = current.with_battler(side, updated)

        if current.attacker.current_hp == 0 or current.defender.current_hp == 0:
            return current.with_phase(BattlePhase.TERMINAL)
        return current.next_turn()


def _deterministic_transition(state: BattleState) -> WeightedTransition[BattleState]:
    """把一个确定状态包装为概率 1、无随机事件的 #23 转移。

    Args:
        state: 需要进入类型化转移管线的不可变状态。

    Returns:
        概率为 1、事件摘要为空的 ``WeightedTransition``。
    """
    return WeightedTransition(probability=Fraction(1, 1), state=state)


def _action_priority(action: BattleAction) -> int:
    """返回类型化行动的基础优先级。

    Args:
        action: 待排序的类型化行动。

    Returns:
        普通招式携带的优先级；挣扎为 0；内部 Pass 使用极低值保证最后处理。
    """
    if isinstance(action, UseMoveAction):
        return action.priority
    if isinstance(action, StruggleAction):
        return 0
    return -10_000


def _compare_action_orders(left: ActionOrder, right: ActionOrder) -> int:
    """按优先级、速度、tie_break 顺序比较两个显式排序键。

    Args:
        left: 第一个行动经全部排序 effect 处理后的键。
        right: 第二个行动经全部排序 effect 处理后的键。

    Returns:
        left 更早时返回 1，right 更早时返回 -1，完全相同时返回 0。
    """
    left_key = (left.priority, left.speed, left.tie_break)
    right_key = (right.priority, right.speed, right.tie_break)
    return (left_key > right_key) - (left_key < right_key)


def _validate_accuracy_outcomes(
    outcomes: tuple[AccuracyCheckOutcome, ...],
) -> None:
    """校验命中策略返回非空且概率严格归一化的完整分布。

    Args:
        outcomes: 单个父状态对应的全部命中与未命中结果。

    Raises:
        InvalidAccuracyDistributionError: 集合为空、元素类型错误或概率未归一化时抛出。
    """
    if not outcomes:
        raise InvalidAccuracyDistributionError(
            "accuracy policy must return at least one outcome"
        )
    if any(not isinstance(outcome, AccuracyCheckOutcome) for outcome in outcomes):
        raise InvalidAccuracyDistributionError(
            "accuracy policy must return AccuracyCheckOutcome values"
        )
    try:
        validate_transition_distribution(
            tuple(outcome.transition for outcome in outcomes)
        )
    except ValueError as exc:
        raise InvalidAccuracyDistributionError(
            "accuracy outcomes must form a normalized transition distribution"
        ) from exc


def _branches_to_transitions(branches: tuple[_Branch, ...]) -> TransitionSet:
    """把 resolver 内部分支转换为可交付给状态图的 #23 转移集合。

    Args:
        branches: 完整回合结束后的内部概率分支。

    Returns:
        保留概率、状态、事件摘要和来源键的不可变转移元组。
    """
    return tuple(
        WeightedTransition(
            probability=branch.probability,
            state=branch.state,
            event_summary=branch.event_summary,
            source_key=branch.source_key,
        )
        for branch in branches
    )


__all__ = [
    "AccuracyCheckOutcome",
    "AccuracyCheckPolicy",
    "ActionOrderPolicy",
    "AlwaysHitAccuracyCheckPolicy",
    "DamageResolutionPolicy",
    "InvalidAccuracyDistributionError",
    "NoOpDamageResolutionPolicy",
    "PrioritySpeedActionOrderPolicy",
    "TurnResolution",
    "TurnResolutionError",
    "TurnResolver",
]
