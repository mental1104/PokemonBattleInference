from __future__ import annotations

from pokeop.domain.battle.effects import PokemonChampionEffectFactory
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type
from tests.domain.battle.test_concrete_move_effects import (
    _battle_state,
    _move_spec,
    _resolve,
)


def test_fake_out_type_immunity_does_not_emit_flinch_attempt() -> None:
    """击掌奇袭命中幽灵属性目标时，普通属性免疫会让统一伤害链产出零伤害，具体 effect 不得仅因为进入 after-damage 阶段就错误施加畏缩。本测试要求攻击方仍按一次合法使用扣除 PP，但幽灵目标保持满 HP、正常执行自己的招式并扣除 PP，同时反击确实降低攻击方 HP，从外部结果证明目标没有被一个无效攻击阻止行动。"""
    fake_out = _move_spec(
        move_id=252,
        name="Fake Out",
        move_type=Type.NORMAL,
        power=40,
        priority=3,
        max_pp=10,
        effect_identifier="fake_out",
    )
    shadow_ball = _move_spec(
        move_id=247,
        name="Shadow Ball",
        move_type=Type.GHOST,
        power=80,
        max_pp=15,
    )
    state = _battle_state(
        attacker_move=fake_out,
        defender_move=shadow_ball,
        attacker_name="Weavile",
        attacker_types=(Type.DARK, Type.ICE),
        attacker_stats=StatValues(170, 172, 85, 60, 105, 90),
        defender_name="Gengar",
        defender_types=(Type.GHOST, Type.POISON),
        defender_stats=StatValues(200, 100, 100, 150, 120, 200),
    )
    effect = PokemonChampionEffectFactory().create_move_effect("fake_out")

    transitions = _resolve(state, effect)

    assert all(
        transition.state.attacker.move_slot(252).current_pp == 9
        for transition in transitions
    )
    assert all(
        transition.state.defender.move_slot(247).current_pp == 14
        for transition in transitions
    )
    assert all(transition.state.defender.current_hp == 200 for transition in transitions)
    assert all(transition.state.attacker.current_hp < 170 for transition in transitions)
