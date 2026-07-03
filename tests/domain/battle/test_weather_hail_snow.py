from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_generation
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _gen9_ruleset():
    return BattleRulesetProfile.GEN9.build()


def test_hail_does_not_trigger_ice_defense_boost_under_modern_policy():
    """
    验证 Weather.HAIL 表示旧世代冰雹语义，即使在现代 damage policy 下也不会触发现代雪天的冰系物防增强。
    测试把防守方替换为冰属性，使用同一钢系物理招式分别计算无天气和 HAIL；
    两次伤害档位必须一致，trace 中不能出现 weather:snow 或 weather:hail 防御修正，避免 HAIL 与 SNOW 混用。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)
    ruleset = _gen9_ruleset()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    hail = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.HAIL),
    )

    modifiers = _modifiers_by_key(hail)
    assert hail.rolls == normal.rolls
    assert "weather:snow" not in modifiers
    assert "weather:hail" not in modifiers


def test_snow_triggers_ice_defense_boost_under_modern_policy():
    """
    验证 Weather.SNOW 表示现代雪天语义，会在 modern policy 下触发冰属性防守方的物防增强。
    同一冰属性防守方承受同一物理招式时，SNOW 结果应低于无天气；
    trace 必须记录 weather:snow 且阶段为 defense stat，从而与 Weather.HAIL 的旧冰雹语义区分开。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)
    ruleset = _gen9_ruleset()

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
    )
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    modifier = _modifiers_by_key(snow)["weather:snow"]
    assert snow.max_damage < normal.max_damage
    assert modifier.stage is ModifierStage.DEFENSE_STAT
    assert modifier.multiplier == ruleset.damage_policy.snow_ice_defense_multiplier


def test_snow_does_not_trigger_ice_defense_boost_under_generation_eight_policy():
    """
    验证第八世代 ruleset 即使收到 Weather.SNOW，也不会启用第九世代才有的冰属性物防增强。
    场景使用同一冰属性防守方承受钢系物理招式，普通环境与雪天环境只差天气字段，并显式传入 Gen8 ruleset；
    两次伤害档位必须完全一致，trace 中不能出现 weather:snow，防止 Gen8 通过 modern profile 误套 Gen9 雪天规则。
    """
    ruleset = resolve_ruleset_by_generation(8)
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
    )
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    assert snow.rolls == normal.rolls
    assert "weather:snow" not in _modifiers_by_key(snow)


def test_snow_does_not_trigger_ice_defense_boost_under_legacy_policy():
    """
    验证即使调用方传入 Weather.SNOW，只要 ruleset policy 禁用了 snow_ice_defense_multiplier，冰系物防增强也不会生效。
    这里使用 resolver 返回的第五世代 legacy profile，并选择该世代已经存在的 Cloyster 作为冰属性防守方；
    测试保护 policy gate 的优先级，确保天气枚举、世代规则和测试对象世代语义都一致时才判断 defense stat 修正。
    """
    ruleset = resolve_ruleset_by_generation(5)
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.cloyster("max_hp")
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    normal = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
    )
    snow = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        environment=BattleEnvironment(weather=Weather.SNOW),
    )

    assert snow.rolls == normal.rolls
    assert "weather:snow" not in _modifiers_by_key(snow)


def test_hail_and_snow_trace_sources_remain_distinct_when_policy_enables_hail():
    """
    验证 HAIL 与 SNOW 的 trace source 不会互相伪装：默认规则下 HAIL 不生效，若未来 policy 显式启用冰雹防御增强，
    伤害链应记录 weather:hail 而不是 weather:snow。本测试用替换后的自定义 ruleset 打开 hail_ice_defense_multiplier，
    只检查 source 与阶段边界，避免在本轮新增旧冰雹持续回合或回合末扣血等非目标机制。
    """
    default_ruleset = _gen9_ruleset()
    ruleset = replace(
        default_ruleset,
        damage_policy=replace(default_ruleset.damage_policy, hail_ice_defense_multiplier=1.25),
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.ICE,))
    move = BattleMoveFactory.physical(name="iron-head", move_type=Type.STEEL, power=80)

    hail = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        environment=BattleEnvironment(weather=Weather.HAIL),
    )

    modifiers = _modifiers_by_key(hail)
    assert "weather:hail" in modifiers
    assert "weather:snow" not in modifiers
    assert modifiers["weather:hail"].stage is ModifierStage.DEFENSE_STAT
    assert modifiers["weather:hail"].multiplier == 1.25
