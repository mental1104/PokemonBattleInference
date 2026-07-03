from __future__ import annotations

import pytest

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.item_effects import (
    BaseItemDamageEffect,
    ChoiceBandEffect,
    ChoiceSpecsEffect,
    EvioliteEffect,
    ExpertBeltEffect,
    LifeOrbEffect,
    resolve_item_effect,
)
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


@pytest.mark.parametrize(
    ("item", "effect_type"),
    [
        (DamageItem.UNKNOWN, BaseItemDamageEffect), # TODO: 这里很明显可以根据枚举直接拿到它的Effect实现类，没必要这么搞元组成对。
        (DamageItem.LIFE_ORB, LifeOrbEffect),
        (DamageItem.CHOICE_BAND, ChoiceBandEffect),
        (DamageItem.CHOICE_SPECS, ChoiceSpecsEffect),
        (DamageItem.EXPERT_BELT, ExpertBeltEffect),
        (DamageItem.EVIOLITE, EvioliteEffect),
    ],
)
def test_damage_item_enum_creates_declared_effect_implementation(item, effect_type):
    """
    验证每个 DamageItem 枚举成员都能通过 create_effect 明确创建对应实现类，而不是依赖裸字符串查表。
    测试参数表列出枚举与实现类的静态关系，配合生产代码中的 match 分支，开发者可以从枚举分支 Ctrl 点击跳转到具体 effect；
    同时断言 trace key 仍由枚举生成，保护新增道具时必须同时补枚举、实现类和关联测试。
    """
    effect = item.create_effect()

    assert isinstance(effect, effect_type)
    assert effect.key == item.trace_key


def test_item_string_resolution_goes_through_damage_item_enum_before_effect_lookup():
    """
    验证道具解析先把外部字符串、连字符名称和中文别名统一映射到 DamageItem 枚举，再从枚举取具体实现。
    该测试不进入完整伤害链，而是直接检查解析边界：Life Orb、life-orb 与生命宝珠都应指向 LIFE_ORB；
    未登记的未来道具必须稳定落到 UNKNOWN no-op 实现，保护后续扩展 registry 时不会继续依赖裸字符串字典对齐。
    """
    assert DamageItem.from_raw("Life Orb") is DamageItem.LIFE_ORB
    assert DamageItem.from_raw("life-orb") is DamageItem.LIFE_ORB
    assert DamageItem.from_raw("生命宝珠") is DamageItem.LIFE_ORB
    assert DamageItem.from_raw("future-unimplemented-item") is DamageItem.UNKNOWN

    eviolite_effect = resolve_item_effect("进化奇石")
    unknown_effect = resolve_item_effect("future-unimplemented-item")
    none_effect = resolve_item_effect(None)

    assert eviolite_effect.key == DamageItem.EVIOLITE.trace_key
    assert unknown_effect.key == DamageItem.UNKNOWN.trace_key
    assert none_effect.key == DamageItem.UNKNOWN.trace_key


def test_life_orb_boosts_final_damage_and_records_item_source():
    """
    验证生命宝珠作为攻击方道具进入 final damage 阶段，提升造成的直接伤害。
    测试使用同一攻击方、目标和子弹拳，对照组没有道具，生命宝珠组应获得更高伤害；
    trace 中的 item:life_orb 必须标记为 final damage，避免被错误实现为攻击能力值或基础威力修正。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    life_orb = BattlePokemonFactory.with_item(attacker, DamageItem.LIFE_ORB)
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
    同一路卡利欧带 Choice Band 后使用物理铁头应比无道具更高；使用它同样可以学习的特殊加农光炮时结果应与无道具一致；
    trace 只在物理场景记录 item:choice_band，并且阶段必须是 attack stat，避免用不会喷射火焰的宝可梦构造错误场景。
    """
    attacker = BattlePokemonFactory.lucario("max_atk_neutral")
    band = BattlePokemonFactory.with_item(attacker, DamageItem.CHOICE_BAND)
    defender = BattlePokemonFactory.sylveon("max_hp")
    physical = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)
    special = BattleMoveFactory.special(name="flash-cannon", move_type=Type.STEEL, power=80)

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
    路卡利欧带 Choice Specs 使用特殊加农光炮时伤害应高于无道具；使用物理铁头时结果必须完全相同；
    trace 只在特殊场景记录 item:choice_specs，阶段为 attack stat，保护物理/特殊分支边界并避免不合法招式搭配。
    """
    attacker = BattlePokemonFactory.lucario("max_spa_neutral")
    specs = BattlePokemonFactory.with_item(attacker, DamageItem.CHOICE_SPECS)
    defender = BattlePokemonFactory.sylveon("max_hp")
    physical = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)
    special = BattleMoveFactory.special(name="flash-cannon", move_type=Type.STEEL, power=80)

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
    expert_belt = BattlePokemonFactory.with_item(attacker, DamageItem.EXPERT_BELT)
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
    验证进化奇石作为防守方道具，只在确实还能进化且 can_evolve=True 的快照上提高防御或特防能力值。
    测试使用可进化的吉利蛋承接物理铁头与特殊加农光炮，确保 Eviolite 进入 defense stat 阶段；
    另用不能再进化的刺甲贝作为负例，要求结果与无道具一致，trace 也不应出现 item:eviolite。
    """
    attacker = BattlePokemonFactory.lucario("max_atk_neutral")
    defender = BattlePokemonFactory.chansey("max_hp")
    eviolite_holder = BattlePokemonFactory.with_item(
        defender,
        DamageItem.EVIOLITE,
        can_evolve=True,
    )
    cannot_evolve_defender = BattlePokemonFactory.cloyster("max_hp")
    cannot_evolve_holder = BattlePokemonFactory.with_item(
        cannot_evolve_defender,
        DamageItem.EVIOLITE,
        can_evolve=False,
    )

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    boosted_defense = calculate_damage_rolls(
        attacker=attacker,
        defender=eviolite_holder,
        move=move,
    )
    cannot_evolve_normal = calculate_damage_rolls(
        attacker=attacker,
        defender=cannot_evolve_defender,
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
    assert unchanged.rolls == cannot_evolve_normal.rolls
    assert "item:eviolite" not in _modifiers_by_key(unchanged)


def test_unknown_item_is_no_op_and_not_recorded():
    """
    验证当前未实现的道具会作为 no-op 处理，不会让伤害计算因为陌生 item 字符串失败。
    攻击方携带一个未来可能实现但当前 registry 未登记的道具，其他输入与对照组完全一致；
    两次结果必须一致，trace 中也不能出现 item:unknown，保证解释输出只记录真实生效的道具。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    unknown = BattlePokemonFactory.with_item(
        attacker,
        DamageItem.from_identifier("future-unimplemented-item"),
    )
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    unchanged = calculate_damage_rolls(attacker=unknown, defender=defender, move=move)

    assert unchanged.rolls == normal.rolls
    assert all(not modifier.key.startswith("item:") for modifier in unchanged.applied_modifiers)
