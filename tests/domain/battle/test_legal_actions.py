from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import (
    PassAction,
    StandardLegalActionGenerator,
    StruggleAction,
    UseMoveAction,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleState, BattlerState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _move_spec(
    move_id: int,
    *,
    name: str,
    priority: int = 0,
    max_pp: int = 5,
) -> MoveSpec:
    """构造合法行动测试使用的招式配置。

    Args:
        move_id: 正整数招式 ID。
        name: 仅供测试诊断展示的规范化招式名。
        priority: 当前规则集下的招式优先级。
        max_pp: 招式槽最大 PP。

    Returns:
        可写入 ``PokemonSpec`` 的不可变 ``MoveSpec``。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=name,
            type=Type.STEEL,
            category=MoveCategory.PHYSICAL,
            power=40,
        ),
        max_pp=max_pp,
        priority=priority,
    )


def _battler(
    *,
    pokemon_id: int,
    speed: int,
    hp: int = 100,
    moves: tuple[MoveSpec, ...] | None = None,
    slots: tuple[MoveSlotState, ...] | None = None,
    choice_lock_move_id: int | None = None,
) -> BattlerState:
    """构造正式 #21 状态模型中的测试战斗方。

    Args:
        pokemon_id: 测试宝可梦稳定 ID。
        speed: 最终速度能力值。
        hp: 当前 HP，最大 HP 固定为 100。
        moves: 一到四个招式配置；省略时创建两个默认招式。
        slots: 与 moves 一一对应的动态槽位；省略时使用满 PP。
        choice_lock_move_id: 可选讲究锁招 ID；存在时自动使用讲究头带并锁定对应槽。

    Returns:
        满足配置、槽位和锁招不变量的 ``BattlerState``。
    """
    configured_moves = moves or (
        _move_spec(101, name="first-move", priority=1),
        _move_spec(102, name="second-move"),
    )
    move_slots = slots or tuple(
        MoveSlotState(
            move_id=move.move_id,
            current_pp=move.max_pp,
            max_pp=move.max_pp,
            is_locked=move.move_id == choice_lock_move_id,
        )
        for move in configured_moves
    )
    spec = PokemonSpec(
        pokemon_id=pokemon_id,
        name=f"pokemon-{pokemon_id}",
        level=50,
        types=(Type.STEEL,),
        stats=StatValues(
            hp=100,
            attack=100,
            defense=100,
            special_attack=100,
            special_defense=100,
            speed=speed,
        ),
        ability=DamageAbility.UNKNOWN,
        item=(
            DamageItem.CHOICE_BAND
            if choice_lock_move_id is not None
            else DamageItem.UNKNOWN
        ),
        moves=configured_moves,
    )
    return BattlerState(
        spec=spec,
        current_hp=hp,
        move_slots=move_slots,
        choice_lock_move_id=choice_lock_move_id,
    )


def _state(attacker: BattlerState) -> BattleState:
    """把指定攻击方放入一个可执行行动选择的 1v1 状态。"""
    return BattleState(
        attacker=attacker,
        defender=_battler(pokemon_id=2, speed=50),
        rules=BattleInferenceRules(level=50),
    )


def test_generator_returns_all_usable_moves_in_slot_order() -> None:
    """可用普通招式应按槽位顺序生成，并携带 MoveSpec 的优先级。"""
    actions = StandardLegalActionGenerator().generate(
        _state(_battler(pokemon_id=1, speed=100)),
        BattleSide.ATTACKER,
    )

    assert actions == (
        UseMoveAction(BattleSide.ATTACKER, 101, priority=1),
        UseMoveAction(BattleSide.ATTACKER, 102, priority=0),
    )


def test_generator_obeys_choice_lock() -> None:
    """讲究锁招存在时只能生成被锁定且仍可使用的招式。"""
    actions = StandardLegalActionGenerator().generate(
        _state(
            _battler(
                pokemon_id=1,
                speed=100,
                choice_lock_move_id=102,
            )
        ),
        BattleSide.ATTACKER,
    )

    assert actions == (UseMoveAction(BattleSide.ATTACKER, 102, priority=0),)


def test_generator_returns_only_struggle_when_every_move_is_unusable() -> None:
    """所有槽位无 PP 或被禁用时，挣扎必须成为唯一合法行动。"""
    moves = (
        _move_spec(201, name="empty"),
        _move_spec(202, name="disabled"),
    )
    battler = _battler(
        pokemon_id=1,
        speed=100,
        moves=moves,
        slots=(
            MoveSlotState(move_id=201, current_pp=0, max_pp=5),
            MoveSlotState(
                move_id=202,
                current_pp=5,
                max_pp=5,
                is_disabled=True,
            ),
        ),
    )

    actions = StandardLegalActionGenerator().generate(
        _state(battler),
        BattleSide.ATTACKER,
    )

    assert actions == (StruggleAction(BattleSide.ATTACKER),)


def test_locked_move_becoming_unusable_forces_struggle() -> None:
    """被锁定招式失效时不能绕过锁招选择其他可用招式。"""
    moves = (
        _move_spec(301, name="locked"),
        _move_spec(302, name="other"),
    )
    battler = _battler(
        pokemon_id=1,
        speed=100,
        moves=moves,
        slots=(
            MoveSlotState(
                move_id=301,
                current_pp=2,
                max_pp=5,
                is_disabled=True,
                is_locked=True,
            ),
            MoveSlotState(move_id=302, current_pp=5, max_pp=5),
        ),
        choice_lock_move_id=301,
    )

    actions = StandardLegalActionGenerator().generate(
        _state(battler),
        BattleSide.ATTACKER,
    )

    assert actions == (StruggleAction(BattleSide.ATTACKER),)


def test_fainted_side_receives_internal_pass_action() -> None:
    """濒死一侧应获得内部 Pass，而不是暴露普通行动给策略。"""
    actions = StandardLegalActionGenerator().generate(
        _state(_battler(pokemon_id=1, speed=100, hp=0)),
        BattleSide.ATTACKER,
    )

    assert actions == (PassAction(BattleSide.ATTACKER),)


def test_formal_battle_state_remains_immutable_and_hashable() -> None:
    """合法行动生成不得破坏 #21 状态的不可变与可哈希合同。"""
    state = _state(_battler(pokemon_id=1, speed=100))
    state_set = {state}

    with pytest.raises(FrozenInstanceError):
        state.attacker.current_hp = 0  # type: ignore[misc]

    assert state in state_set


def test_move_priority_participates_in_state_key() -> None:
    """不同招式优先级必须形成不同配置键，避免行动顺序节点被错误归并。"""
    normal = _move_spec(401, name="priority-check", priority=0)
    elevated = _move_spec(401, name="priority-check", priority=1)

    assert normal.state_key != elevated.state_key
