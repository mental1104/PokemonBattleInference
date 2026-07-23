from __future__ import annotations

import inspect
from dataclasses import dataclass
from fractions import Fraction

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import BattleAction, StruggleAction
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects.protocols import (
    BattleEffect,
    EffectCoverage,
    EffectCoverageStatus,
    EffectSourceKind,
    MoveEffectContext,
    TransitionSet,
)
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_execution import (
    FlinchActionGateEffect,
    StandardMoveDamagePolicy,
    StandardMoveTurnResolver,
)
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.rulesets.move_execution_policy import (
    InvalidMoveExecutionPolicy,
    MoveExecutionPolicy,
)
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import (
    BattlePhase,
    BattleState,
    BattlerState,
    StatStages,
)
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import CombatantStatus, FlinchStatus
from pokeop.domain.battle.transitions import (
    TransitionEventType,
    WeightedTransition,
)
from pokeop.domain.models.types import Type


def _coverage(identifier: str) -> EffectCoverage:
    """构造测试 effect 所需的显式机制覆盖记录。

    Args:
        identifier: 测试 effect 的稳定非空标识。

    Returns:
        标记为当前规则集已支持的 move effect 覆盖记录。
    """
    return EffectCoverage(
        ruleset_id="pokemon-champion",
        source_kind=EffectSourceKind.MOVE,
        identifier=identifier,
        status=EffectCoverageStatus.SUPPORTED,
        reason="test effect",
    )


