from tests.domain.battle.helpers import BattlePokemonFactory


def test_scizor_attack_profiles():
    """
    验证 50 级巨钳螳螂的两个攻击配置能力值。
    同样使用 252 Atk 和默认 31 IV，极攻配置带攻击性格 1.1 修正，
    应得到 Atk=200；满攻配置不带性格修正，应得到 Atk=182。
    这个测试锁住现代宝可梦非 HP 能力值公式中的 floor 位置。
    """
    max_attack_plus = BattlePokemonFactory.scizor_stats("max_atk_plus")
    max_attack_neutral = BattlePokemonFactory.scizor_stats("max_atk_neutral")

    assert max_attack_plus.attack == 200
    assert max_attack_neutral.attack == 182


def test_sylveon_defense_profiles():
    """
    验证 50 级仙子伊布三种防守配置的 HP 和物防能力值。
    252 HP / 0 Def 应得到 HP=202、Def=85；
    252 HP / 252 Def 应得到 HP=202、Def=117；
    252 HP / 252 Def+ 应再应用防御性格 1.1 修正，得到 Def=128。
    """
    max_hp_stats = BattlePokemonFactory.sylveon_stats("max_hp")
    max_hp_def_stats = BattlePokemonFactory.sylveon_stats("max_hp_def")
    max_hp_def_plus_stats = BattlePokemonFactory.sylveon_stats("max_hp_def_plus")

    assert max_hp_stats.hp == 202
    assert max_hp_stats.defense == 85
    assert max_hp_def_stats.hp == 202
    assert max_hp_def_stats.defense == 117
    assert max_hp_def_plus_stats.hp == 202
    assert max_hp_def_plus_stats.defense == 128
