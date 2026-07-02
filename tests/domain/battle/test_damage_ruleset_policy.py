from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.profiles import GEN6_RULESET, GEN9_RULESET
from pokeop.domain.battle.status.modifiers import apply_burn_physical_damage_modifier
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    CombatantStatusFactory,
    MoveProfileFactory,
)


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _ruleset_with_damage_policy(policy: DamagePolicy):
    return replace(GEN9_RULESET, ruleset_id="custom-policy", damage_policy=policy)


def test_modern_terrain_boost_uses_ruleset_policy_multiplier():
    """
    验证现代默认规则下电气场地的增伤倍率来自 BattleRuleset.damage_policy，而不是 TerrainFinalDamageModifier
    内部硬编码的一点三。测试使用 grounded 攻击方、电系特殊招式和同一防守方，对比无场地与电气场地；
    结果应提高，trace 中 terrain:electric_terrain 的 multiplier 必须等于 GEN9 规则集 policy 字段。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="thunderbolt", move_type=Type.ELECTRIC, power=90)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
    )
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
        environment=BattleEnvironment(terrain=Terrain.ELECTRIC),
    )

    modifier = _modifiers_by_key(terrain)["terrain:electric_terrain"]
    assert terrain.max_damage > normal.max_damage
    assert modifier.multiplier == GEN9_RULESET.damage_policy.terrain_boost_multiplier
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_old_ruleset_can_configure_terrain_boost_to_one_point_five():
    """
    验证旧规则或自定义规则可以把场地增伤配置为一点五，证明场地倍率不再写死为现代一点三。
    同一只 grounded 攻击方在电气场地使用同一电系招式，分别传入 GEN9 现代规则和 GEN6 风格规则；
    GEN6 结果应高于现代结果，并且 trace 中的倍率应等于该 ruleset 的 damage_policy 配置。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="thunderbolt", move_type=Type.ELECTRIC, power=90)
    environment = BattleEnvironment(terrain=Terrain.ELECTRIC)

    modern = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
        environment=environment,
    )
    old_style = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN6_RULESET,
        environment=environment,
    )

    modifier = _modifiers_by_key(old_style)["terrain:electric_terrain"]
    assert old_style.max_damage > modern.max_damage
    assert modifier.multiplier == GEN6_RULESET.damage_policy.terrain_boost_multiplier
    assert modifier.multiplier == 1.5


def test_sun_and_rain_weather_multipliers_are_policy_driven():
    """
    验证晴天和雨天的增伤、减伤倍率都从 damage_policy 获取，而不是在天气节点中固定为一点五和零点五。
    自定义 policy 把天气增伤改成二倍、削弱改成零点二五；火系招式在晴天应比现代晴天更高，
    水系招式在晴天应比现代晴天更低，并且两个 trace multiplier 都必须等于自定义 policy 字段。
    """
    custom_ruleset = _ruleset_with_damage_policy(
        DamagePolicy(
            weather_boost_multiplier=2.0,
            weather_weaken_multiplier=0.25,
        )
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    fire_move = BattleMoveFactory.special(name="flamethrower", move_type=Type.FIRE, power=90)
    water_move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)
    sunny = BattleEnvironment(weather=Weather.HARSH_SUNLIGHT)

    modern_fire = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=fire_move,
        ruleset=GEN9_RULESET,
        environment=sunny,
    )
    custom_fire = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=fire_move,
        ruleset=custom_ruleset,
        environment=sunny,
    )
    modern_water = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=water_move,
        ruleset=GEN9_RULESET,
        environment=sunny,
    )
    custom_water = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=water_move,
        ruleset=custom_ruleset,
        environment=sunny,
    )

    assert custom_fire.max_damage > modern_fire.max_damage
    assert custom_water.max_damage < modern_water.max_damage
    assert _modifiers_by_key(custom_fire)["weather:harsh_sunlight"].multiplier == 2.0
    assert _modifiers_by_key(custom_water)["weather:harsh_sunlight"].multiplier == 0.25


