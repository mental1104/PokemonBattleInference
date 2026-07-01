import pytest

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.modifiers import (
    AppliedModifier,
    BaseDamageModifier,
    DamageCalculationState,
    DamageModifierChain,
    RandomRollModifier,
    build_damage_chain,
)
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


@pytest.mark.parametrize(
    ("attacker_key", "defender_key", "expected_range"),
    [
        ("max_atk_plus", "max_hp", (109, 129)),
        ("max_atk_plus", "max_hp_def", (81, 96)),
        ("max_atk_plus", "max_hp_def_plus", (73, 87)),
        ("max_atk_neutral", "max_hp", (99, 117)),
        ("max_atk_neutral", "max_hp_def", (73, 87)),
        ("max_atk_neutral", "max_hp_def_plus", (68, 81)),
    ],
)
def test_scizor_bullet_punch_sylveon_damage_ranges(
    attacker_key,
    defender_key,
    expected_range,
):
    """
    验证巨钳螳螂子弹拳打仙子伊布时六组攻防配置的精确伤害区间。
    攻击方覆盖极攻 Atk+ 和满攻 Atk neutral，防守方覆盖 252HP/0Def、
    252HP/252Def、252HP/252Def+ 三种配置。每组都会走完整伤害链：
    基础伤害、STAB、钢打妖精 2 倍克制和 16 档随机伤害。
    """
    result = calculate_damage_rolls(
        attacker=BattlePokemonFactory.scizor(attacker_key),
        defender=BattlePokemonFactory.sylveon(defender_key),
        move=BattleMoveFactory.bullet_punch(),
    )

    assert (result.min_damage, result.max_damage) == expected_range
    assert len(result.rolls) == 16


def test_applied_modifiers_include_stab_type_and_random_without_ability():
    """
    验证本阶段伤害链只应用并记录核心修正项。
    场景是极攻巨钳螳螂使用本系钢系子弹拳攻击妖精系仙子伊布，
    因此应记录 STAB=1.5、type_effectiveness=2.0、random=0.85-1.00。
    当前阶段明确不计算 Technician，所以不能出现 ability 修正。
    """
    result = calculate_damage_rolls(
        attacker=BattlePokemonFactory.scizor("max_atk_plus"),
        defender=BattlePokemonFactory.sylveon("max_hp"),
        move=BattleMoveFactory.bullet_punch(),
    )

    modifiers = {modifier.key: modifier for modifier in result.applied_modifiers}
    assert modifiers["stab"].multiplier == 1.5
    assert modifiers["type_effectiveness"].multiplier == 2.0
    assert modifiers["random"].min_multiplier == 0.85
    assert modifiers["random"].max_multiplier == 1.0
    assert "ability" not in modifiers


def test_damage_chain_allows_new_modifier_links_before_random_rolls():
    """
    验证伤害计算使用责任链后可以插入新的扩展节点。
    测试里临时定义一个 TestAbilityModifier，把基础伤害乘以 2，
    并把它放在 BaseDamageModifier 和 RandomRollModifier 之间。
    这模拟以后接入 Technician、生命宝珠、天气等修正时，只新增链节点即可。
    """
    class TestAbilityModifier(DamageModifierChain):
        """测试专用链节点：模拟一个把当前伤害倍率翻倍的特性修正。"""

        def apply(self, state: DamageCalculationState) -> DamageCalculationState:
            """把总倍率乘以 2，并记录 test_ability 修正方便断言链路顺序。"""
            return state.with_multiplier(
                2.0,
                AppliedModifier("test_ability", multiplier=2.0),
            )

    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    chain = build_damage_chain(
        (
            BaseDamageModifier(),
            TestAbilityModifier(),
            RandomRollModifier((1.0,)),
        )
    )

    state = chain.handle(
        DamageCalculationState(
            attacker=attacker,
            defender=defender,
            move=BattleMoveFactory.bullet_punch(),
        )
    )

    assert state.rolls == (78,)
    assert [modifier.key for modifier in state.applied_modifiers] == [
        "test_ability",
        "random",
    ]
