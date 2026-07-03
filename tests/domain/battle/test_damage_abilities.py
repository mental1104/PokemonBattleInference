from __future__ import annotations

from dataclasses import replace

import pytest

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.models.types import Type
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def _ruleset(profile: BattleRulesetProfile):
    return profile.build()


class TestTechnician:
    def test_boosts_moves_with_power_sixty_or_less_at_base_power_stage(self):
        """
        验证技术高手只在招式基础威力不超过六十时生效，并且生效阶段是 base power。
        场景使用巨钳螳螂携带 Technician 使用四十威力子弹拳攻击同一防守方，对照组没有特性；
        伤害应提高，trace 应记录 ability:technician，保护该特性不会被错误实现成 final damage 倍率。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        technician = replace(attacker, ability="technician")
        defender = BattlePokemonFactory.sylveon("max_hp")
        move = BattleMoveFactory.bullet_punch()

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        boosted = calculate_damage_rolls(attacker=technician, defender=defender, move=move)

        assert boosted.max_damage > normal.max_damage
        modifier = _modifiers_by_key(boosted)["ability:technician"]
        assert modifier.multiplier == 1.5
        assert modifier.stage is ModifierStage.BASE_POWER

    def test_does_not_boost_moves_above_power_sixty(self):
        """
        验证技术高手不会影响基础威力六十一或以上的招式，并且未生效时不得在 trace 中伪造特性修正。
        攻击方、目标和招式除 ability 字段外完全一致，六十一威力钢系物理招式已经超过 Technician 阈值；
        两次计算的随机伤害档位应完全相同，applied_modifiers 中也不应出现 ability:technician。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        technician = replace(attacker, ability="technician")
        defender = BattlePokemonFactory.sylveon("max_hp")
        move = BattleMoveFactory.physical(name="steel-wing-like", move_type=Type.STEEL, power=61)

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=technician, defender=defender, move=move)

        assert unchanged.rolls == normal.rolls
        assert "ability:technician" not in _modifiers_by_key(unchanged)


class TestAdaptability:
    def test_replaces_stab_multiplier_with_two_times(self):
        """
        验证适应力通过 STAB 阶段改写本系加成倍率，而不是另加一个最终伤害倍率。
        攻击方使用本系钢系子弹拳时，普通 STAB 为一点五倍，Adaptability 应把 trace 中的 stab 倍率变成两倍；
        结果伤害高于普通攻击方，并且 stab 记录的 source 指向 ability:adaptability，便于解释生效来源。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        adaptability = replace(attacker, ability="adaptability")
        defender = BattlePokemonFactory.sylveon("max_hp")
        move = BattleMoveFactory.bullet_punch()

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        adapted = calculate_damage_rolls(attacker=adaptability, defender=defender, move=move)

        assert adapted.max_damage > normal.max_damage
        modifier = _modifiers_by_key(adapted)["stab"]
        assert modifier.multiplier == 2.0
        assert modifier.stage is ModifierStage.STAB
        assert modifier.source == "ability:adaptability"

    def test_does_not_replace_stab_for_non_stab_moves(self):
        """
        验证适应力只改写本系招式的 STAB 倍率，不能让非本系招式获得额外加成或错误来源。
        场景让巨钳螳螂携带 Adaptability 使用火系特殊招式攻击同一防守方，火系不属于攻击方属性；
        计算结果应与普通攻击方完全一致，stab trace 仍保持普通 no-op 记录且 source 不能指向 ability:adaptability。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        adaptability = replace(attacker, ability="adaptability")
        defender = BattlePokemonFactory.sylveon("max_hp")
        move = BattleMoveFactory.special(name="flamethrower", move_type=Type.FIRE, power=90)

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=adaptability, defender=defender, move=move)

        assert unchanged.rolls == normal.rolls
        modifier = _modifiers_by_key(unchanged)["stab"]
        assert modifier.multiplier == 1.0
        assert modifier.stage is ModifierStage.STAB
        assert modifier.source == "stab"


