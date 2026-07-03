from fractions import Fraction

from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.status.modifiers import (
    apply_burn_physical_damage_modifier,
    apply_paralysis_speed_modifier,
)
from tests.domain.battle.helpers import CombatantStatusFactory, MoveProfileFactory


def _ruleset(profile: BattleRulesetProfile):
    return profile.build()


def test_paralysis_speed_modifier_uses_generation_specific_multiplier():
    """
    验证麻痹速度修正会读取当前规则集中的代际倍率，而不是在 modifier 中写死固定数值。本用例对同一个基础速度
    分别套用 Gen6、Gen7 和 Gen9 规则集，断言 Gen6 使用四分之一，Gen7 与 Gen9 使用二分之一。这个测试说明
    代际差异应该收敛在 ruleset policy 中，后续补第一到第九世代规则时只扩展配置，不改行动顺序计算入口。
    """
    status = CombatantStatusFactory.paralyzed()

    assert apply_paralysis_speed_modifier(100, status, _ruleset(BattleRulesetProfile.GEN6)) == 25
    assert apply_paralysis_speed_modifier(100, status, _ruleset(BattleRulesetProfile.GEN7)) == 50
    assert apply_paralysis_speed_modifier(100, status, _ruleset(BattleRulesetProfile.GEN9)) == 50


def test_burn_physical_damage_modifier_only_affects_physical_moves():
    """
    验证烧伤物理伤害修正只作用于物理招式，不影响特殊招式和变化招式。本用例让攻击方处于烧伤状态，分别传入
    物理、特殊和变化三类最小招式模型，并断言只有物理分支把倍率变为二分之一。这个测试保护后续接入完整伤害链
    时的边界：烧伤 modifier 可以作为独立节点加入公式，但不能污染招式分类判断或影响非物理招式。
    """
    burned = CombatantStatusFactory.burned()

    assert apply_burn_physical_damage_modifier(
        Fraction(1, 1),
        burned,
        _ruleset(BattleRulesetProfile.GEN9),
        MoveProfileFactory.physical(),
    ) == Fraction(1, 2)
    assert apply_burn_physical_damage_modifier(
        Fraction(1, 1),
        burned,
        _ruleset(BattleRulesetProfile.GEN9),
        MoveProfileFactory.special(),
    ) == Fraction(1, 1)
    assert apply_burn_physical_damage_modifier(
        Fraction(1, 1),
        burned,
        _ruleset(BattleRulesetProfile.GEN9),
        MoveProfileFactory.status(),
    ) == Fraction(1, 1)
