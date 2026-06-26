from pokeop.application.presets import stat_profiles
from pokeop.application.use_cases.calculate_move_damage import (
    CalculateMoveDamageCommand,
    CalculateMoveDamageUseCase,
    MoveBattleSnapshot,
    PokemonBattleSnapshot,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


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


def test_calculate_move_damage_use_case_with_snapshot_inputs():
    """
    用纯快照输入跑一次 application 层伤害计算用例。
    场景是 50 级满攻巨钳螳螂使用钢系物理招式子弹拳攻击 252 HP 仙子伊布。
    这里验证用例会先算出攻击方 Atk=182、防守方 HP=202/Def=85，
    再返回 99-117 的伤害区间、百分比、期望伤害、非一击且有概率二击的结果。
    """
    command = CalculateMoveDamageCommand(
        attacker=PokemonBattleSnapshot(
            name="scizor",
            level=LEVEL,
            types=(Type.BUG, Type.STEEL),
            stat_profile=stat_profiles.max_atk_neutral(SCIZOR_BASE),
        ),
        defender=PokemonBattleSnapshot(
            name="sylveon",
            level=LEVEL,
            types=(Type.FAIRY,),
            stat_profile=stat_profiles.max_hp(SYLVEON_BASE),
        ),
        move=MoveBattleSnapshot(
            name="bullet-punch",
            type=Type.STEEL,
            category=MoveCategory.PHYSICAL,
            power=40,
        ),
    )

    result = CalculateMoveDamageUseCase().execute(command)

    assert result.attacker_stats.attack == 182
    assert result.defender_stats.hp == 202
    assert result.defender_stats.defense == 85
    assert (result.damage.min_damage, result.damage.max_damage) == (99, 117)
    assert result.damage.min_percent == 99 / 202 * 100
    assert result.damage.max_percent == 117 / 202 * 100
    assert result.damage.expected_damage == sum(result.damage.rolls) / 16
    assert result.damage.expected_percent == result.damage.expected_damage / 202 * 100
    assert result.ko_chance.ohko_chance == 0
    assert 0 < result.ko_chance.two_hit_ko_chance < 1
    assert {modifier.key for modifier in result.damage.applied_modifiers} == {
        "stab",
        "type_effectiveness",
        "random",
    }