class TestSniper:
    def test_raises_modern_critical_multiplier_to_two_point_two_five(self):
        """
        验证狙击手作为攻击方特性会改写现代会心阶段的最终倍率，而不是另加 final damage 修正。
        场景使用拥有狙击手语义的刺龙王作为攻击方，现代规则下基础会心倍率为一点五，携带 Sniper 时应得到二点二五倍；
        trace 仍使用 critical_hit key 和 critical stage，但 source 必须指向 ability:sniper，方便解释输出说明倍率来源。
        """
        attacker = BattlePokemonFactory.kingdra("max_spa_neutral")
        sniper = replace(attacker, ability="sniper")
        defender = BattlePokemonFactory.scizor("max_atk_neutral")
        move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

        normal_critical = calculate_damage_rolls(
            attacker=attacker,
            defender=defender,
            move=move,
            ruleset=_ruleset(BattleRulesetProfile.GEN9),
            is_critical=True,
        )
        sniper_critical = calculate_damage_rolls(
            attacker=sniper,
            defender=defender,
            move=move,
            ruleset=_ruleset(BattleRulesetProfile.GEN9),
            is_critical=True,
        )

        modifier = _modifiers_by_key(sniper_critical)["critical_hit"]
        assert sniper_critical.max_damage > normal_critical.max_damage
        assert modifier.multiplier == 2.25
        assert modifier.stage is ModifierStage.CRITICAL
        assert modifier.source == "ability:sniper"

    def test_raises_legacy_critical_multiplier_to_three_times(self):
        """
        验证狙击手在第六世代以前会基于二倍基础会心倍率得到三倍最终倍率。
        场景显式传入 Gen5 ruleset，并使用该世代已存在的刺龙王分别以普通特性和 Sniper 特性打出会心；
        Sniper 结果必须高于普通会心，critical_hit trace 的 multiplier 必须是三点零，保护旧世代会心和特性叠加规则。
        """
        attacker = BattlePokemonFactory.kingdra("max_spa_neutral")
        sniper = replace(attacker, ability="sniper")
        defender = BattlePokemonFactory.scizor("max_atk_neutral")
        move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

        normal_critical = calculate_damage_rolls(
            attacker=attacker,
            defender=defender,
            move=move,
            ruleset=_ruleset(BattleRulesetProfile.GEN5),
            is_critical=True,
        )
        sniper_critical = calculate_damage_rolls(
            attacker=sniper,
            defender=defender,
            move=move,
            ruleset=_ruleset(BattleRulesetProfile.GEN5),
            is_critical=True,
        )

        modifier = _modifiers_by_key(sniper_critical)["critical_hit"]
        assert sniper_critical.max_damage > normal_critical.max_damage
        assert modifier.multiplier == 3.0
        assert modifier.stage is ModifierStage.CRITICAL
        assert modifier.source == "ability:sniper"

    def test_does_not_write_critical_trace_without_critical_hit(self):
        """
        验证狙击手只在会心一击场景参与 critical stage，不会让普通攻击凭空获得会心 trace。
        攻击方使用刺龙王并仅把 ability 字段改成 sniper，但不传 is_critical 标记，其他输入与普通伤害计算保持一致；
        结果应与无特性攻击方完全相同，applied_modifiers 中不能出现 critical_hit 或 ability:sniper 记录。
        """
        attacker = BattlePokemonFactory.kingdra("max_spa_neutral")
        sniper = replace(attacker, ability="sniper")
        defender = BattlePokemonFactory.scizor("max_atk_neutral")
        move = BattleMoveFactory.special(name="dragon-pulse", move_type=Type.DRAGON, power=85)

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=sniper, defender=defender, move=move)

        modifiers = _modifiers_by_key(unchanged)
        assert unchanged.rolls == normal.rolls
        assert "critical_hit" not in modifiers
        assert "ability:sniper" not in modifiers


