from __future__ import annotations

from dataclasses import replace

import pytest

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def test_life_orb_boosts_final_damage_and_records_item_source():
    """
    验证生命宝珠作为攻击方道具进入 final damage 阶段，提升造成的直接伤害。
    测试使用同一攻击方、目标和子弹拳，对照组没有道具，生命宝珠组应获得更高伤害；
    trace 中的 item:life_orb 必须标记为 final damage，避免被错误实现为攻击能力值或基础威力修正。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    life_orb = replace(attacker, item="life_orb")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    boosted = calculate_damage_rolls(attacker=life_orb, defender=defender, move=move)

    assert boosted.max_damage > normal.max_damage
    modifier = _modifiers_by_key(boosted)["item:life_orb"]
    assert modifier.multiplier == 1.3
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_choice_band_only_boosts_physical_attack_stat():
    """
    验证讲究头带只在物理招式中提高攻击能力值，不应影响特殊招式或 final damage 阶段。
    同一攻击方带 Choice Band 后使用物理子弹拳应比无道具更高；使用火系特殊招式时结果应与无道具一致；
    trace 只在物理场景记录 item:choice_band，并且阶段必须是 attack stat。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    band = replace(attacker, item="choice_band")
    defender = BattlePokemonFactory.sylveon("max_hp")
    physical = BattleMoveFactory.bullet_punch()
    special = BattleMoveFactory.special(name="flamethrower", move_type=Type.FIRE, power=90)

    normal_physical = calculate_damage_rolls(attacker=attacker, defender=defender, move=physical)
    boosted_physical = calculate_damage_rolls(attacker=band, defender=defender, move=physical)
    normal_special = calculate_damage_rolls(attacker=attacker, defender=defender, move=special)
    unchanged_special = calculate_damage_rolls(attacker=band, defender=defender, move=special)

    assert boosted_physical.max_damage > normal_physical.max_damage
    modifier = _modifiers_by_key(boosted_physical)["item:choice_band"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.ATTACK_STAT
    assert unchanged_special.rolls == normal_special.rolls
    assert "item:choice_band" not in _modifiers_by_key(unchanged_special)


def test_choice_specs_only_boosts_special_attack_stat():
    """
    验证讲究眼镜只在特殊招式中提高特攻能力值，不应影响物理招式或最终伤害倍率。
    攻击方带 Choice Specs 使用火系特殊招式时伤害应高于无道具；使用物理子弹拳时结果必须完全相同；
    trace 只在特殊场景记录 item:choice_specs，阶段为 attack stat，保护物理/特殊分支边界。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    specs = replace(attacker, item="choice_specs")
    defender = BattlePokemonFactory.sylveon("max_hp")
    physical = BattleMoveFactory.bullet_punch()
    special = BattleMoveFactory.special(name="flamethrower", move_type=Type.FIRE, power=90)

    normal_special = calculate_damage_rolls(attacker=attacker, defender=defender, move=special)
    boosted_special = calculate_damage_rolls(attacker=specs, defender=defender, move=special)
    normal_physical = calculate_damage_rolls(attacker=attacker, defender=defender, move=physical)
    unchanged_physical = calculate_damage_rolls(attacker=specs, defender=defender, move=physical)

    assert boosted_special.max_damage > normal_special.max_damage
    modifier = _modifiers_by_key(boosted_special)["item:choice_specs"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.ATTACK_STAT
    assert unchanged_physical.rolls == normal_physical.rolls
    assert "item:choice_specs" not in _modifiers_by_key(unchanged_physical)


def test_expert_belt_only_boosts_super_effective_final_damage():
    """
    验证达人带依赖属性克制结果，只在招式效果拔群时提升 final damage。
    钢系子弹拳攻击妖精属性目标会触发达人带，普通系物理招式攻击同一目标不会触发；
    trace 应只在效果拔群场景记录 item:expert_belt，保证该道具读取 type_effectiveness 而不是粗暴常驻增伤。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    expert_belt = replace(attacker, item="expert_belt")
    defender = BattlePokemonFactory.sylveon("max_hp")
    super_effective = BattleMoveFactory.bullet_punch()
    neutral = BattleMoveFactory.physical(name="body-slam", move_type=Type.NORMAL, power=85)

    normal_super = calculate_damage_rolls(attacker=attacker, defender=defender, move=super_effective)
    boosted_super = calculate_damage_rolls(attacker=expert_belt, defender=defender, move=super_effective)
    normal_neutral = calculate_damage_rolls(attacker=attacker, defender=defender, move=neutral)
    unchanged_neutral = calculate_damage_rolls(attacker=expert_belt, defender=defender, move=neutral)

    assert boosted_super.max_damage > normal_super.max_damage
    modifier = _modifiers_by_key(boosted_super)["item:expert_belt"]
    assert modifier.multiplier == 1.2
    assert modifier.stage is ModifierStage.FINAL_DAMAGE
    assert unchanged_neutral.rolls == normal_neutral.rolls
    assert "item:expert_belt" not in _modifiers_by_key(unchanged_neutral)


@pytest.mark.parametrize(
    "move",
    [
        BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80),
        BattleMoveFactory.special(name="flash-cannon", move_type=Type.STEEL, power=80),
    ],
)
def test_eviolite_boosts_defenses_only_when_defender_can_evolve(move):
    """
    验证进化奇石作为防守方道具，只在 can_evolve=True 的快照上提高防御或特防能力值。
    测试同时覆盖物理招式和特殊招式，确保 Eviolite 进入 defense stat 阶段而不是最终伤害阶段；
    当同一防守方 can_evolve=False 时结果必须与无道具一致，trace 也不应出现 item:eviolite。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    eviolite_holder = replace(defender, item="eviolite", can_evolve=True)
    cannot_evolve_holder = replace(defender, item="eviolite", can_evolve=False)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    boosted_defense = calculate_damage_rolls(
        attacker=attacker,
        defender=eviolite_holder,
        move=move,
    )
    unchanged = calculate_damage_rolls(
        attacker=attacker,
        defender=cannot_evolve_holder,
        move=move,
    )

    assert boosted_defense.max_damage < normal.max_damage
    modifier = _modifiers_by_key(boosted_defense)["item:eviolite"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.DEFENSE_STAT
    assert unchanged.rolls == normal.rolls
    assert "item:eviolite" not in _modifiers_by_key(unchanged)


def test_unknown_item_is_no_op_and_not_recorded():
    """
    验证当前未实现的道具会作为 no-op 处理，不会让伤害计算因为陌生 item 字符串失败。
    攻击方携带一个未来可能实现但当前 registry 未登记的道具，其他输入与对照组完全一致；
    两次结果必须一致，trace 中也不能出现 item:unknown，保证解释输出只记录真实生效的道具。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    unknown = replace(attacker, item="future-unimplemented-item")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    unchanged = calculate_damage_rolls(attacker=unknown, defender=defender, move=move)

    assert unchanged.rolls == normal.rolls
    assert all(not modifier.key.startswith("item:") for modifier in unchanged.applied_modifiers)
