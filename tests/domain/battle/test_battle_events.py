from __future__ import annotations

from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.battle_events import (
    BattleEvent,
    BattleEventKind,
    InvalidBattleEventError,
    battle_event_paths,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.effects import BattleEffect, PokemonChampionEffectFactory
from pokeop.domain.battle.effects.move_effects import FakeOutEffect, IcePunchEffect
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifier_keys import ModifierKey
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattlePhase, BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.state import CombatantStatus, FlinchStatus
from pokeop.domain.battle.structured_turn_resolver import (
    BattleEventStandardMoveTurnResolver,
)
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.models.types import Type


def _move_spec(
    move_id: int,
    *,
    effect_identifier: str | None = None,
    accuracy: int | None = 100,
    power: int = 40,
    priority: int = 0,
) -> MoveSpec:
    """构造结构化战报测试使用的普通物理招式配置。

    Args:
        move_id: 测试范围内唯一的正整数招式 ID。
        effect_identifier: 可选的具体 move effect 标识。
        accuracy: 百分制基础命中率；None 表示跳过普通命中判定。
        power: 参与标准伤害公式的基础威力。
        priority: 当前规则集下的行动优先级。

    Returns:
        已完成领域校验的不可变 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=f"move-{move_id}",
            type=Type.NORMAL,
            category=MoveCategory.PHYSICAL,
            power=power,
        ),
        max_pp=10,
        priority=priority,
        accuracy=accuracy,
        effect_identifier=effect_identifier,
    )


def _battler(
    *,
    pokemon_id: int,
    move: MoveSpec,
    speed: int,
    ability: DamageAbility = DamageAbility.UNKNOWN,
    current_hp: int = 100,
    flinched: bool = False,
) -> BattlerState:
    """构造单招式、可指定特性和临时状态的正式战斗方。

    Args:
        pokemon_id: 测试宝可梦的稳定正整数 ID。
        move: 当前唯一配置招式。
        speed: 用于标准行动排序的最终速度。
        ability: 已归一化的 domain 特性枚举。
        current_hp: 当前 HP，测试最大 HP 固定为 100。
        flinched: 是否在回合开始时携带畏缩状态。

    Returns:
        可直接放入 ``BattleState`` 的不可变 ``BattlerState``。
    """
    status = (
        CombatantStatus(volatile=frozenset((FlinchStatus(),)))
        if flinched
        else CombatantStatus()
    )
    return BattlerState(
        spec=PokemonSpec(
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
            ability=ability,
            item=DamageItem.UNKNOWN,
            moves=(move,),
        ),
        current_hp=current_hp,
        move_slots=(
            MoveSlotState(
                move_id=move.move_id,
                current_pp=move.max_pp,
                max_pp=move.max_pp,
            ),
        ),
        status=status,
    )


def _state(
    *,
    attacker_move: MoveSpec,
    defender_move: MoveSpec | None = None,
    defender_ability: DamageAbility = DamageAbility.UNKNOWN,
    defender_hp: int = 100,
    defender_flinched: bool = False,
    damage_policy: DamagePolicy | None = None,
) -> BattleState:
    """构造攻击方确定先手的结构化回合测试状态。

    Args:
        attacker_move: 攻击方唯一配置招式。
        defender_move: 防守方唯一招式；省略时构造普通低威力招式。
        defender_ability: 防守方待测特性。
        defender_hp: 防守方当前 HP。
        defender_flinched: 是否预置畏缩以隔离攻击方路径。
        damage_policy: 可选伤害规则；省略时保留现代 16 档随机倍率。

    Returns:
        处于 ``ACTION_SELECTION`` 的正式 1v1 ``BattleState``。
    """
    resolved_defender_move = defender_move or _move_spec(202, power=10)
    return BattleState(
        attacker=_battler(
            pokemon_id=1,
            move=attacker_move,
            speed=120,
        ),
        defender=_battler(
            pokemon_id=2,
            move=resolved_defender_move,
            speed=80,
            ability=defender_ability,
            current_hp=defender_hp,
            flinched=defender_flinched,
        ),
        rules=BattleInferenceRules(
            level=50,
            damage_policy=damage_policy or DamagePolicy.modern(),
        ),
    )


def _resolve(
    state: BattleState,
    *,
    effects: tuple[BattleEffect, ...] = (),
) -> tuple[WeightedTransition[BattleState], ...]:
    """选择双方首个合法行动并推进一个结构化完整回合。

    Args:
        state: 当前正式行动选择状态。
        effects: 需要接入 dispatcher 的 move、ability 或 item effect。

    Returns:
        按状态键归并且概率严格归一化的完整后继转移集合。
    """
    resolver = BattleEventStandardMoveTurnResolver(effects=effects)
    attacker_action = resolver.legal_actions(state, BattleSide.ATTACKER)[0]
    defender_action = resolver.legal_actions(state, BattleSide.DEFENDER)[0]
    return resolver.resolve(
        state,
        attacker_action,
        defender_action,
    ).transitions


def _all_paths(
    transitions: tuple[WeightedTransition[BattleState], ...],
) -> tuple[tuple[BattleEvent, ...], ...]:
    """收集一组转移中的全部结构化业务事件替代路径。

    Args:
        transitions: 完整回合产生的按状态归并转移。

    Returns:
        保持转移顺序和摘要路径顺序的 ``BattleEvent`` 路径集合。
    """
    return tuple(
        path
        for transition in transitions
        for path in battle_event_paths(transition.event_summary)
    )


def _event_index(
    path: tuple[BattleEvent, ...],
    kind: BattleEventKind,
    *,
    actor: BattleSide | None = None,
) -> int:
    """返回路径中首个匹配类别和可选主体的事件位置。

    Args:
        path: 单条按发生顺序排列的结构化业务事件路径。
        kind: 需要定位的事件类别。
        actor: 可选主体过滤；None 表示不限制主体。

    Returns:
        首个匹配事件的从零开始索引。

    Raises:
        AssertionError: 路径中不存在匹配事件时抛出。
    """
    for index, event in enumerate(path):
        if event.kind is kind and (actor is None or event.actor is actor):
            return index
    raise AssertionError(f"missing battle event: {kind.value}")


def test_battle_event_is_immutable_and_derives_numeric_delta() -> None:
    """结构化事件应冻结字段，并从 before/after 自动计算 delta 与 value。"""
    event = BattleEvent(
        kind=BattleEventKind.PP_CHANGED,
        turn_number=1,
        actor=BattleSide.ATTACKER,
        move_id=101,
        before_value=10,
        after_value=9,
    )

    assert event.delta == -1
    assert event.value == -1
    assert event.numeric_value == -1
    with pytest.raises(FrozenInstanceError):
        event.value = 0  # type: ignore[misc]
    with pytest.raises(InvalidBattleEventError):
        BattleEvent(
            kind=BattleEventKind.HP_CHANGED,
            turn_number=1,
            before_value=100,
        )


def test_ice_punch_hit_and_miss_paths_record_selection_pp_and_accuracy() -> None:
    """冰冻拳命中与未命中应共享选招/PP 事实，并分别记录 HIT、MISS 与伤害。"""
    state = _state(
        attacker_move=_move_spec(
            101,
            effect_identifier="ice_punch",
            accuracy=75,
            power=60,
        ),
        defender_flinched=True,
        damage_policy=DamagePolicy(random_damage_multipliers=(1.0,)),
    )
    transitions = _resolve(state, effects=(IcePunchEffect(),))
    paths = _all_paths(transitions)

    assert len(paths) == 2
    hit_path = next(
        path
        for path in paths
        if any(event.kind is BattleEventKind.HIT for event in path)
    )
    miss_path = next(
        path
        for path in paths
        if any(event.kind is BattleEventKind.MISS for event in path)
    )
    for path in (hit_path, miss_path):
        selected = next(
            event
            for event in path
            if event.kind is BattleEventKind.MOVE_SELECTED
            and event.actor is BattleSide.ATTACKER
        )
        pp_changed = next(
            event
            for event in path
            if event.kind is BattleEventKind.PP_CHANGED
            and event.actor is BattleSide.ATTACKER
        )
        assert selected.move_id == 101
        assert pp_changed.before_value == 10
        assert pp_changed.after_value == 9
        assert _event_index(
            path,
            BattleEventKind.MOVE_USED,
            actor=BattleSide.ATTACKER,
        ) < _event_index(
            path,
            BattleEventKind.PP_CHANGED,
            actor=BattleSide.ATTACKER,
        )

    assert any(event.kind is BattleEventKind.DAMAGE for event in hit_path)
    assert not any(event.kind is BattleEventKind.DAMAGE for event in miss_path)
    assert sum(
        (transition.probability for transition in transitions),
        start=Fraction(0, 1),
    ) == Fraction(1, 1)


def test_damage_rolls_keep_sixteen_alternative_paths_after_overkill_merge() -> None:
    """16 档伤害全部击倒同一目标时仍应保留 16 条可解释替代事件路径。"""
    transitions = _resolve(
        _state(
            attacker_move=_move_spec(101, power=80),
            defender_hp=1,
            defender_flinched=True,
        )
    )

    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.state.phase is BattlePhase.TERMINAL
    assert transition.state.defender.current_hp == 0
    paths = battle_event_paths(transition.event_summary)
    damage_paths = tuple(
        path
        for path in paths
        if any(event.kind is BattleEventKind.DAMAGE for event in path)
    )
    assert len(damage_paths) == 16
    assert all(
        any(
            event.kind is BattleEventKind.DAMAGE and event.value == 1
            for event in path
        )
        for path in damage_paths
    )
    assert all(
        _event_index(path, BattleEventKind.FAINTED)
        < _event_index(path, BattleEventKind.TURN_ENDED)
        for path in damage_paths
    )
    assert all(
        not any(
            event.kind in {BattleEventKind.MOVE_USED, BattleEventKind.PP_CHANGED}
            and event.actor is BattleSide.DEFENDER
            for event in path
        )
        for path in damage_paths
    )


def test_multiscale_trigger_is_recorded_before_damage() -> None:
    """满 HP 多重鳞片生效时应先记录特性来源，再记录本次实际伤害。"""
    effect = PokemonChampionEffectFactory().create_ability_effect(
        DamageAbility.MULTISCALE
    )
    transitions = _resolve(
        _state(
            attacker_move=_move_spec(101, power=80),
            defender_ability=DamageAbility.MULTISCALE,
            defender_flinched=True,
            damage_policy=DamagePolicy(random_damage_multipliers=(1.0,)),
        ),
        effects=(effect,),
    )
    path = _all_paths(transitions)[0]

    trigger = next(
        event
        for event in path
        if event.kind is BattleEventKind.ABILITY_TRIGGERED
    )
    assert trigger.actor is BattleSide.DEFENDER
    assert trigger.source_identifier == ModifierKey.ABILITY_MULTISCALE.value
    assert _event_index(path, BattleEventKind.ABILITY_TRIGGERED) < _event_index(
        path,
        BattleEventKind.DAMAGE,
    )


def test_fake_out_records_flinch_application_and_action_block() -> None:
    """击掌奇袭成功畏缩后手时应记录状态施加、阻断来源且不扣后手 PP。"""
    transitions = _resolve(
        _state(
            attacker_move=_move_spec(
                101,
                effect_identifier="fake_out",
                power=40,
                priority=3,
            ),
            damage_policy=DamagePolicy(random_damage_multipliers=(1.0,)),
        ),
        effects=(FakeOutEffect(),),
    )
    path = _all_paths(transitions)[0]

    applied = next(
        event for event in path if event.kind is BattleEventKind.STATUS_APPLIED
    )
    blocked = next(
        event
        for event in path
        if event.kind is BattleEventKind.ACTION_BLOCKED
        and event.actor is BattleSide.DEFENDER
    )
    assert applied.source_identifier == "fake_out"
    assert applied.target is BattleSide.DEFENDER
    assert blocked.source_identifier == "flinch"
    assert _event_index(path, BattleEventKind.STATUS_APPLIED) < _event_index(
        path,
        BattleEventKind.ACTION_BLOCKED,
        actor=BattleSide.DEFENDER,
    )
    assert not any(
        event.kind is BattleEventKind.PP_CHANGED
        and event.actor is BattleSide.DEFENDER
        for event in path
    )


def test_inner_focus_records_prevention_without_flinch_blocking() -> None:
    """精神力应记录特性触发与状态阻止，同时允许目标正常行动并消耗 PP。"""
    inner_focus = PokemonChampionEffectFactory().create_ability_effect(
        DamageAbility.INNER_FOCUS
    )
    transitions = _resolve(
        _state(
            attacker_move=_move_spec(
                101,
                effect_identifier="fake_out",
                power=40,
                priority=3,
            ),
            defender_ability=DamageAbility.INNER_FOCUS,
            damage_policy=DamagePolicy(random_damage_multipliers=(1.0,)),
        ),
        effects=(FakeOutEffect(), inner_focus),
    )
    path = _all_paths(transitions)[0]

    trigger = next(
        event
        for event in path
        if event.kind is BattleEventKind.ABILITY_TRIGGERED
        and event.source_identifier == DamageAbility.INNER_FOCUS.value
    )
    prevented = next(
        event
        for event in path
        if event.kind is BattleEventKind.STATUS_PREVENTED
    )
    assert trigger.actor is BattleSide.DEFENDER
    assert prevented.source_identifier == DamageAbility.INNER_FOCUS.value
    assert not any(event.kind is BattleEventKind.STATUS_APPLIED for event in path)
    assert not any(
        event.kind is BattleEventKind.ACTION_BLOCKED
        and event.actor is BattleSide.DEFENDER
        for event in path
    )
    assert any(
        event.kind is BattleEventKind.MOVE_USED
        and event.actor is BattleSide.DEFENDER
        for event in path
    )
    assert any(
        event.kind is BattleEventKind.PP_CHANGED
        and event.actor is BattleSide.DEFENDER
        and event.before_value == 10
        and event.after_value == 9
        for event in path
    )
