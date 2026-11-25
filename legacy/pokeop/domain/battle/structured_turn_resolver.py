from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Generic, TypeVar, cast

from pokeop.domain.battle.actions import (
    BattleAction,
    LegalActionGenerator,
    PassAction,
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.battle_events import (
    BattleEvent,
    BattleEventKind,
    append_battle_events,
    battle_event_paths,
    event_summary,
    prepend_battle_events,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.effects.dispatcher import BattleEffectDispatcher
from pokeop.domain.battle.effects.protocols import (
    ActionEffectContext,
    BattleEffect,
    DamageEffectApplication,
    DamageEffectContext,
    DamageEffectStage,
    MoveEffectContext,
    TransitionSet,
    VolatileStatusEffectContext,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.move_execution import (
    EffectiveSpeedActionOrderPolicy,
    FlinchActionGateEffect,
    MoveAccuracyCheckPolicy,
    StandardMoveDamagePolicy,
)
from pokeop.domain.battle.state import BattlePhase, BattleState
from pokeop.domain.battle.transitions import (
    TransitionEventSummary,
    WeightedTransition,
    merge_equivalent_transitions,
    validate_transition_distribution,
)
from pokeop.domain.battle.turn_resolver import (
    TurnResolution,
    TurnResolutionError,
    TurnResolver,
    _Branch,
    _OrderedBranch,
    _branches_to_transitions,
    _deterministic_transition,
    _validate_accuracy_outcomes,
)


ActionT = TypeVar("ActionT")


def _opponent_side(side: BattleSide) -> BattleSide:
    """返回 1v1 战斗中指定行动侧的对手侧。

    Args:
        side: 当前行动、状态来源或机制持有者所属的稳定战斗侧。

    Returns:
        与输入相反的另一稳定战斗侧。
    """
    return (
        BattleSide.DEFENDER
        if side is BattleSide.ATTACKER
        else BattleSide.ATTACKER
    )


def _move_id(action: BattleAction) -> int | None:
    """读取行动关联的普通招式 ID。

    Args:
        action: 普通招式、挣扎或内部 Pass 行动。

    Returns:
        ``UseMoveAction.move_id``；挣扎和 Pass 不引用普通招式槽，因此返回 None。
    """
    return action.move_id if isinstance(action, UseMoveAction) else None


def _action_source_identifier(action: BattleAction) -> str:
    """返回不依赖具体招式名称的稳定行动来源标识。

    Args:
        action: 当前类型化行动。

    Returns:
        普通招式返回 ``move``，挣扎返回 ``struggle``，内部占位返回 ``pass``。
    """
    if isinstance(action, UseMoveAction):
        return "move"
    if isinstance(action, StruggleAction):
        return "struggle"
    return "pass"


def _modifier_identifier(application: DamageEffectApplication) -> str:
    """把伤害 effect key 规范化为可持久投影的字符串标识。

    Args:
        application: dispatcher 返回的一次实际伤害倍率应用。

    Returns:
        枚举 key 的 value 或自定义字符串 key 本身。
    """
    key = application.key
    return str(key.value) if isinstance(key, Enum) else str(key)


def _branch_with_events(
    branch: _Branch,
    events: Iterable[BattleEvent],
) -> _Branch:
    """为 resolver 内部分支追加确定性业务事件。

    Args:
        branch: 当前概率、状态、随机路径与来源键组成的内部不可变分支。
        events: 当前阶段按发生顺序产生的结构化事件。

    Returns:
        状态和概率不变、事件路径已追加的新分支。
    """
    return _Branch(
        probability=branch.probability,
        state=branch.state,
        event_summary=append_battle_events(branch.event_summary, events),
        source_key=branch.source_key,
    )


def _hp_change_events(
    *,
    before: BattleState,
    after: BattleState,
    action: BattleAction,
) -> tuple[BattleEvent, ...]:
    """根据一个明确执行阶段的前后状态生成 HP、伤害和濒死事件。

    该辅助函数只在 resolver 已知当前行动和阶段边界时使用，不供 application 通过任意
    图节点差异猜测战报。目标直接伤害先记录，随后才记录挣扎反伤等行动方变化。

    Args:
        before: 当前伤害或伤害后 effect 执行前的正式战斗状态。
        after: 同一阶段完成后的正式战斗状态。
        action: 造成该阶段变化的类型化行动。

    Returns:
        按目标侧、行动侧顺序排列的 DAMAGE、HP_CHANGED 与 FAINTED 事件；没有 HP
        变化时返回空元组。
    """
    actor_side = action.side
    target_side = _opponent_side(actor_side)
    events: list[BattleEvent] = []
    for affected_side in (target_side, actor_side):
        before_hp = before.battler(affected_side).current_hp
        after_hp = after.battler(affected_side).current_hp
        if before_hp == after_hp:
            continue

        source_identifier = _action_source_identifier(action)
        if affected_side is actor_side and isinstance(action, StruggleAction):
            source_identifier = "struggle-recoil"
        if after_hp < before_hp:
            events.append(
                BattleEvent(
                    kind=BattleEventKind.DAMAGE,
                    turn_number=before.turn_number,
                    actor=actor_side,
                    target=affected_side,
                    move_id=_move_id(action),
                    source_identifier=source_identifier,
                    value=before_hp - after_hp,
                )
            )
        events.append(
            BattleEvent(
                kind=BattleEventKind.HP_CHANGED,
                turn_number=before.turn_number,
                actor=actor_side,
                target=affected_side,
                move_id=_move_id(action),
                source_identifier=source_identifier,
                before_value=before_hp,
                after_value=after_hp,
            )
        )
        if before_hp > 0 and after_hp == 0:
            events.append(
                BattleEvent(
                    kind=BattleEventKind.FAINTED,
                    turn_number=before.turn_number,
                    actor=affected_side,
                    source_identifier=source_identifier,
                )
            )
    return tuple(events)


def _summary_has_hp_change(summary: TransitionEventSummary) -> bool:
    """判断局部转移摘要是否已经显式记录 HP 变化。

    Args:
        summary: 单个策略或 effect 返回的局部事件摘要，不包含 resolver 父路径。

    Returns:
        任一替代路径包含 ``HP_CHANGED`` 时返回 True。
    """
    return any(
        event.kind is BattleEventKind.HP_CHANGED
        for path in battle_event_paths(summary)
        for event in path
    )


class BattleEventEffectDispatcher(BattleEffectDispatcher[ActionT], Generic[ActionT]):
    """在现有类型化 effect 分发之上记录状态施加与阻止事件。

    dispatcher 仍按原窄 Protocol 分发，不识别击掌奇袭、精神力等具体类名。结构化事件
    直接来自 ``VolatileStatusAttempt`` 与 ``StatusPreventionReport`` 的稳定标识，因此
    新增同类招式或免疫特性时不需要修改本类分支。
    """

    @classmethod
    def from_effects(
        cls,
        effects: Iterable[BattleEffect],
    ) -> "BattleEventEffectDispatcher[ActionT]":
        """根据 effect 实际实现的协议构建可记录事件的 dispatcher。

        Args:
            effects: 同一规则集下的 move、ability 和 item effect 序列。

        Returns:
            保留基础 dispatcher 全部协议索引，并覆盖状态请求结算阶段的新实例。
        """
        base = BattleEffectDispatcher.from_effects(effects)
        return cls(
            coverage=base.coverage,
            _validate_action_effects=base._validate_action_effects,
            _modify_action_order_effects=base._modify_action_order_effects,
            _before_move_effects=base._before_move_effects,
            _modify_damage_effects=base._modify_damage_effects,
            _prevent_volatile_status_effects=base._prevent_volatile_status_effects,
            _after_move_selected_effects=base._after_move_selected_effects,
            _after_damage_effects=base._after_damage_effects,
            _after_damage_volatile_status_effects=(
                base._after_damage_volatile_status_effects
            ),
            _turn_end_effects=base._turn_end_effects,
        )

    def after_damage(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """执行伤害后状态转换，并为临时状态裁决追加结构化事件。

        Args:
            context: 当前行动方、类型化行动和进入伤害后阶段的状态。
            transitions: 已完成直接伤害的局部归一化转移集合。

        Returns:
            保留原概率和随机路径，同时追加状态施加、状态阻止和免疫特性触发事实的
            归一化转移集合。
        """
        current = self._validated_transitions(transitions)
        for effect in self._after_damage_effects:
            current = self._validated_transitions(effect.after_damage(context, current))
        return self._apply_structured_status_attempts(context, current)

    def _apply_structured_status_attempts(
        self,
        context: MoveEffectContext[ActionT],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """结算临时状态请求并同步产生成功或阻止事件。

        Args:
            context: 当前行动方和行动；每条分支会使用自己的状态重建上下文。
            transitions: 已完成普通伤害后 effect 的局部归一化转移。

        Returns:
            状态与事件摘要同步更新后的归一化集合。已濒死目标不写入临时状态，也不产生
            一个后续无法消费的状态事件。

        Raises:
            ValueError: effect 发出的状态来源与当前行动方不一致时抛出。
        """
        if not self._after_damage_volatile_status_effects:
            return self._validated_transitions(transitions)

        updated: list[WeightedTransition[BattleState]] = []
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
            events: list[BattleEvent] = []
            for attempt in attempts:
                self._validate_status_attempt_source(context, attempt)
                if state.battler(attempt.target).current_hp == 0:
                    continue
                prevention = self.prevent_volatile_status(
                    VolatileStatusEffectContext(
                        state=state,
                        source=attempt.source,
                        target=attempt.target,
                        status_identifier=attempt.status.kind.value,
                    )
                )
                blocking_decisions = tuple(
                    decision
                    for decision in prevention.decisions
                    if decision.prevented
                )
                if blocking_decisions:
                    for decision in blocking_decisions:
                        events.append(
                            BattleEvent(
                                kind=BattleEventKind.ABILITY_TRIGGERED,
                                turn_number=state.turn_number,
                                actor=attempt.target,
                                target=attempt.source,
                                move_id=_move_id(cast(BattleAction, context.action)),
                                source_identifier=decision.source_identifier,
                            )
                        )
                        events.append(
                            BattleEvent(
                                kind=BattleEventKind.STATUS_PREVENTED,
                                turn_number=state.turn_number,
                                actor=attempt.source,
                                target=attempt.target,
                                move_id=_move_id(cast(BattleAction, context.action)),
                                source_identifier=decision.source_identifier,
                            )
                        )
                    continue

                target = state.battler(attempt.target)
                state = state.with_battler(
                    attempt.target,
                    target.with_status(target.status.add_volatile(attempt.status)),
                )
                events.append(
                    BattleEvent(
                        kind=BattleEventKind.STATUS_APPLIED,
                        turn_number=state.turn_number,
                        actor=attempt.source,
                        target=attempt.target,
                        move_id=_move_id(cast(BattleAction, context.action)),
                        source_identifier=attempt.source_identifier,
                    )
                )
            updated.append(
                WeightedTransition(
                    probability=transition.probability,
                    state=state,
                    event_summary=append_battle_events(
                        transition.event_summary,
                        events,
                    ),
                    source_key=transition.source_key,
                )
            )
        return self._validated_transitions(tuple(updated))


class BattleEventDamagePolicy(StandardMoveDamagePolicy):
    """为标准伤害策略产生的每条伤害路径补充结构化事件。

    伤害公式、随机档位、动态倍率和 HP 更新仍完全复用 ``StandardMoveDamagePolicy``；
    本类只在同一 domain 阶段把已知输入、实际后继状态和动态 effect application 投影为
    ``BattleEvent``，不会复制第二套伤害公式。
    """

    def resolve(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[WeightedTransition[BattleState], ...]:
        """返回带伤害、HP、濒死和动态机制触发事件的标准伤害分布。

        Args:
            context: 已完成 PP 消耗和命中判定的行动上下文。

        Returns:
            复用原标准策略概率和状态，并在每条替代伤害路径中追加结构化事实的转移集合。
        """
        applications = self._active_dynamic_applications(context)
        transitions = super().resolve(context)
        return tuple(
            self._decorate_transition(context, transition, applications)
            for transition in transitions
        )

    def _active_dynamic_applications(
        self,
        context: MoveEffectContext[BattleAction],
    ) -> tuple[DamageEffectApplication, ...]:
        """读取本次标准招式实际新增的动态最终伤害修正。

        Args:
            context: 当前行动、PP 已扣除后的状态和行动方。

        Returns:
            尚未由旧伤害 trace 应用、将在实时状态阶段生效的 ability/item application。
            变化招式、挣扎和 Pass 返回空元组。
        """
        action = context.action
        if not isinstance(action, UseMoveAction):
            return ()
        move_spec = context.state.battler(context.actor).spec.move_spec(action.move_id)
        if move_spec.move.category is MoveCategory.STATUS:
            return ()

        damage_context = self._damage_context(
            state=context.state,
            actor=context.actor,
            move_id=action.move_id,
        )
        damage_result = calculate_damage_rolls(damage_context)
        existing_keys = {
            modifier.key for modifier in damage_result.applied_modifiers
        }
        target = _opponent_side(context.actor)
        applications = self.effects.modify_damage(
            DamageEffectContext(
                damage_context=damage_context,
                stage=DamageEffectStage.FINAL_DAMAGE,
                type_effectiveness=self._type_effectiveness(damage_result),
                battle_state=context.state,
                actor=context.actor,
                target=target,
                is_direct_damage=True,
            )
        )
        return tuple(
            application
            for application in applications
            if application.key not in existing_keys
        )

    def _decorate_transition(
        self,
        context: MoveEffectContext[BattleAction],
        transition: WeightedTransition[BattleState],
        applications: tuple[DamageEffectApplication, ...],
    ) -> WeightedTransition[BattleState]:
        """为单个伤害后继状态的全部随机档路径补充业务事件。

        Args:
            context: 伤害发生前的行动上下文。
            transition: 原标准策略已经按状态归并的一条后继转移。
            applications: 本次实时阶段实际新增的动态倍率修正。

        Returns:
            概率、状态和来源键不变，且每条替代路径都保留触发、伤害、HP 与濒死顺序的
            新转移。
        """
        target_side = _opponent_side(context.actor)
        trigger_events: list[BattleEvent] = []
        for application in applications:
            identifier = _modifier_identifier(application)
            if identifier.startswith("ability:"):
                kind = BattleEventKind.ABILITY_TRIGGERED
            elif identifier.startswith("item:"):
                kind = BattleEventKind.ITEM_TRIGGERED
            else:
                continue
            # 当前动态最终伤害协议由目标侧实时状态 effect 使用；未来若引入攻击方动态
            # effect，应在 DamageEffectApplication 中显式增加来源侧，而不是按 identifier 猜测。
            trigger_events.append(
                BattleEvent(
                    kind=kind,
                    turn_number=context.state.turn_number,
                    actor=target_side,
                    target=context.actor,
                    move_id=_move_id(context.action),
                    source_identifier=identifier,
                )
            )

        hp_events = _hp_change_events(
            before=context.state,
            after=transition.state,
            action=context.action,
        )
        summary = prepend_battle_events(
            transition.event_summary,
            trigger_events,
        )
        summary = append_battle_events(summary, hp_events)
        return WeightedTransition(
            probability=transition.probability,
            state=transition.state,
            event_summary=summary,
            source_key=transition.source_key,
        )


class BattleEventTurnResolver(TurnResolver):
    """在稳定完整回合管线中同步产生结构化 ``BattleEvent``。

    resolver 仍通过注入的行动生成器、排序策略、effect dispatcher、命中策略和伤害策略
    推进状态；新增逻辑只记录阶段事实。它不包含具体 Pokémon、招式、特性或道具名称，
    也不生成面向用户的战报字符串。
    """

    def resolve(
        self,
        state: BattleState,
        attacker_action: BattleAction,
        defender_action: BattleAction,
    ) -> TurnResolution:
        """从行动选择节点推进一个带完整结构化事件路径的 1v1 回合。

        Args:
            state: 必须处于 ``ACTION_SELECTION`` 的正式不可变状态。
            attacker_action: 攻击方从当前合法行动集合选择的行动。
            defender_action: 防守方从当前合法行动集合选择的行动。

        Returns:
            按状态键归并的完整概率分布；到达同一状态的替代路径仍分别保留自己的
            ``BattleEvent`` 顺序。

        Raises:
            TurnResolutionError: 输入阶段不允许开始完整回合时抛出。
            InvalidBattleAction: 行动侧、合法性或 PP 不变量非法时由基础 resolver 抛出。
        """
        if state.phase is not BattlePhase.ACTION_SELECTION:
            raise TurnResolutionError(
                "turn resolution must start from BattlePhase.ACTION_SELECTION"
            )

        supplied_actions = (attacker_action, defender_action)
        self._validate_action_sides(supplied_actions)
        self._validate_legal_actions(state, supplied_actions)
        branches = (
            _Branch(
                probability=Fraction(1, 1),
                state=state,
                event_summary=event_summary(
                    (
                        BattleEvent(
                            kind=BattleEventKind.TURN_STARTED,
                            turn_number=state.turn_number,
                        ),
                    )
                ),
            ),
        )
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
        finished: list[_Branch] = []
        for branch in turn_end:
            finished_state = self._finish_turn_state(branch.state)
            finished.append(
                _Branch(
                    probability=branch.probability,
                    state=finished_state,
                    event_summary=append_battle_events(
                        branch.event_summary,
                        (
                            BattleEvent(
                                kind=BattleEventKind.TURN_ENDED,
                                turn_number=branch.state.turn_number,
                            ),
                        ),
                    ),
                    source_key=branch.source_key,
                )
            )
        transitions = merge_equivalent_transitions(
            _branches_to_transitions(tuple(finished))
        )
        return TurnResolution(
            transitions=transitions,
            phase_order=self.phase_policy.phases,
        )

    def _run_action_selection(
        self,
        branches: tuple[_Branch, ...],
        actions: tuple[BattleAction, BattleAction],
    ) -> tuple[_Branch, ...]:
        """记录双方行动选择后再执行选招后 effect。

        Args:
            branches: 进入行动选择阶段的全局概率分支。
            actions: 双方在根节点选择的合法行动。

        Returns:
            每条路径先含 ``MOVE_SELECTED``，再包含锁招等选招后 effect 结果，并进入
            ``ACTION_RESOLUTION`` 粗阶段的分支。
        """
        current = branches
        for action in actions:
            current = tuple(
                _branch_with_events(
                    branch,
                    (
                        BattleEvent(
                            kind=BattleEventKind.MOVE_SELECTED,
                            turn_number=branch.state.turn_number,
                            actor=action.side,
                            target=(
                                None
                                if isinstance(action, PassAction)
                                else _opponent_side(action.side)
                            ),
                            move_id=_move_id(action),
                            source_identifier=_action_source_identifier(action),
                        ),
                    ),
                )
                for branch in current
            )
            if isinstance(action, PassAction):
                continue
            current = self._expand_transition_stage(
                current,
                lambda current_state, selected=action: self.effects.after_move_selected(
                    ActionEffectContext(
                        state=current_state,
                        actor=selected.side,
                        action=selected,
                    ),
                    (_deterministic_transition(current_state),),
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
        """复用基础排序与同速概率，并显式记录每条路径的实际行动顺序。

        Args:
            branches: 完成选招后 effect 的状态分支。
            actions: 双方原始行动。

        Returns:
            每条排序分支追加两个从 1 开始的 ``ACTION_ORDERED`` 事件；同速随机事件仍
            由基础 resolver 保留。
        """
        ordered = super()._run_action_order(branches, actions)
        return tuple(
            _OrderedBranch(
                probability=branch.probability,
                state=branch.state,
                actions=branch.actions,
                event_summary=append_battle_events(
                    branch.event_summary,
                    tuple(
                        BattleEvent(
                            kind=BattleEventKind.ACTION_ORDERED,
                            turn_number=branch.state.turn_number,
                            actor=action.side,
                            target=(
                                None
                                if isinstance(action, PassAction)
                                else _opponent_side(action.side)
                            ),
                            move_id=_move_id(action),
                            source_identifier=_action_source_identifier(action),
                            value=index,
                        )
                        for index, action in enumerate(branch.actions, start=1)
                    ),
                ),
                source_key=branch.source_key,
            )
            for branch in ordered
        )

    def _execute_action(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[_Branch, ...]:
        """执行一方行动并在每个确定状态变化点同步记录业务事件。

        Args:
            branches: 当前行动开始前的全局概率分支。
            action: 本轮实际行动顺序中的当前行动。

        Returns:
            包含行动使用、PP 变化、命中、伤害、状态与阻断事件的后继分支。先手造成
            濒死后，后手不会产生 ``MOVE_USED`` 或 ``PP_CHANGED``。
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
                blocking_events = tuple(
                    BattleEvent(
                        kind=BattleEventKind.ACTION_BLOCKED,
                        turn_number=branch.state.turn_number,
                        actor=action.side,
                        target=_opponent_side(action.side),
                        move_id=_move_id(action),
                        source_identifier=decision.source_identifier,
                    )
                    for decision in validation.decisions
                    if not decision.allowed
                )
                completed.append(_branch_with_events(branch, blocking_events))
                continue

            used_branch = _branch_with_events(
                branch,
                (
                    BattleEvent(
                        kind=BattleEventKind.MOVE_USED,
                        turn_number=branch.state.turn_number,
                        actor=action.side,
                        target=_opponent_side(action.side),
                        move_id=_move_id(action),
                        source_identifier=_action_source_identifier(action),
                    ),
                ),
            )
            before_move = self._expand_transition_stage(
                (used_branch,),
                lambda current_state: self.effects.before_move(
                    MoveEffectContext(
                        state=current_state,
                        actor=action.side,
                        action=action,
                    ),
                    (_deterministic_transition(current_state),),
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
                before_pp = (
                    item.state.battler(action.side)
                    .move_slot(action.move_id)
                    .current_pp
                    if isinstance(action, UseMoveAction)
                    else None
                )
                consumed_state = self._consume_action(item.state, action)
                pp_events: tuple[BattleEvent, ...] = ()
                if isinstance(action, UseMoveAction) and before_pp is not None:
                    after_pp = (
                        consumed_state.battler(action.side)
                        .move_slot(action.move_id)
                        .current_pp
                    )
                    pp_events = (
                        BattleEvent(
                            kind=BattleEventKind.PP_CHANGED,
                            turn_number=item.state.turn_number,
                            actor=action.side,
                            move_id=action.move_id,
                            source_identifier="move-use",
                            before_value=before_pp,
                            after_value=after_pp,
                        ),
                    )
                consumed.append(
                    _Branch(
                        probability=item.probability,
                        state=consumed_state,
                        event_summary=append_battle_events(
                            item.event_summary,
                            pp_events,
                        ),
                        source_key=item.source_key,
                    )
                )
            if not consumed:
                continue

            missed, hit = self._run_accuracy_check(tuple(consumed), action)
            damaged = self._run_damage(hit, action) if hit else ()
            after_damage = (
                self._expand_transition_stage_with_hp_events(
                    damaged,
                    action=action,
                    stage=lambda current_state: self.effects.after_damage(
                        MoveEffectContext(
                            state=current_state,
                            actor=action.side,
                            action=action,
                        ),
                        (_deterministic_transition(current_state),),
                    ),
                )
                if damaged
                else ()
            )
            completed.extend((*missed, *after_damage))
        return tuple(completed)

    def _run_accuracy_check(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[tuple[_Branch, ...], tuple[_Branch, ...]]:
        """展开命中分布，并为确定命中与未命中都追加结构化事件。

        Args:
            branches: 已完成 PP 消耗的父分支。
            action: 当前正在执行的行动。

        Returns:
            ``(missed, hit)`` 两组分支；每条路径在随机命中事件之后包含 ``MISS`` 或
            ``HIT`` 业务事实。
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
                summary = branch.event_summary.concatenate(child.event_summary)
                summary = append_battle_events(
                    summary,
                    (
                        BattleEvent(
                            kind=(
                                BattleEventKind.HIT
                                if outcome.hit
                                else BattleEventKind.MISS
                            ),
                            turn_number=branch.state.turn_number,
                            actor=action.side,
                            target=_opponent_side(action.side),
                            move_id=_move_id(action),
                            source_identifier="accuracy",
                        ),
                    ),
                )
                expanded = _Branch(
                    probability=branch.probability * child.probability,
                    state=child.state,
                    event_summary=summary,
                    source_key=child.source_key or branch.source_key,
                )
                (hit if outcome.hit else missed).append(expanded)
        return tuple(missed), tuple(hit)

    def _run_damage(
        self,
        branches: tuple[_Branch, ...],
        action: BattleAction,
    ) -> tuple[_Branch, ...]:
        """组合伤害策略分布，并为未结构化的替换策略补充阶段级 HP 事件。

        Args:
            branches: 命中判定成功的父分支。
            action: 当前已命中的行动。

        Returns:
            父子概率相乘且事件路径按顺序连接的分支。标准结构化伤害策略直接使用其
            事件；测试或自定义策略只改变 HP 时由 resolver 在已知阶段边界补齐事实。
        """
        expanded: list[_Branch] = []
        for parent in branches:
            children = validate_transition_distribution(
                self.damage_policy.resolve(
                    MoveEffectContext(
                        state=parent.state,
                        actor=action.side,
                        action=action,
                    )
                )
            )
            for child in children:
                child_summary = child.event_summary
                if not _summary_has_hp_change(child_summary):
                    child_summary = append_battle_events(
                        child_summary,
                        _hp_change_events(
                            before=parent.state,
                            after=child.state,
                            action=action,
                        ),
                    )
                expanded.append(
                    _Branch(
                        probability=parent.probability * child.probability,
                        state=child.state,
                        event_summary=parent.event_summary.concatenate(child_summary),
                        source_key=child.source_key or parent.source_key,
                    )
                )
        return tuple(expanded)

    def _expand_transition_stage_with_hp_events(
        self,
        branches: tuple[_Branch, ...],
        *,
        action: BattleAction,
        stage: Callable[[BattleState], TransitionSet],
    ) -> tuple[_Branch, ...]:
        """展开一个局部 effect 阶段并记录该阶段新增的 HP 变化。

        Args:
            branches: 当前全局概率分支。
            action: 当前阶段所属行动，用于标识伤害来源和事件双方。
            stage: 接收单个 ``BattleState`` 并返回局部归一化 ``TransitionSet`` 的函数。

        Returns:
            概率、随机路径和该 effect 阶段新增 HP 事件均已组合的全局分支。
        """
        expanded: list[_Branch] = []
        for parent in branches:
            children = validate_transition_distribution(stage(parent.state))
            for child in children:
                child_summary = append_battle_events(
                    child.event_summary,
                    _hp_change_events(
                        before=parent.state,
                        after=child.state,
                        action=action,
                    ),
                )
                expanded.append(
                    _Branch(
                        probability=parent.probability * child.probability,
                        state=child.state,
                        event_summary=parent.event_summary.concatenate(child_summary),
                        source_key=child.source_key or parent.source_key,
                    )
                )
        return tuple(expanded)


@dataclass(frozen=True, slots=True)
class BattleEventStandardMoveTurnResolver:
    """组装标准招式策略与结构化事件完整回合 resolver。

    Args:
        effects: 当前规则集的 move、ability 和 item effect。通用畏缩行动门禁会自动接入。
        legal_action_generator: 负责 PP、禁用、锁招、挣扎和濒死 Pass 的合法行动生成器。
    """

    effects: tuple[BattleEffect, ...] = ()
    legal_action_generator: LegalActionGenerator = StandardLegalActionGenerator()

    def __post_init__(self) -> None:
        """冻结调用方 effect 序列，避免外部集合变化影响后续回合。"""
        object.__setattr__(self, "effects", tuple(self.effects))

    def legal_actions(
        self,
        state: BattleState,
        side: BattleSide,
    ) -> tuple[BattleAction, ...]:
        """返回一侧当前可由行动策略选择的稳定合法行动。

        Args:
            state: 当前行动选择阶段的不可变战斗状态。
            side: 需要生成行动的一方。

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
        """按标准命中、伤害、有效速度和 effect 语义推进结构化完整回合。

        Args:
            state: 必须处于 ``ACTION_SELECTION`` 的正式战斗状态。
            attacker_action: 攻击方从当前合法集合选择的行动。
            defender_action: 防守方从当前合法集合选择的行动。

        Returns:
            精确归一化、按状态键归并并保留全部替代 ``BattleEvent`` 路径的回合结果。
        """
        dispatcher = BattleEventEffectDispatcher[BattleAction].from_effects(
            (FlinchActionGateEffect(), *self.effects)
        )
        return BattleEventTurnResolver(
            legal_action_generator=self.legal_action_generator,
            action_order_policy=EffectiveSpeedActionOrderPolicy(),
            effects=dispatcher,
            accuracy_policy=MoveAccuracyCheckPolicy(),
            damage_policy=BattleEventDamagePolicy(effects=dispatcher),
        ).resolve(state, attacker_action, defender_action)


__all__ = [
    "BattleEventDamagePolicy",
    "BattleEventEffectDispatcher",
    "BattleEventStandardMoveTurnResolver",
    "BattleEventTurnResolver",
]
