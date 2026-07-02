from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.grounding import GroundingState, is_grounded
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattlePokemonFactory


def test_non_flying_pokemon_is_grounded_by_default():
    """
    验证最小 grounded 模型在没有显式覆盖时，会把非飞行属性宝可梦视为 grounded。
    这个判断是电气、精神、青草、薄雾场地伤害修正能否生效的共同前置条件；
    当前测试不引入重力、铁球、击落等复杂战斗状态，确保第一版接口保持纯净且易于后续扩展。
    """
    assert is_grounded(BattlePokemonFactory.scizor("max_atk_neutral")) is True


def test_flying_type_pokemon_is_airborne_by_default():
    """
    验证没有显式覆盖时，飞行属性会让宝可梦默认不受场地类伤害修正影响。
    测试通过替换既有战斗快照的属性来表达飞行状态，不引入完整战斗状态系统；
    这保护了本轮需求中的最小 airborne 判定，并为后续加入漂浮、重力等机制留下单一入口。
    """
    pokemon = replace(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        types=(Type.FLYING,),
    )

    assert is_grounded(pokemon) is False


def test_grounding_override_can_force_flying_type_grounded():
    """
    验证 grounding_state 显式覆盖优先于属性默认判断，允许测试和未来应用层表达被击落或重力等状态。
    即使宝可梦拥有飞行属性，只要快照标记为 GROUNDED，is_grounded 就必须返回 True；
    该设计避免为了第一版场地伤害修正引入完整多回合状态系统，同时保持扩展口稳定。
    """
    pokemon = replace(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        types=(Type.FLYING,),
        grounding_state=GroundingState.GROUNDED,
    )

    assert is_grounded(pokemon) is True


def test_grounding_override_can_force_non_flying_type_airborne():
    """
    验证 grounding_state 也可以把默认 grounded 的非飞行属性宝可梦显式标记为 AIRBORNE。
    这个能力让场地测试可以稳定表达不接地的攻击方或防守方，不需要依赖道具、特性或完整状态模拟；
    后续机制只要写入同一个覆盖字段，就能复用现有场地伤害判定。
    """
    pokemon = replace(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        grounding_state=GroundingState.AIRBORNE,
    )

    assert is_grounded(pokemon) is False
