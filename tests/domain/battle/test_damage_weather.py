from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_generation
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def test_harsh_sunlight_boosts_fire_damage_and_records_final_stage():
    """
    验证晴天作为战斗环境进入统一伤害上下文后，会在 final damage 阶段提升火系招式伤害。
    场景使用同一攻击方、防守方和火系特殊招式分别计算普通环境与晴天环境，预期晴天结果更高，
    并且 trace 中出现 weather:harsh_sunlight，而不是把该倍率混进基础威力、攻防能力值或 STAB 阶段。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(
        name="flamethrower",
        move_type=Type.FIRE,
        power=90,
    )

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    sunny = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.HARSH_SUNLIGHT),
    )

    assert sunny.max_damage > normal.max_damage
    modifier = _modifiers_by_key(sunny)["weather:harsh_sunlight"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_harsh_sunlight_weakens_water_damage_without_other_stage_pollution():
    """
    验证晴天对水系招式的削弱同样经过统一 final damage 修正链，而不是通过改写招式模型或攻防数值实现。
    同一只攻击方使用同一水系特殊招式攻击同一目标时，晴天下的最高伤害必须低于普通环境；
    trace 需要记录明确天气来源，方便后续解释系统区分天气削弱和属性克制、随机档位等其他修正。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    sunny = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.HARSH_SUNLIGHT),
    )

    assert sunny.max_damage < normal.max_damage
    modifier = _modifiers_by_key(sunny)["weather:harsh_sunlight"]
    assert modifier.multiplier == 0.5
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_rain_boosts_water_damage_and_records_final_stage():
    """
    验证雨天作为 BattleEnvironment 的天气字段参与伤害计算时，会提升水系招式的最终伤害倍率。
    这个用例保护新增 DamageContext 入口和旧 attacker/defender/move 入口的兼容关系：除环境不同外，
    其他输入完全一致，结果差异只能来自 weather:rain 这个 final damage 修正项。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    rainy = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.RAIN),
    )

    assert rainy.max_damage > normal.max_damage
    modifier = _modifiers_by_key(rainy)["weather:rain"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_rain_weakens_fire_damage_and_keeps_weather_trace_specific():
    """
    验证雨天削弱火系招式时不会伪造成特性、道具或属性克制修正，而是以 weather:rain 记录在 trace 中。
    这个场景使用同一火系招式对同一防守方分别计算普通环境与雨天环境，预期雨天结果更低；
    同时断言修正阶段为 final damage，保证后续加入其他天气特性时仍能按阶段组合。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(
        name="flamethrower",
        move_type=Type.FIRE,
        power=90,
    )

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    rainy = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.RAIN),
    )

    assert rainy.max_damage < normal.max_damage
    modifier = _modifiers_by_key(rainy)["weather:rain"]
    assert modifier.multiplier == 0.5
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_sandstorm_boosts_rock_special_defense_in_defense_stat_stage():
    """
    验证沙暴下岩石属性防守方承受特殊招式时，特防提升发生在 defense stat 阶段，而不是最终伤害倍率。
    测试把仙子伊布快照替换成岩石属性目标，使用同一水系特殊招式计算普通环境与沙暴环境；
    沙暴结果应更低，trace 应精确记录 weather:sandstorm 的倍率和阶段，保护攻防数值修正链的边界。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ROCK,))
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    sandstorm = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.SANDSTORM),
    )

    assert sandstorm.max_damage < normal.max_damage
    modifier = _modifiers_by_key(sandstorm)["weather:sandstorm"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.DEFENSE_STAT


def test_sandstorm_does_not_boost_rock_special_defense_before_generation_four():
    """
    验证第三世代规则下沙暴不会提高岩石属性防守方的特防，保护 Gen4 才引入的沙暴加特防断点。
    场景仍然使用岩石属性目标承受水系特殊招式，普通环境与沙暴环境只差天气字段，并显式传入 Gen3 ruleset；
    两次伤害档位必须完全一致，trace 中也不能出现 weather:sandstorm，说明 modifier 受 ruleset policy gate 控制。
    """
    ruleset = resolve_ruleset_by_generation(3)
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ROCK,))
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
    )
    sandstorm = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        environment=BattleEnvironment(weather=Weather.SANDSTORM),
    )

    assert sandstorm.rolls == normal.rolls
    assert "weather:sandstorm" not in _modifiers_by_key(sandstorm)


def test_snow_boosts_ice_physical_defense_in_modern_rules():
    """
    验证现代雪天天气在物理招式伤害中提高冰属性防守方的物防，且该效果进入 defense stat 阶段。
    场景使用钢系物理招式攻击被替换为冰属性的防守方，普通环境与雪天环境只差天气字段；
    雪天最高伤害必须更低，trace 要记录 weather:snow，避免未来实现冰雹或世代差异时混淆规则来源。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    assert snow.max_damage < normal.max_damage
    modifier = _modifiers_by_key(snow)["weather:snow"]
    assert modifier.multiplier == 1.5
    assert modifier.stage is ModifierStage.DEFENSE_STAT
