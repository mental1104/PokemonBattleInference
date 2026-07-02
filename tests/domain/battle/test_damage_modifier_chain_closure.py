from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _modifier_keys(result):
    return [modifier.key for modifier in result.applied_modifiers]


def test_stat_screen_spread_protect_and_random_stage_order_is_stable():
    """
    验证 phase closure 后的默认伤害链顺序稳定：基础威力、攻防能力值、STAB、属性克制、屏障、多目标、保护和随机档位
    都按各自 stage 进入 trace。场景同时启用 Technician、Choice Band、Eviolite、Reflect、spread move 与 protect reduction；
    测试不追求官方 4096 精确链，只保护当前最小兼容链不会把新增机制塞进无 stage 的裸倍率。
    """
    attacker = replace(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        ability="technician",
        item="choice_band",
    )
    defender = replace(
        BattlePokemonFactory.sylveon("max_hp"),
        item="eviolite",
        can_evolve=True,
    )
    result = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.bullet_punch(),
        environment=BattleEnvironment(defender_side=SideConditions(reflect=True)),
        is_spread_move=True,
        is_protect_reduced=True,
    )

    modifiers = _modifiers_by_key(result)
    keys = _modifier_keys(result)
    expected_order = [
        "ability:technician",
        "item:choice_band",
        "item:eviolite",
        "stab",
        "type_effectiveness",
        "screen:reflect",
        "spread_move",
        "protect_reduction",
        "random",
    ]
    assert keys == expected_order
    assert modifiers["ability:technician"].stage is ModifierStage.BASE_POWER
    assert modifiers["item:choice_band"].stage is ModifierStage.ATTACK_STAT
    assert modifiers["item:eviolite"].stage is ModifierStage.DEFENSE_STAT
    assert modifiers["screen:reflect"].stage is ModifierStage.SCREEN
    assert modifiers["spread_move"].stage is ModifierStage.SPREAD
    assert modifiers["protect_reduction"].stage is ModifierStage.PROTECT
    assert modifiers["random"].stage is ModifierStage.RANDOM


def test_critical_stage_precedes_spread_protect_and_final_damage_sources():
    """
    验证会心一击、spread、protect 与 final damage 来源的 trace 顺序符合当前阶段定义。
    攻击方携带 Life Orb，在雨天使用水系 spread 招式，并开启 protect reduction 与 critical；
    trace 应先记录 CRITICAL，再记录 SPREAD、PROTECT，随后才是天气和道具 final damage，最后进入随机档位。
    """
    attacker = replace(BattlePokemonFactory.scizor("max_atk_neutral"), item="life_orb")
    defender = BattlePokemonFactory.sylveon("max_hp")
    result = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90),
        environment=BattleEnvironment(weather=Weather.RAIN),
        is_critical=True,
        is_spread_move=True,
        is_protect_reduced=True,
    )

    modifiers = _modifiers_by_key(result)
    keys = _modifier_keys(result)
    assert modifiers["critical_hit"].stage is ModifierStage.CRITICAL
    assert modifiers["spread_move"].stage is ModifierStage.SPREAD
    assert modifiers["protect_reduction"].stage is ModifierStage.PROTECT
    assert modifiers["weather:rain"].stage is ModifierStage.FINAL_DAMAGE
    assert modifiers["item:life_orb"].stage is ModifierStage.FINAL_DAMAGE
    assert keys.index("critical_hit") < keys.index("spread_move")
    assert keys.index("spread_move") < keys.index("protect_reduction")
    assert keys.index("protect_reduction") < keys.index("weather:rain")
    assert keys.index("item:life_orb") < keys.index("random")


def test_final_damage_sources_keep_distinct_sources_after_closure():
    """
    验证天气、场地和达人带这些既有 final damage 来源，在新增 SCREEN/CRITICAL/SPREAD/PROTECT 阶段后仍保持独立 trace。
    测试分别构造雨天水系、青草场地草系和达人带效果拔群三个场景；
    每个来源都必须留在 FINAL_DAMAGE 阶段，避免 Phase 2 走读时看到新增链路后误判已有机制被迁移或混算。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    rain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.special(name="surf", move_type=Type.WATER, power=90),
        environment=BattleEnvironment(weather=Weather.RAIN),
    )
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=BattleMoveFactory.special(name="energy-ball", move_type=Type.GRASS, power=90),
        environment=BattleEnvironment(terrain=Terrain.GRASSY),
    )
    expert_belt = calculate_damage_rolls(
        attacker=replace(attacker, item="expert_belt"),
        defender=defender,
        move=BattleMoveFactory.bullet_punch(),
    )

    assert _modifiers_by_key(rain)["weather:rain"].stage is ModifierStage.FINAL_DAMAGE
    assert _modifiers_by_key(terrain)["terrain:grassy_terrain"].stage is ModifierStage.FINAL_DAMAGE
    assert _modifiers_by_key(expert_belt)["item:expert_belt"].stage is ModifierStage.FINAL_DAMAGE