def test_sandstorm_rock_special_defense_boost_uses_policy():
    """
    验证沙暴下岩石属性防守方的特防增强倍率来自 ruleset policy，而不是天气防御阶段硬编码。
    自定义 policy 把沙暴岩石特防倍率改为二倍，同一水系特殊招式攻击岩石属性目标时，
    自定义规则的伤害应低于现代默认一点五倍规则，trace 中 weather:sandstorm 也要记录二倍倍率。
    """
    custom_ruleset = _ruleset_with_damage_policy(
        DamagePolicy(sandstorm_rock_spdef_multiplier=2.0)
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ROCK,))
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)
    sandstorm = BattleEnvironment(weather=Weather.SANDSTORM)

    modern = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
        environment=sandstorm,
    )
    custom = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=custom_ruleset,
        environment=sandstorm,
    )

    modifier = _modifiers_by_key(custom)["weather:sandstorm"]
    assert custom.max_damage < modern.max_damage
    assert modifier.multiplier == custom_ruleset.damage_policy.sandstorm_rock_spdef_multiplier
    assert modifier.stage is ModifierStage.DEFENSE_STAT


def test_modern_snow_ice_defense_boost_uses_policy():
    """
    验证现代雪天冰属性物防增强由 damage_policy.snow_ice_defense_multiplier 控制。
    测试把防守方替换为冰属性，用钢系物理招式分别计算普通环境和雪天环境；
    雪天伤害应降低，trace 中 weather:snow 的倍率必须等于现代 policy 字段，保护 Gen9 snow 规则入口。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
    )
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    modifier = _modifiers_by_key(snow)["weather:snow"]
    assert snow.max_damage < normal.max_damage
    assert modifier.multiplier == GEN9_RULESET.damage_policy.snow_ice_defense_multiplier
    assert modifier.stage is ModifierStage.DEFENSE_STAT


def test_old_snow_or_hail_policy_can_disable_ice_defense_boost():
    """
    验证旧冰雹或旧雪天规则可以通过 policy 禁用冰属性物防增强，防止现代 Gen9 snow 规则套到旧世代。
    自定义 ruleset 把 snow_ice_defense_multiplier 设为 None，同一冰属性防守方在雪天承受同一物理招式时，
    伤害应与无天气完全一致，并且 trace 里不能出现 weather:snow 这种未实际生效的防御修正。
    """
    old_ruleset = _ruleset_with_damage_policy(
        DamagePolicy(snow_ice_defense_multiplier=None)
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=old_ruleset,
    )
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=old_ruleset,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    assert snow.rolls == normal.rolls
    assert "weather:snow" not in _modifiers_by_key(snow)


def test_burn_physical_damage_multiplier_uses_damage_policy():
    """
    验证烧伤物理伤害倍率从 ruleset.damage_policy 读取，而不是继续依赖状态规则中的固定倍率字段。
    默认现代规则下烧伤物理招式倍率为二分之一；自定义 policy 改成四分之一后，同一 burned 状态、
    同一物理招式入口应返回更低倍率，保护状态 modifier 与规则差异配置的连接方式。
    """
    custom_ruleset = _ruleset_with_damage_policy(
        DamagePolicy(burn_physical_attack_multiplier=0.25)
    )
    status = CombatantStatusFactory.burned()
    move = MoveProfileFactory.physical(name="tackle")

    default_multiplier = apply_burn_physical_damage_modifier(
        Fraction(1, 1),
        status,
        GEN9_RULESET,
        move,
    )
    custom_multiplier = apply_burn_physical_damage_modifier(
        Fraction(1, 1),
        status,
        custom_ruleset,
        move,
    )

    assert default_multiplier == Fraction(1, 2)
    assert custom_multiplier == Fraction(1, 4)
    assert custom_multiplier < default_multiplier


def test_default_ruleset_matches_explicit_modern_ruleset_for_existing_damage_entry():
    """
    验证旧入口不显式传 ruleset 时仍使用当前现代默认规则，避免新增 damage_policy 后破坏已有调用方。
    测试复用巨钳螳螂子弹拳攻击仙子伊布的基础伤害场景，分别不传规则集和显式传 GEN9_RULESET；
    两次伤害档位和修正倍率记录必须一致，保护 application 旧用例和 domain 旧测试的兼容性。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    implicit = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    explicit = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=GEN9_RULESET,
    )

    implicit_trace = [
        (modifier.key, modifier.multiplier, modifier.min_multiplier, modifier.max_multiplier)
        for modifier in implicit.applied_modifiers
    ]
    explicit_trace = [
        (modifier.key, modifier.multiplier, modifier.min_multiplier, modifier.max_multiplier)
        for modifier in explicit.applied_modifiers
    ]
    assert implicit.rolls == explicit.rolls
    assert implicit_trace == explicit_trace
