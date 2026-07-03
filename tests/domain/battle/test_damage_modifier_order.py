from __future__ import annotations

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import (
    BattleMoveFactory,
    BattlePokemonFactory,
    damage_context,
)


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _modifier_keys(result):
    return [modifier.key for modifier in result.applied_modifiers]


def test_technician_is_recorded_before_stab_as_base_power_modifier():
    """
    验证技术高手的修正顺序处于 STAB 与属性克制之前，并且阶段明确为 base power。
    这个测试不只比较最终伤害，而是检查 applied_modifiers 的顺序与 stage，防止后续实现为了省事把所有倍率
    混入 final damage；如果 Technician 被错误放在随机档位前的最终倍率中，本测试会通过阶段断言失败。
    """
    attacker = BattlePokemonFactory.with_ability(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageAbility.TECHNICIAN,
    )
    defender = BattlePokemonFactory.sylveon("max_hp")
    result = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.bullet_punch(),
        )
    )

    keys = _modifier_keys(result)
    technician = _modifiers_by_key(result)["ability:technician"]
    assert technician.stage is ModifierStage.BASE_POWER
    assert keys.index("ability:technician") < keys.index("stab")
    assert technician.stage is not ModifierStage.FINAL_DAMAGE


def test_choice_band_and_eviolite_are_stat_stage_modifiers_before_base_damage_trace():
    """
    验证讲究头带与进化奇石都进入攻防能力值阶段，而不是作为最终伤害倍率附加。
    攻击方携带 Choice Band，防守方携带可生效的 Eviolite，二者应分别记录 attack stat 与 defense stat；
    两个修正都必须出现在 STAB 之前，说明它们先改变基础伤害公式输入，再由后续链路处理属性与随机档位。
    """
    attacker = BattlePokemonFactory.with_item(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageItem.CHOICE_BAND,
    )
    defender = BattlePokemonFactory.with_item(
        BattlePokemonFactory.sylveon("max_hp"),
        DamageItem.EVIOLITE,
        can_evolve=True,
    )
    result = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.bullet_punch(),
        )
    )

    modifiers = _modifiers_by_key(result)
    keys = _modifier_keys(result)
    assert (
        modifiers["item:choice_band"].stage is ModifierStage.ATTACK_STAT
    )  # 为什么要加"item:" 这种前缀？为什么不用明确的成员变量 + 枚举类型来区分？为什么要用字符串 key 来做这个？这很容易出错。尽管python是脚本语言，请按照编译语言的标准去设计类型系统，避免字符串 key 这种容易出错的设计。
    assert modifiers["item:eviolite"].stage is ModifierStage.DEFENSE_STAT
    assert keys.index("item:choice_band") < keys.index("stab")
    assert keys.index("item:eviolite") < keys.index("stab")
    assert modifiers["item:choice_band"].stage is not ModifierStage.FINAL_DAMAGE
    assert modifiers["item:eviolite"].stage is not ModifierStage.FINAL_DAMAGE


def test_filter_and_expert_belt_are_applied_after_type_effectiveness():
    """
    验证依赖效果拔群判断的过滤与达人带，都在 type_effectiveness 记录之后才进入 final damage 阶段。
    场景中钢系子弹拳攻击妖精目标，攻击方携带 Expert Belt，防守方拥有 Filter；
    trace 顺序必须先出现 type_effectiveness，再出现 ability:filter 与 item:expert_belt，保护二者读取克制结果。
    """
    attacker = BattlePokemonFactory.with_item(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageItem.EXPERT_BELT,
    )
    defender = BattlePokemonFactory.with_ability(
        BattlePokemonFactory.sylveon("max_hp"),
        DamageAbility.FILTER,
    )
    result = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.bullet_punch(),
        )
    )

    modifiers = _modifiers_by_key(result)
    keys = _modifier_keys(result)
    assert modifiers["type_effectiveness"].multiplier == 2.0
    assert modifiers["ability:filter"].stage is ModifierStage.FINAL_DAMAGE
    assert modifiers["item:expert_belt"].stage is ModifierStage.FINAL_DAMAGE
    assert keys.index("type_effectiveness") < keys.index("ability:filter")
    assert keys.index("type_effectiveness") < keys.index("item:expert_belt")


def test_weather_terrain_and_life_orb_are_final_damage_sources():
    """
    验证天气、场地与生命宝珠可以同时作为 final damage 阶段来源被记录，而不会覆盖彼此 trace。
    攻击方携带 Life Orb，在雨天与电气场地下使用电系招式；雨天对电系不生效，电气场地和生命宝珠应生效；
    另用晴天火系招式验证天气 final damage 记录，确保三个来源都有清晰 stage 和 key。
    """
    attacker = BattlePokemonFactory.with_item(
        BattlePokemonFactory.scizor("max_atk_neutral"),
        DamageItem.LIFE_ORB,
    )
    defender = BattlePokemonFactory.sylveon("max_hp")
    electric_result = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.special(
                name="thunderbolt", move_type=Type.ELECTRIC, power=90
            ),
            environment=BattleEnvironment(
                weather=Weather.RAIN, terrain=Terrain.ELECTRIC
            ),
        )
    )
    sunny_result = calculate_damage_rolls(
        damage_context(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.special(
                name="flamethrower", move_type=Type.FIRE, power=90
            ),
            environment=BattleEnvironment(weather=Weather.HARSH_SUNLIGHT),
        )
    )

    electric_modifiers = _modifiers_by_key(electric_result)
    sunny_modifiers = _modifiers_by_key(sunny_result)
    assert (
        electric_modifiers["terrain:electric_terrain"].stage
        is ModifierStage.FINAL_DAMAGE
    )
    assert electric_modifiers["item:life_orb"].stage is ModifierStage.FINAL_DAMAGE
    assert "weather:rain" not in electric_modifiers
    assert sunny_modifiers["weather:harsh_sunlight"].stage is ModifierStage.FINAL_DAMAGE
    assert sunny_modifiers["item:life_orb"].stage is ModifierStage.FINAL_DAMAGE
