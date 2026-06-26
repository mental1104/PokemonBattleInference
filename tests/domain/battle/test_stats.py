from pokeop.domain.battle.stats import (
    NatureModifier,
    StatProfile,
    StatValues,
    calculate_actual_stats,
)
from pokeop.domain.models.pokemon_fields import StatField


LEVEL = 50

SCIZOR_BASE = StatValues(
    hp=70,
    attack=130,
    defense=100,
    special_attack=55,
    special_defense=80,
    speed=65,
)
SYLVEON_BASE = StatValues(
    hp=95,
    attack=65,
    defense=65,
    special_attack=110,
    special_defense=130,
    speed=60,
)


def test_scizor_attack_profiles():
    """
    验证 50 级巨钳螳螂的两个攻击配置能力值。
    同样使用 252 Atk 和默认 31 IV，极攻配置带攻击性格 1.1 修正，
    应得到 Atk=200；满攻配置不带性格修正，应得到 Atk=182。
    这个测试锁住现代宝可梦非 HP 能力值公式中的 floor 位置。
    """
    max_attack_plus = StatProfile(
        base_stats=SCIZOR_BASE,
        evs=StatValues(attack=252),
        nature_modifier=NatureModifier.increase(StatField.ATTACK),
    )
    max_attack_neutral = StatProfile(
        base_stats=SCIZOR_BASE,
        evs=StatValues(attack=252),
    )

    assert calculate_actual_stats(max_attack_plus, level=LEVEL).attack == 200
    assert calculate_actual_stats(max_attack_neutral, level=LEVEL).attack == 182


def test_sylveon_defense_profiles():
    """
    验证 50 级仙子伊布三种防守配置的 HP 和物防能力值。
    252 HP / 0 Def 应得到 HP=202、Def=85；
    252 HP / 252 Def 应得到 HP=202、Def=117；
    252 HP / 252 Def+ 应再应用防御性格 1.1 修正，得到 Def=128。
    """
    max_hp = StatProfile(
        base_stats=SYLVEON_BASE,
        evs=StatValues(hp=252),
    )
    max_hp_def = StatProfile(
        base_stats=SYLVEON_BASE,
        evs=StatValues(hp=252, defense=252),
    )
    max_hp_def_plus = StatProfile(
        base_stats=SYLVEON_BASE,
        evs=StatValues(hp=252, defense=252),
        nature_modifier=NatureModifier.increase(StatField.DEFENSE),
    )

    max_hp_stats = calculate_actual_stats(max_hp, level=LEVEL)
    max_hp_def_stats = calculate_actual_stats(max_hp_def, level=LEVEL)
    max_hp_def_plus_stats = calculate_actual_stats(max_hp_def_plus, level=LEVEL)

    assert max_hp_stats.hp == 202
    assert max_hp_stats.defense == 85
    assert max_hp_def_stats.hp == 202
    assert max_hp_def_stats.defense == 117
    assert max_hp_def_plus_stats.hp == 202
    assert max_hp_def_plus_stats.defense == 128
