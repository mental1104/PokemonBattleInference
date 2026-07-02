from __future__ import annotations

from dataclasses import replace

import pytest

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def test_technician_boosts_moves_with_power_sixty_or_less_at_base_power_stage():
    """
    验证技术高手只在招式基础威力不超过六十时生效，并且生效阶段是 base power。
    场景使用巨钳螳螂携带 Technician 使用四十威力子弹拳攻击同一防守方，对照组没有特性；
    伤害应提高，trace 应记录 ability:technician，保护该特性不会被错误实现成 final damage 倍率。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    technician = replace(attacker, ability="technician")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    boosted = calculate_damage_rolls(attacker=technician, defender=defender, move=move)

    assert boosted.max_damage > normal.max_damage
    modifier = _modifiers_by_key(boosted)["ability:technician"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.BASE_POWER


def test_technician_does_not_boost_moves_above_power_sixty():
    """
    验证技术高手不会影响基础威力六十一或以上的招式，并且未生效时不得在 trace 中伪造特性修正。
    攻击方、目标和招式除 ability 字段外完全一致，六十一威力钢系物理招式已经超过 Technician 阈值；
    两次计算的随机伤害档位应完全相同，applied_modifiers 中也不应出现 ability:technician。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    technician = replace(attacker, ability="technician")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.physical(name="steel-wing-like", move_type=Type.STEEL, power=61)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    unchanged = calculate_damage_rolls(attacker=technician, defender=defender, move=move)

    assert unchanged.rolls == normal.rolls
    assert "ability:technician" not in _modifiers_by_key(unchanged)


def test_adaptability_replaces_stab_multiplier_with_two_times():
    """
    验证适应力通过 STAB 阶段改写本系加成倍率，而不是另加一个最终伤害倍率。
    攻击方使用本系钢系子弹拳时，普通 STAB 为一点五倍，Adaptability 应把 trace 中的 stab 倍率变成两倍；
    结果伤害高于普通攻击方，并且 stab 记录的 source 指向 ability:adaptability，便于解释生效来源。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    adaptability = replace(attacker, ability="adaptability")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    adapted = calculate_damage_rolls(attacker=adaptability, defender=defender, move=move)

    assert adapted.max_damage > normal.max_damage
    modifier = _modifiers_by_key(adapted)["stab"]
    assert modifier.multiplier == 2.0
    assert modifier.stage is ModifierStage.STAB
    assert modifier.source == "ability:adaptability"


def test_thick_fat_reduces_incoming_fire_and_ice_damage():
    """
    验证厚脂肪作为防守方特性，会在 final damage 阶段削弱火系和冰系直接伤害。
    测试分别使用火系与冰系特殊招式攻击同一目标，对照组没有特性，厚脂肪组应得到更低伤害；
    每个结果都必须记录 ability:thick_fat，说明未知或未生效特性不会被混入该修正来源。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    thick_fat = replace(defender, ability="thick_fat")

    for move_type in (Type.FIRE, Type.ICE):
        move = BattleMoveFactory.special(
            name=f"{move_type.name.lower()}-beam",
            move_type=move_type,
            power=90,
        )
        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        reduced = calculate_damage_rolls(attacker=attacker, defender=thick_fat, move=move)

        assert reduced.max_damage < normal.max_damage
        modifier = _modifiers_by_key(reduced)["ability:thick_fat"]
        assert modifier.multiplier == 0.5
        assert modifier.stage is ModifierStage.FINAL_DAMAGE


@pytest.mark.parametrize("ability", ["filter", "solid_rock"])
def test_filter_and_solid_rock_only_reduce_super_effective_damage(ability):
    """
    验证过滤和坚硬岩石只在防守方受到效果拔群招式时生效，普通效果招式不能触发。
    该用例用钢系物理招式打妖精属性目标作为效果拔群场景，再用普通系物理招式作为非效果拔群场景；
    trace 应只在前者记录对应 ability key，保护 final damage 修正依赖 type_effectiveness 的契约。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    protected = replace(defender, ability=ability)
    super_effective_move = BattleMoveFactory.bullet_punch()
    neutral_move = BattleMoveFactory.physical(name="body-slam", move_type=Type.NORMAL, power=85)

    normal_super = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=super_effective_move,
    )
    reduced_super = calculate_damage_rolls(
        attacker=attacker,
        defender=protected,
        move=super_effective_move,
    )
    normal_neutral = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=neutral_move,
    )
    unchanged_neutral = calculate_damage_rolls(
        attacker=attacker,
        defender=protected,
        move=neutral_move,
    )

    ability_key = f"ability:{ability}"
    assert reduced_super.max_damage < normal_super.max_damage
    assert _modifiers_by_key(reduced_super)[ability_key].stage is ModifierStage.FINAL_DAMAGE
    assert unchanged_neutral.rolls == normal_neutral.rolls
    assert ability_key not in _modifiers_by_key(unchanged_neutral)


def test_unknown_ability_is_no_op_and_not_recorded():
    """
    验证当前未实现的特性会按 no-op 处理，避免第一版扩展框架因为陌生 ability 字符串直接中断伤害计算。
    攻击方带有一个不存在于 registry 的特性，其他输入与对照组完全相同；两次结果必须一致，
    trace 中也不能出现任何 ability:unknown 之类伪造记录，保证解释输出只描述实际生效机制。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    unknown = replace(attacker, ability="future-unimplemented-ability")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    unchanged = calculate_damage_rolls(attacker=unknown, defender=defender, move=move)

    assert unchanged.rolls == normal.rolls
    assert all(not modifier.key.startswith("ability:") for modifier in unchanged.applied_modifiers)
