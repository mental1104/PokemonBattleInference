from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _gen9_ruleset():
    return BattleRulesetProfile.GEN9.build()


def test_spread_move_reduces_damage_and_records_spread_stage():
    """
    验证 is_spread_move=True 表达当前招式命中场景是多目标招式，并应用 spread 阶段减伤。
    同一攻击方、防守方和招式在单体与 spread 两种上下文中计算，spread 结果必须更低；
    trace 要记录 spread_move 且 stage 为 SPREAD，说明该规则不是从 move metadata、数据库或 final damage 硬编码推断。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    single_target = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    spread = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_spread_move=True,
    )

    modifier = _modifiers_by_key(spread)["spread_move"]
    assert spread.max_damage < single_target.max_damage
    assert modifier.multiplier == _gen9_ruleset().damage_policy.spread_move_multiplier
    assert modifier.stage is ModifierStage.SPREAD


def test_non_spread_move_does_not_write_spread_trace():
    """
    验证默认单体伤害不会写入 spread_move trace，避免 Phase 2 走读时把普通招式解释成多目标场景。
    测试不传 is_spread_move 标记，仍走完整正式伤害入口；
    结果 trace 应保留基础的 STAB、属性克制和随机修正，但不能出现 spread 阶段记录。
    """
    result = calculate_damage_rolls(
        attacker=BattlePokemonFactory.scizor("max_atk_neutral"),
        defender=BattlePokemonFactory.sylveon("max_hp"),
        move=BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90),
    )

    assert "spread_move" not in _modifiers_by_key(result)


def test_spread_multiplier_is_policy_configurable():
    """
    验证多目标招式倍率由 DamagePolicy 控制，而不是 SpreadMoveModifier 中固定零点七五。
    自定义 ruleset 把 spread multiplier 改成二分之一，同一 spread 场景应比默认现代规则伤害更低；
    trace 中 multiplier 也必须等于自定义值，保护后续不同世代或特殊规则能通过 policy 扩展。
    """
    default_ruleset = _gen9_ruleset()
    ruleset = replace(
        default_ruleset,
        damage_policy=replace(default_ruleset.damage_policy, spread_move_multiplier=0.5),
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    default = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_spread_move=True,
    )
    custom = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        is_spread_move=True,
    )

    assert custom.max_damage < default.max_damage
    assert _modifiers_by_key(custom)["spread_move"].multiplier == 0.5


def test_spread_move_stacks_with_weather_and_life_orb_with_distinct_trace():
    """
    验证 spread 阶段可以与天气和生命宝珠等 final damage 来源叠加，并且 trace source/stage 彼此区分。
    攻击方携带 Life Orb，在雨天使用水系 spread 招式；伤害链应同时记录 spread_move、weather:rain 和 item:life_orb；
    这个测试保护新增阶段不会覆盖已有 final modifier，也不会把多目标修正混入天气或道具来源。
    """
    attacker = BattlePokemonFactory.with_item(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageItem.LIFE_ORB,
    )
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90)

    result = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(weather=Weather.RAIN),
        is_spread_move=True,
    )

    modifiers = _modifiers_by_key(result)
    assert modifiers["spread_move"].stage is ModifierStage.SPREAD
    assert modifiers["weather:rain"].stage is ModifierStage.FINAL_DAMAGE
    assert modifiers["item:life_orb"].stage is ModifierStage.FINAL_DAMAGE