class TestThickFat:
    @pytest.mark.parametrize("move_type", [Type.FIRE, Type.ICE])
    def test_reduces_incoming_fire_and_ice_damage_at_final_damage_stage(self, move_type):
        """
        验证厚脂肪作为防守方特性，会在 final damage 阶段削弱火系和冰系直接伤害。
        测试分别使用火系与冰系特殊招式攻击同一目标，对照组没有特性，厚脂肪组应得到更低伤害；
        每个结果都必须记录 ability:thick_fat，说明未知或未生效特性不会被混入该修正来源。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        defender = BattlePokemonFactory.sylveon("max_hp")
        thick_fat = replace(defender, ability="thick_fat")
        move = BattleMoveFactory.special(
            name=f"{move_type.name.lower()}-beam",
            move_type=move_type,
            power=90,
        )

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        reduced = calculate_damage_rolls(attacker=attacker, defender=thick_fat, move=move)

        assert reduced.max_damage < normal.max_damage
        modifier = _modifiers_by_key(reduced)["ability:thick_fat"]
        assert modifier.multiplier == 0.5
        assert modifier.stage is ModifierStage.FINAL_DAMAGE

    def test_does_not_reduce_other_move_types(self):
        """
        验证厚脂肪不会削弱火系和冰系之外的直接伤害，也不会在未触发场景留下误导性的 trace。
        场景使用钢系物理子弹拳攻击同一只仙子伊布，防守方只在 ability 字段上从无特性变为 thick_fat；
        两次计算的随机伤害档位必须完全一致，并且 applied_modifiers 中不能出现 ability:thick_fat。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        defender = BattlePokemonFactory.sylveon("max_hp")
        thick_fat = replace(defender, ability="thick_fat")
        move = BattleMoveFactory.bullet_punch()

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=attacker, defender=thick_fat, move=move)

        assert unchanged.rolls == normal.rolls
        assert "ability:thick_fat" not in _modifiers_by_key(unchanged)


class TestFilterLikeAbilities:
    @pytest.mark.parametrize("ability", ["filter", "solid_rock"])
    def test_reduce_super_effective_damage_at_final_damage_stage(self, ability):
        """
        验证过滤和坚硬岩石在防守方受到效果拔群招式时生效，并统一进入 final damage 阶段。
        该场景使用钢系子弹拳攻击妖精属性目标，属性相性已经由前序链路计算为效果拔群；
        携带对应特性的防守方应比无特性对照组受到更低伤害，trace 也必须记录具体 ability key 与阶段。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        defender = BattlePokemonFactory.sylveon("max_hp")
        protected = replace(defender, ability=ability)
        move = BattleMoveFactory.bullet_punch()

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        reduced = calculate_damage_rolls(attacker=attacker, defender=protected, move=move)

        ability_key = f"ability:{ability}"
        assert reduced.max_damage < normal.max_damage
        modifier = _modifiers_by_key(reduced)[ability_key]
        assert modifier.multiplier == 0.75
        assert modifier.stage is ModifierStage.FINAL_DAMAGE

    @pytest.mark.parametrize("ability", ["filter", "solid_rock"])
    def test_do_not_reduce_neutral_damage(self, ability):
        """
        验证过滤和坚硬岩石不会削弱普通效果招式，保护这组特性依赖 type_effectiveness 的触发边界。
        该场景使用普通系物理招式攻击同一妖精属性目标，除防守方 ability 外其余输入保持一致；
        两次计算的随机伤害档位应完全相同，applied_modifiers 中也不能出现对应 ability key。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        defender = BattlePokemonFactory.sylveon("max_hp")
        protected = replace(defender, ability=ability)
        move = BattleMoveFactory.physical(name="body-slam", move_type=Type.NORMAL, power=85)

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=attacker, defender=protected, move=move)

        ability_key = f"ability:{ability}"
        assert unchanged.rolls == normal.rolls
        assert ability_key not in _modifiers_by_key(unchanged)


class TestUnknownAbility:
    def test_unknown_ability_is_no_op_and_not_recorded(self):
        """
        验证当前未实现的特性会按 no-op 处理，避免第一版扩展框架因为陌生 ability 字符串直接中断伤害计算。
        攻击方带有一个不存在于 registry 的特性，其他输入与对照组完全相同；两次结果必须一致，
        trace 中也不能出现任何 ability:unknown 之类伪造记录，保证解释输出只描述实际生效机制。
        """
        attacker = BattlePokemonFactory.scizor("max_atk_neutral")
        unknown = replace(attacker, ability="future-unimplemented-ability")
        defender = BattlePokemonFactory.sylveon("max_hp")
        move = BattleMoveFactory.bullet_punch()

        normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
        unchanged = calculate_damage_rolls(attacker=unknown, defender=defender, move=move)

        assert unchanged.rolls == normal.rolls
        assert all(not modifier.key.startswith("ability:") for modifier in unchanged.applied_modifiers)