def _move_spec(
    move_id: int,
    *,
    priority: int = 0,
    accuracy: int | None = 100,
    power: int = 40,
    max_pp: int = 5,
) -> MoveSpec:
    """构造通用招式执行测试使用的物理招式配置。

    Args:
        move_id: 测试规则集中的稳定正整数招式 ID。
        priority: 行动顺序使用的招式优先级。
        accuracy: 百分制基础命中率；None 表示跳过普通命中判定。
        power: 现有伤害链使用的正整数基础威力。
        max_pp: 当前招式槽的最大 PP。

    Returns:
        已通过生产代码构造期校验的 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=f"move-{move_id}",
            type=Type.NORMAL,
            category=MoveCategory.PHYSICAL,
            power=power,
        ),
        max_pp=max_pp,
        priority=priority,
        accuracy=accuracy,
    )


def _battler(
    *,
    pokemon_id: int,
    move_id: int,
    speed: int,
    speed_stage: int = 0,
    current_hp: int = 100,
    pp: int = 5,
    priority: int = 0,
    accuracy: int | None = 100,
    power: int = 40,
    flinched: bool = False,
) -> BattlerState:
    """构造包含单个招式槽的正式战斗方状态。

    Args:
        pokemon_id: 测试宝可梦的稳定正整数 ID。
        move_id: 唯一配置招式的稳定正整数 ID。
        speed: ``PokemonSpec`` 中已经计算完成的基础实际速度。
        speed_stage: 当前速度能力等级，必须位于 -6 到 +6。
        current_hp: 当前 HP，测试最大 HP 固定为 100。
        pp: 唯一招式槽当前剩余 PP。
        priority: 唯一招式的优先级。
        accuracy: 唯一招式的百分制基础命中率。
        power: 唯一招式的基础威力。
        flinched: 是否在当前回合开始时携带畏缩临时状态。

    Returns:
        可直接放入 ``BattleState`` 的不可变 ``BattlerState``。
    """
    move = _move_spec(
        move_id,
        priority=priority,
        accuracy=accuracy,
        power=power,
    )
    status = (
        CombatantStatus(volatile=frozenset((FlinchStatus(),)))
        if flinched
        else CombatantStatus()
    )
    spec = PokemonSpec(
        pokemon_id=pokemon_id,
        name=f"pokemon-{pokemon_id}",
        level=50,
        types=(Type.NORMAL,),
        stats=StatValues(
            hp=100,
            attack=100,
            defense=100,
            special_attack=100,
            special_defense=100,
            speed=speed,
        ),
        ability=DamageAbility.UNKNOWN,
        item=DamageItem.UNKNOWN,
        moves=(move,),
    )
    return BattlerState(
        spec=spec,
        current_hp=current_hp,
        move_slots=(
            MoveSlotState(
                move_id=move_id,
                current_pp=pp,
                max_pp=move.max_pp,
            ),
        ),
        stat_stages=StatStages(speed=speed_stage),
        status=status,
    )


def _state(
    *,
    attacker_speed: int = 100,
    defender_speed: int = 80,
    attacker_speed_stage: int = 0,
    defender_speed_stage: int = 0,
    attacker_hp: int = 100,
    defender_hp: int = 100,
    attacker_pp: int = 5,
    defender_pp: int = 5,
    attacker_priority: int = 0,
    defender_priority: int = 0,
    attacker_accuracy: int | None = 100,
    defender_accuracy: int | None = 100,
    attacker_power: int = 40,
    defender_power: int = 40,
    attacker_flinched: bool = False,
    defender_flinched: bool = False,
    rules: BattleInferenceRules | None = None,
) -> BattleState:
    """构造处于行动选择阶段的正式 1v1 测试状态。

    Args:
        attacker_speed: 攻击方基础实际速度。
        defender_speed: 防守方基础实际速度。
        attacker_speed_stage: 攻击方当前速度能力等级。
        defender_speed_stage: 防守方当前速度能力等级。
        attacker_hp: 攻击方当前 HP。
        defender_hp: 防守方当前 HP。
        attacker_pp: 攻击方唯一招式当前 PP。
        defender_pp: 防守方唯一招式当前 PP。
        attacker_priority: 攻击方招式优先级。
        defender_priority: 防守方招式优先级。
        attacker_accuracy: 攻击方招式基础命中率。
        defender_accuracy: 防守方招式基础命中率。
        attacker_power: 攻击方招式基础威力。
        defender_power: 防守方招式基础威力。
        attacker_flinched: 攻击方是否携带当前回合畏缩。
        defender_flinched: 防守方是否携带当前回合畏缩。
        rules: 可选的显式推演规则；省略时使用首版默认规则。

    Returns:
        双方配置、动态状态和规则完整的 ``BattleState``。
    """
    return BattleState(
        attacker=_battler(
            pokemon_id=1,
            move_id=101,
            speed=attacker_speed,
            speed_stage=attacker_speed_stage,
            current_hp=attacker_hp,
            pp=attacker_pp,
            priority=attacker_priority,
            accuracy=attacker_accuracy,
            power=attacker_power,
            flinched=attacker_flinched,
        ),
        defender=_battler(
            pokemon_id=2,
            move_id=202,
            speed=defender_speed,
            speed_stage=defender_speed_stage,
            current_hp=defender_hp,
            pp=defender_pp,
            priority=defender_priority,
            accuracy=defender_accuracy,
            power=defender_power,
            flinched=defender_flinched,
        ),
        rules=rules or BattleInferenceRules(level=50),
    )


def _resolve(
    state: BattleState,
    *,
    effects: tuple[BattleEffect, ...] = (),
) -> tuple[WeightedTransition[BattleState], ...]:
    """使用双方当前第一个合法行动推进一个标准完整回合。

    Args:
        state: 当前行动选择阶段的不可变测试状态。
        effects: 需要接入标准执行器的 fake battle effects。

    Returns:
        标准执行器产生的完整带权后继状态集合。
    """
    resolver = StandardMoveTurnResolver(effects=effects)
    attacker_action = resolver.legal_actions(state, BattleSide.ATTACKER)[0]
    defender_action = resolver.legal_actions(state, BattleSide.DEFENDER)[0]
    return resolver.resolve(
        state,
        attacker_action,
        defender_action,
    ).transitions


@dataclass(frozen=True, slots=True)
class KnockOutTargetAfterDamage:
    """在当前行动伤害完成后把目标 HP 置零，用于观察确定的行动顺序。"""

    coverage: EffectCoverage = _coverage("test-knockout")

    def after_damage(
        self,
        context: MoveEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """保持概率与事件摘要，并把当前行动目标更新为濒死。

        Args:
            context: 当前行动方和伤害发生前后的执行上下文。
            transitions: 已完成伤害随机事件的局部归一化状态分布。

        Returns:
            目标 HP 均为 0、其余转移信息保持不变的新分布。
        """
        target_side = (
            BattleSide.DEFENDER
            if context.actor is BattleSide.ATTACKER
            else BattleSide.ATTACKER
        )
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=transition.state.with_battler(
                    target_side,
                    transition.state.battler(target_side).with_current_hp(0),
                ),
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for transition in transitions
        )


@dataclass(frozen=True, slots=True)
class FlinchTargetAfterDamage:
    """只在指定行动方完成伤害后向其目标施加通用畏缩状态。"""

    source_side: BattleSide
    coverage: EffectCoverage = _coverage("test-apply-flinch")

    def after_damage(
        self,
        context: MoveEffectContext[BattleAction],
        transitions: TransitionSet,
    ) -> TransitionSet:
        """条件性写入目标畏缩，并保持局部概率分布不变。

        Args:
            context: 当前行动方与类型化行动。
            transitions: 已完成伤害的局部归一化状态分布。

        Returns:
            非指定来源保持原分布；指定来源的每条状态都为目标追加 ``FlinchStatus``。
        """
        if context.actor is not self.source_side:
            return transitions
        target_side = (
            BattleSide.DEFENDER
            if context.actor is BattleSide.ATTACKER
            else BattleSide.ATTACKER
        )
        return tuple(
            WeightedTransition(
                probability=transition.probability,
                state=transition.state.with_battler(
                    target_side,
                    transition.state.battler(target_side).with_status(
                        transition.state.battler(target_side).status.add_volatile(
                            FlinchStatus()
                        )
                    ),
                ),
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            for transition in transitions
        )


def test_higher_priority_move_acts_first_even_when_slower() -> None:
    """高优先级招式应在低优先级招式之前行动并取消已濒死后手。"""
    transitions = _resolve(
        _state(
            attacker_speed=40,
            defender_speed=120,
            attacker_priority=1,
            defender_priority=0,
        ),
        effects=(KnockOutTargetAfterDamage(),),
    )

    assert len(transitions) == 1
    state = transitions[0].state
    assert state.phase is BattlePhase.TERMINAL
    assert state.defender.current_hp == 0
    assert state.attacker.current_hp == 100
    assert state.attacker.move_slot(101).current_pp == 4
    assert state.defender.move_slot(202).current_pp == 5


def test_speed_stage_is_applied_before_action_order_comparison() -> None:
    """速度能力等级后的有效速度应决定同优先级行动顺序。"""
    transitions = _resolve(
        _state(
            attacker_speed=60,
            defender_speed=100,
            attacker_speed_stage=2,
        ),
        effects=(KnockOutTargetAfterDamage(),),
    )

    assert len(transitions) == 1
    assert transitions[0].state.defender.current_hp == 0
    assert transitions[0].state.attacker.current_hp == 100


def test_accuracy_creates_exact_hit_and_miss_transitions() -> None:
    """75% 命中率应产生 3/4 命中与 1/4 未命中的可重复分支。"""
    transitions = _resolve(
        _state(
            defender_hp=1,
            attacker_accuracy=75,
            defender_flinched=True,
        )
    )

    assert len(transitions) == 2
    assert {transition.probability for transition in transitions} == {
        Fraction(3, 4),
        Fraction(1, 4),
    }
    assert {
        transition.state.defender.current_hp for transition in transitions
    } == {0, 1}
    assert sum(
        (transition.probability for transition in transitions),
        start=Fraction(0, 1),
    ) == Fraction(1, 1)


def test_regular_damage_reuses_sixteen_rolls_and_updates_hp() -> None:
    """普通伤害应保留现有 16 档事件并把每档结果写入目标当前 HP。"""
    transitions = _resolve(
        _state(
            attacker_power=80,
            defender_flinched=True,
        )
    )

    damage_paths = [
        path
        for transition in transitions
        for path in transition.event_summary.paths
        if any(event.event_type is TransitionEventType.DAMAGE_ROLL for event in path)
    ]
    assert len(damage_paths) == 16
    assert all(transition.state.defender.current_hp < 100 for transition in transitions)
    assert sum(
        (transition.probability for transition in transitions),
        start=Fraction(0, 1),
    ) == Fraction(1, 1)


def test_last_pp_is_consumed_before_damage_but_move_still_resolves() -> None:
    """最后 1 PP 扣成 0 后仍应完成本次已合法选择的伤害。"""
    transitions = _resolve(
        _state(
            attacker_pp=1,
            defender_flinched=True,
        )
    )

    assert all(
        transition.state.attacker.move_slot(101).current_pp == 0
        for transition in transitions
    )
    assert all(transition.state.defender.current_hp < 100 for transition in transitions)


def test_miss_consumes_pp_under_first_move_execution_policy() -> None:
    """首版规则下未命中分支仍应保留行动前已经发生的 1 PP 消耗。"""
    transitions = _resolve(
        _state(
            attacker_pp=1,
            attacker_accuracy=50,
            defender_hp=1,
            defender_flinched=True,
        )
    )

    assert len(transitions) == 2
    assert all(
        transition.state.attacker.move_slot(101).current_pp == 0
        for transition in transitions
    )


def test_flinch_blocks_only_target_that_has_not_acted_yet() -> None:
    """先手施加的畏缩应阻止后手且不消耗后手 PP，并在回合结束清理。"""
    transitions = _resolve(
        _state(attacker_speed=120, defender_speed=80),
        effects=(FlinchTargetAfterDamage(BattleSide.ATTACKER),),
    )

    assert all(
        transition.state.attacker.move_slot(101).current_pp == 4
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(202).current_pp == 5
        for transition in transitions
    )
    assert all(
        not transition.state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
        for transition in transitions
    )


def test_flinch_does_not_cancel_action_that_already_finished() -> None:
    """后手对已行动目标施加畏缩不得追溯取消目标本回合行动。"""
    transitions = _resolve(
        _state(attacker_speed=80, defender_speed=120),
        effects=(FlinchTargetAfterDamage(BattleSide.ATTACKER),),
    )

    assert all(
        transition.state.attacker.move_slot(101).current_pp == 4
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(202).current_pp == 4
        for transition in transitions
    )
    assert all(
        not transition.state.defender.status.has_volatile(VolatileStatusKind.FLINCH)
        for transition in transitions
    )


def test_all_pp_exhausted_allows_only_struggle_with_recoil() -> None:
    """全部普通招式 PP 耗尽时只能挣扎，并按最大 HP 的 1/4 承受反伤。"""
    state = _state(
        attacker_pp=0,
        defender_flinched=True,
    )
    resolver = StandardMoveTurnResolver()
    legal_actions = resolver.legal_actions(state, BattleSide.ATTACKER)

    assert legal_actions == (StruggleAction(BattleSide.ATTACKER),)

    transitions = resolver.resolve(
        state,
        legal_actions[0],
        resolver.legal_actions(state, BattleSide.DEFENDER)[0],
    ).transitions
    assert all(transition.state.attacker.current_hp == 75 for transition in transitions)
    assert all(transition.state.defender.current_hp < 100 for transition in transitions)
    assert all(
        transition.state.attacker.move_slot(101).current_pp == 0
        for transition in transitions
    )


def test_struggle_can_create_deterministic_simultaneous_faint() -> None:
    """挣扎直接伤害与反伤都致死时应归并为双方同时濒死的确定终局。"""
    transitions = _resolve(
        _state(
            attacker_hp=25,
            defender_hp=1,
            attacker_pp=0,
            defender_flinched=True,
        )
    )

    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.probability == Fraction(1, 1)
    assert transition.state.phase is BattlePhase.TERMINAL
    assert transition.state.attacker.current_hp == 0
    assert transition.state.defender.current_hp == 0
    assert len(transition.event_summary.paths) == 16


def test_accuracy_is_part_of_move_and_battle_state_keys() -> None:
    """不同基础命中率必须产生不同招式键和战斗状态键。"""
    certain = _state(attacker_accuracy=100)
    uncertain = _state(attacker_accuracy=90)

    assert (
        certain.attacker.spec.moves[0].state_key
        != uncertain.attacker.spec.moves[0].state_key
    )
    assert certain.state_key != uncertain.state_key


def test_move_execution_policy_rejects_unsupported_pp_semantics() -> None:
    """首版 policy 应拒绝执行器尚未支持的 PP 消耗语义。"""
    with pytest.raises(InvalidMoveExecutionPolicy):
        MoveExecutionPolicy(consume_pp_when_action_blocked=True)


def test_standard_executor_contains_no_concrete_move_identifier_branch() -> None:
    """通用执行策略不得按冰冻拳、击掌奇袭或劈瓦 identifier 分支。"""
    source = (
        inspect.getsource(StandardMoveDamagePolicy)
        + inspect.getsource(StandardMoveTurnResolver)
        + inspect.getsource(FlinchActionGateEffect)
    ).lower()

    assert "ice-punch" not in source
    assert "fake-out" not in source
    assert "brick-break" not in source
