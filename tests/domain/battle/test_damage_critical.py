from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _ruleset(profile: BattleRulesetProfile):
    return profile.build()


def test_critical_hit_increases_damage_and_records_trace():
    """
    验证 is_critical=True 会通过会心阶段提升直接伤害，并写入可解释的 critical_hit trace。
    测试使用同一攻击方、防守方和物理招式，普通结果与会心结果只差 DamageContext 的会心标记；
    会心伤害必须更高，trace 中倍率和 stage 必须来自规则链，保护后续走读确认这不是隐藏 final multiplier。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    critical = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_critical=True,
    )

    modifier = _modifiers_by_key(critical)["critical_hit"]
    assert critical.max_damage > normal.max_damage
    assert modifier.multiplier == _ruleset(BattleRulesetProfile.GEN9).damage_policy.critical_hit_multiplier
    assert modifier.stage is ModifierStage.CRITICAL
    assert "Critical hit" in modifier.reason


def test_critical_multiplier_is_policy_configurable():
    """
    验证会心倍率从 DamagePolicy 读取，而不是 CriticalHitModifier 内部固定为一点五。
    自定义 ruleset 把会心倍率改成二倍，同一会心伤害场景应高于默认现代倍率结果；
    trace 中 critical_hit 的 multiplier 也必须反映自定义 policy，防止新增规则继续扩大硬编码债务。
    """
    default_ruleset = _ruleset(BattleRulesetProfile.GEN9)
    ruleset = replace(
        default_ruleset,
        damage_policy=replace(default_ruleset.damage_policy, critical_hit_multiplier=2.0),
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    default = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_critical=True,
    )
    custom = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        is_critical=True,
    )

    assert custom.max_damage > default.max_damage
    assert _modifiers_by_key(custom)["critical_hit"].multiplier == 2.0


def test_critical_multiplier_changes_from_two_times_to_one_point_five_after_gen_five():
    """
    验证基础会心倍率由 ruleset policy 决定，并锁住第六世代前后的一次关键规则变化。
    场景使用第五世代前已经存在的刺龙王攻击巨钳螳螂，并在 Gen5 与 Gen6 ruleset 下都显式传入 is_critical=True；
    Gen5 trace 应记录二倍会心倍率，Gen6 trace 应记录一点五倍，避免旧世代测试误用后续世代宝可梦或把旧会心伤害压低。
    """
    attacker = BattlePokemonFactory.kingdra("max_spa_neutral")
    defender = BattlePokemonFactory.scizor("max_atk_neutral")
    move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

    gen5 = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=_ruleset(BattleRulesetProfile.GEN5),
        is_critical=True,
    )
    gen6 = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=_ruleset(BattleRulesetProfile.GEN6),
        is_critical=True,
    )

    assert gen5.max_damage > gen6.max_damage
    assert _modifiers_by_key(gen5)["critical_hit"].multiplier == 2.0
    assert _modifiers_by_key(gen6)["critical_hit"].multiplier == 1.5


def test_critical_hit_ignores_all_screen_conditions():
    """
    验证会心一击在当前最小模型中会无视 Reflect、Light Screen 和 Aurora Veil。
    这个测试使用特殊招式并开启全部防守方屏障，确保 Light Screen 与 Aurora Veil 都有潜在生效条件；
    会心结果应与无屏障会心完全一致，trace 中只允许出现 critical_hit 而不能出现任何 screen:* 减伤。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="flash-cannon", move_type=BattleMoveFactory.bullet_punch().type, power=80)
    environment = BattleEnvironment(
        defender_side=SideConditions(reflect=True, light_screen=True, aurora_veil=True)
    )

    critical = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_critical=True,
    )
    critical_with_screens = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=environment,
        is_critical=True,
    )

    modifiers = _modifiers_by_key(critical_with_screens)
    assert critical_with_screens.rolls == critical.rolls
    assert "critical_hit" in modifiers
    assert all(not key.startswith("screen:") for key in modifiers)


def test_non_critical_damage_does_not_write_critical_trace():
    """
    验证普通非会心伤害不会写入 critical_hit trace，避免解释输出误导调用方。
    场景复用标准子弹拳伤害计算，不传 is_critical 标记时，伤害链仍应保留 STAB、属性克制和随机档位；
    但不能出现 critical stage 记录，保护会心字段作为显式输入开关而非默认机制。
    """
    result = calculate_damage_rolls(
        attacker=BattlePokemonFactory.scizor("max_atk_neutral"),
        defender=BattlePokemonFactory.sylveon("max_hp"),
        move=BattleMoveFactory.bullet_punch(),
    )

    assert "critical_hit" not in _modifiers_by_key(result)
