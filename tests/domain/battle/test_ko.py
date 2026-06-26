import pytest

from pokeop.domain.battle.ko import estimate_ko_chance


def test_two_hit_ko_chance_uses_all_damage_roll_pairs():
    """
    验证二击击杀概率按全部 16x16 个随机伤害组合计算。
    输入使用满攻巨钳螳螂子弹拳打 252 HP 仙子伊布的 16 档伤害，
    仙子伊布 HP=202；单次伤害不可能一击击杀，但两次伤害有 246/256 的组合能击杀。
    同时验证这不是稳定二击，因为最低伤害 99+99 仍然小于 202。
    """
    rolls = (99, 100, 101, 102, 104, 105, 106, 107, 108, 109, 111, 112, 113, 114, 115, 117)

    result = estimate_ko_chance(rolls=rolls, defender_hp=202)

    assert result.ohko_chance == 0
    assert result.two_hit_ko_chance == pytest.approx(246 / 256)
    assert not result.guaranteed_ohko
    assert not result.guaranteed_2hko


def test_guaranteed_two_hit_ko_when_minimum_two_rolls_are_enough():
    """
    验证最低伤害连续两次已经超过 HP 时会判定为稳定二击击杀。
    这里给定伤害档位 109、110、129，防守方 HP=202，
    因为最低组合 109+109 已经足够击杀，所以 two_hit_ko_chance 应为 1。
    """
    result = estimate_ko_chance(rolls=(109, 110, 129), defender_hp=202)

    assert result.two_hit_ko_chance == 1
    assert result.guaranteed_2hko
