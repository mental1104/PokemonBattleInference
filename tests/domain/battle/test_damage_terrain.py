from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def test_electric_terrain_boosts_grounded_electric_attack():
    """
    验证电气场地只要攻击方处于 grounded 状态，就会在 final damage 阶段提升电系招式伤害。
    测试使用默认非飞行攻击方和同一电系特殊招式分别计算无场地与电气场地结果，预期场地结果更高；
    trace 中必须出现 terrain:electric_terrain，说明场地是独立伤害来源而不是被塞进 STAB 或属性克制。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="thunderbolt", move_type=Type.ELECTRIC, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    electric = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.ELECTRIC),
    )

    assert electric.max_damage > normal.max_damage
    modifier = _modifiers_by_key(electric)["terrain:electric_terrain"]
    assert modifier.multiplier == 1.3
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_electric_terrain_does_not_boost_airborne_attacker():
    """
    验证 grounded 判定是场地伤害修正的必要前提，而不是只看场地类型和招式属性。
    攻击方显式标记为 AIRBORNE 后，即使处于电气场地并使用电系招式，伤害也应与普通环境完全一致；
    trace 中不应伪造 terrain:electric_terrain，保护后续加入飞行、漂浮、重力等机制时的扩展边界。
    """
    attacker = replace(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        grounding_state=GroundingState.AIRBORNE,
    )
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="thunderbolt", move_type=Type.ELECTRIC, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    electric = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.ELECTRIC),
    )

    assert electric.rolls == normal.rolls
    assert "terrain:electric_terrain" not in _modifiers_by_key(electric)


def test_psychic_terrain_boosts_grounded_psychic_attack():
    """
    验证精神场地对 grounded 攻击方使用超能系招式的增伤会通过统一 TerrainFinalDamageModifier 生效。
    输入只改变 BattleEnvironment.terrain，攻击方、防守方、招式威力和分类均保持一致；
    结果必须高于普通环境，并且 trace 阶段为 final damage，避免精神场地未来的先制阻止规则混入伤害公式。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="psychic", move_type=Type.PSYCHIC, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.PSYCHIC),
    )

    assert terrain.max_damage > normal.max_damage
    modifier = _modifiers_by_key(terrain)["terrain:psychic_terrain"]
    assert modifier.multiplier == 1.3
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_grassy_terrain_boosts_grounded_grass_attack():
    """
    验证青草场地当前只实现直接伤害增幅，不包含回血或地震类招式削弱等非本轮目标。
    测试中 grounded 攻击方使用草系特殊招式攻击同一目标，青草场地结果必须高于无场地结果；
    trace 记录 terrain:grassy_terrain 和 final damage 阶段，说明后续扩展回血时不会污染当前伤害链。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.special(name="energy-ball", move_type=Type.GRASS, power=90)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.GRASSY),
    )

    assert terrain.max_damage > normal.max_damage
    modifier = _modifiers_by_key(terrain)["terrain:grassy_terrain"]
    assert modifier.multiplier == 1.3
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_misty_terrain_reduces_dragon_damage_to_grounded_defender():
    """
    验证薄雾场地会降低 grounded 防守方受到的龙系直接伤害，并且该机制依赖防守方 grounded 状态。
    为避免妖精免疫龙系造成零伤害，测试把防守方替换成普通属性，普通环境与薄雾场地只差 terrain 字段；
    薄雾场地伤害必须更低，trace 要记录 terrain:misty_terrain，证明减伤来源可被解释层识别。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(BattlePokemonFactory.sylveon("max_hp"), types=(Type.NORMAL,))
    move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.MISTY),
    )

    assert terrain.max_damage < normal.max_damage
    modifier = _modifiers_by_key(terrain)["terrain:misty_terrain"]
    assert modifier.multiplier == 0.5
    assert modifier.stage is ModifierStage.FINAL_DAMAGE


def test_misty_terrain_does_not_reduce_dragon_damage_to_airborne_defender():
    """
    验证薄雾场地不会影响显式处于 AIRBORNE 状态的防守方，即使该防守方正在承受龙系招式。
    这个场景保护 is_grounded 最小模型与 TerrainFinalDamageModifier 的协作边界：场地字段存在但条件不满足时，
    伤害结果应与普通环境一致，trace 也不能出现 terrain:misty_terrain 这种未实际生效的修正项。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = replace(
        BattlePokemonFactory.sylveon("max_hp"),
        types=(Type.NORMAL,),
        grounding_state=GroundingState.AIRBORNE,
    )
    move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    terrain = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        environment=BattleEnvironment(terrain=Terrain.MISTY),
    )

    assert terrain.rolls == normal.rolls
    assert "terrain:misty_terrain" not in _modifiers_by_key(terrain)
