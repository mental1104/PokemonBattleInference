from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    damage_context,
)


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _gen9_ruleset():
    return BattleRulesetProfile.GEN9.build()


def _ruleset_with_policy(**changes):
    ruleset = _gen9_ruleset()
    return replace(
        ruleset,
        damage_policy=replace(ruleset.damage_policy, **changes),
    )


def test_reflect_reduces_physical_damage_and_records_screen_stage():
    """
    验证防守方一侧 Reflect 开启时，只对物理直接伤害产生屏障减伤，并在 trace 中写入 SCREEN 阶段。
    场景使用同一只攻击方、同一防守方和同一物理招式，唯一差异是 BattleEnvironment.defender_side.reflect；
    伤害应低于无屏障结果，modifier key、stage、reason 都要可读，方便 Phase 2 走读确认屏障不是普通 final 乘法。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(
        damage_context(attacker=attacker, defender=defender, move=move)
    )
    reflected = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            environment=BattleEnvironment(defender_side=SideConditions(reflect=True)),
        )
    )

    modifier = _modifiers_by_key(reflected)["screen:reflect"]
    assert reflected.max_damage < normal.max_damage
    assert (
        modifier.multiplier
        == _gen9_ruleset().damage_policy.screen_single_target_multiplier
    )
    assert modifier.stage is ModifierStage.SCREEN
    assert "Reflect" in modifier.reason


def test_reflect_does_not_reduce_special_damage():
    """
    验证 Reflect 不影响特殊招式，避免屏障模型把所有伤害统一削弱。
    测试使用火系特殊招式攻击同一目标，防守方一侧开启 Reflect 后，结果必须与无屏障完全一致；
    trace 中也不能出现 screen:reflect，这保护物理/特殊分类分支，后续 Light Screen 与 Aurora Veil 走读时可明确区分。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="flamethrower", move_type=Type.FIRE, power=90)

    normal = calculate_damage_rolls(
        damage_context(attacker=attacker, defender=defender, move=move)
    )
    reflected = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            environment=BattleEnvironment(defender_side=SideConditions(reflect=True)),
        )
    )

    assert reflected.rolls == normal.rolls
    assert "screen:reflect" not in _modifiers_by_key(reflected)


def test_light_screen_reduces_special_damage_and_ignores_physical_damage():
    """
    验证 Light Screen 只削弱特殊直接伤害，不影响物理招式。
    同一防守方开启 light_screen 后，火系特殊招式的伤害必须低于无屏障结果，而物理子弹拳结果必须保持不变；
    trace 只应在特殊场景记录 screen:light_screen，保护屏障语义不会与 Reflect 或普通 final modifier 混淆。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    special_move = BattleMoveFactory.special(
        name="flamethrower", move_type=Type.FIRE, power=90
    )
    physical_move = BattleMoveFactory.bullet_punch()
    environment = BattleEnvironment(defender_side=SideConditions(light_screen=True))

    normal_special = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=special_move,
        )
    )
    screened_special = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=special_move,
            environment=environment,
        )
    )
    normal_physical = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=physical_move,
        )
    )
    screened_physical = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=physical_move,
            environment=environment,
        )
    )

    modifier = _modifiers_by_key(screened_special)["screen:light_screen"]
    assert screened_special.max_damage < normal_special.max_damage
    assert modifier.stage is ModifierStage.SCREEN
    assert screened_physical.rolls == normal_physical.rolls
    assert "screen:light_screen" not in _modifiers_by_key(screened_physical)


def test_aurora_veil_reduces_physical_and_special_damage():
    """
    验证 Aurora Veil 作为防守方一侧的屏障状态，会同时削弱物理和特殊直接伤害。
    本测试分别使用物理子弹拳和火系特殊招式，在同一 defender_side.aurora_veil 环境下计算；
    两种结果都应低于无屏障对照，并且都记录 screen:aurora_veil，明确该机制是屏障阶段而不是天气或道具效果。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    physical_move = BattleMoveFactory.bullet_punch()
    special_move = BattleMoveFactory.special(
        name="flamethrower", move_type=Type.FIRE, power=90
    )
    environment = BattleEnvironment(defender_side=SideConditions(aurora_veil=True))

    normal_physical = calculate_damage_rolls(
        damage_context(attacker=attacker, defender=defender, move=physical_move)
    )
    veiled_physical = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=physical_move,
            environment=environment,
        )
    )
    normal_special = calculate_damage_rolls(
        damage_context(attacker=attacker, defender=defender, move=special_move)
    )
    veiled_special = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=special_move,
            environment=environment,
        )
    )

    assert veiled_physical.max_damage < normal_physical.max_damage
    assert veiled_special.max_damage < normal_special.max_damage
    assert (
        _modifiers_by_key(veiled_physical)["screen:aurora_veil"].stage
        is ModifierStage.SCREEN
    )
    assert (
        _modifiers_by_key(veiled_special)["screen:aurora_veil"].stage
        is ModifierStage.SCREEN
    )


def test_critical_hit_ignores_screens_without_writing_screen_trace():
    """
    验证会心一击会忽略防守方有利的 Reflect、Light Screen 与 Aurora Veil 屏障减伤。
    测试在防守方三种屏障都开启的环境下计算会心物理招式，并与没有屏障的会心结果比较；
    两者伤害应完全一致，trace 不应写入 screen modifier，避免解释层误报屏障已生效。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()
    all_screens = BattleEnvironment(
        defender_side=SideConditions(reflect=True, light_screen=True, aurora_veil=True)
    )

    critical = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            is_critical=True,
        )
    )
    critical_with_screens = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            environment=all_screens,
            is_critical=True,
        )
    )

    modifiers = _modifiers_by_key(critical_with_screens)
    assert critical_with_screens.rolls == critical.rolls
    assert "screen:reflect" not in modifiers
    assert "screen:light_screen" not in modifiers
    assert "screen:aurora_veil" not in modifiers


def test_screen_multiplier_is_policy_configurable():
    """
    验证屏障倍率来自 DamagePolicy，而不是 ScreenDamageModifier 内部硬编码。
    自定义 ruleset 把单体屏障倍率改成四分之一，同一 Reflect 物理伤害场景应比默认二分之一规则更低；
    trace 中 screen:reflect 的 multiplier 也必须等于自定义 policy 字段，保护 Phase 2 对规则配置入口的审查。
    """
    ruleset = _ruleset_with_policy(screen_single_target_multiplier=0.25)
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()
    environment = BattleEnvironment(defender_side=SideConditions(reflect=True))

    default = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            environment=environment,
        )
    )
    custom = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=move,
            ruleset=ruleset,
            environment=environment,
        )
    )

    modifier = _modifiers_by_key(custom)["screen:reflect"]
    assert custom.max_damage < default.max_damage
    assert modifier.multiplier == 0.25
