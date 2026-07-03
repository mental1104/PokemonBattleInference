from __future__ import annotations

import pytest

from pokeop.domain.battle.rulesets.errors import (
    UnknownGenerationError,
    UnknownVersionGroupError,
)
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.rulesets.resolver import (
    VERSION_GROUP_TO_GENERATION,
    resolve_ruleset_by_generation,
    resolve_ruleset_by_version_group,
)


def test_ruleset_profile_enum_keeps_one_member_per_generation():
    """
    验证 ruleset profile 枚举按第一到第九世代逐一建模，而不是把当前字段暂时相同的世代合并成区间桶。
    这个测试直接检查 from_generation_id、默认 build 结果和枚举值顺序，要求每个 generation_id 都有自己的 profile；
    它保护后续补 Gen1、Gen2、Gen4 或 Gen5 独有机制时，可以只扩展对应枚举分支，不必先拆掉错误的公共分类。
    """
    expected_profiles = (
        BattleRulesetProfile.GEN1,
        BattleRulesetProfile.GEN2,
        BattleRulesetProfile.GEN3,
        BattleRulesetProfile.GEN4,
        BattleRulesetProfile.GEN5,
        BattleRulesetProfile.GEN6,
        BattleRulesetProfile.GEN7,
        BattleRulesetProfile.GEN8,
        BattleRulesetProfile.GEN9,
    )

    assert tuple(BattleRulesetProfile) == expected_profiles
    for generation_id, profile in enumerate(expected_profiles, start=1):
        ruleset = profile.build()

        assert BattleRulesetProfile.from_generation_id(generation_id) is profile
        assert ruleset.generation_id == generation_id
        assert ruleset.ruleset_id == f"gen{generation_id}"

    with pytest.raises(ValueError, match="does not belong to profile gen4"):
        BattleRulesetProfile.GEN4.build(generation_id=5)


def test_resolve_ruleset_by_generation_three_disables_weather_defense_boosts():
    """
    验证第三世代以及更早的 ruleset 不会启用沙暴岩石特防或雪天冰系物防这类后续世代规则。
    该场景直接通过 generation resolver 获取 Gen3 profile，断言场地倍率仍是旧入口的一点零，同时两个天气防御倍率都是 None；
    测试保护 application 未来按 generation_id 选择规则时，不会把 Gen4 沙暴或 Gen9 雪天行为提前套到旧世代。
    """
    ruleset = resolve_ruleset_by_generation(3)

    assert ruleset.generation_id == 3
    assert ruleset.version_group_id is None
    assert ruleset.damage_policy.terrain_boost_multiplier == 1.0
    assert ruleset.damage_policy.sandstorm_rock_spdef_multiplier is None
    assert ruleset.damage_policy.snow_ice_defense_multiplier is None
    assert ruleset.damage_policy.hail_ice_defense_multiplier is None


def test_resolve_ruleset_by_generation_four_and_five_enable_sandstorm_only():
    """
    验证第四、第五世代 resolver 会分别返回具体世代 ruleset，并在当前已建模字段上都启用沙暴岩石特防。
    测试同时解析 Gen4 与 Gen5，只比较 DamagePolicy 目前覆盖的天气和场地字段，不把二者声明为完整等价；
    这样既保护沙暴从 Gen4 开始生效的断点，也避免第五世代被误判为拥有 Gen9 的 Weather.SNOW 防御修正。
    """
    gen4 = resolve_ruleset_by_generation(4)
    gen5 = resolve_ruleset_by_generation(5)

    assert gen4.generation_id == 4
    assert gen5.generation_id == 5
    assert gen4.version_group_id is None
    assert gen5.version_group_id is None
    assert gen4.damage_policy.terrain_boost_multiplier == 1.0
    assert gen5.damage_policy.terrain_boost_multiplier == 1.0
    assert gen4.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen5.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen4.damage_policy.snow_ice_defense_multiplier is None
    assert gen5.damage_policy.snow_ice_defense_multiplier is None
    assert gen4.damage_policy.hail_ice_defense_multiplier is None
    assert gen5.damage_policy.hail_ice_defense_multiplier is None


def test_resolve_ruleset_by_generation_six_and_seven_returns_terrain_legacy_policy():
    """
    验证第六、第七世代 resolver 会分别返回具体世代 ruleset，并在当前已建模字段上都使用一点五场地增伤。
    这不是完整官方全世代 ruleset，只是当前 DamagePolicy 粒度下对场地倍率字段的约束；
    测试明确锁住 terrain-era legacy 与 modern profile 的差异，避免后续把所有 generation 都导向现代 policy。
    """
    gen6 = resolve_ruleset_by_generation(6)
    gen7 = resolve_ruleset_by_generation(7)

    assert gen6.generation_id == 6
    assert gen7.generation_id == 7
    assert gen6.damage_policy.terrain_boost_multiplier == 1.5
    assert gen7.damage_policy.terrain_boost_multiplier == 1.5
    assert gen6.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen7.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen6.damage_policy.snow_ice_defense_multiplier is None
    assert gen7.damage_policy.snow_ice_defense_multiplier is None


def test_resolve_ruleset_by_generation_eight_and_nine_split_snow_defense_policy():
    """
    验证第八、第九世代 resolver 虽然都使用现代一点三场地倍率，但只有第九世代启用雪天冰系物防增强。
    该场景直接比较 Gen8 与 Gen9 的 damage_policy 字段，确保 Sword/Shield 等 Gen8 规则不会因为 modern 入口而提前获得雪天加防；
    同时 Gen9 仍保持默认现代规则，供不显式传 ruleset 的伤害链作为当前默认行为。
    """
    gen8 = resolve_ruleset_by_generation(8)
    gen9 = resolve_ruleset_by_generation(9)

    assert gen8.generation_id == 8
    assert gen9.generation_id == 9
    assert gen8.damage_policy.terrain_boost_multiplier == 1.3
    assert gen9.damage_policy.terrain_boost_multiplier == 1.3
    assert gen8.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen9.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert gen8.damage_policy.snow_ice_defense_multiplier is None
    assert gen9.damage_policy.snow_ice_defense_multiplier == 1.5


def test_resolve_ruleset_by_version_group_uses_repository_csv_mapping_for_gen5():
    """
    验证 version_group resolver 使用仓库当前 version_groups.csv 对齐的静态映射，而不是提示词里的旧示例编号。
    当前 CSV 中 black-white 是 id 11，black-2-white-2 是 id 14，二者都映射到第五世代 legacy policy；
    测试同时断言 version_group_id 会写入返回的 BattleRuleset，方便未来解释和 application 追踪规则来源。
    """
    black_white = resolve_ruleset_by_version_group(11)
    black_2_white_2 = resolve_ruleset_by_version_group(14)

    assert black_white.generation_id == 5
    assert black_2_white_2.generation_id == 5
    assert black_white.version_group_id == 11
    assert black_2_white_2.version_group_id == 14
    assert black_white.damage_policy.terrain_boost_multiplier == 1.0
    assert black_white.damage_policy.sandstorm_rock_spdef_multiplier == 1.5
    assert black_2_white_2.damage_policy.snow_ice_defense_multiplier is None


def test_resolve_ruleset_by_version_group_uses_csv_mapping_for_non_linear_ids():
    """
    验证 resolver 明确遵循仓库 CSV 的非线性编号：version_group_id 12 是 colosseum，对应第三世代。
    这个测试防止开发者按旧版 PokeAPI 常识把 id 12 误认为 black-2-white-2；
    生产代码仍不读取 CSV，但静态表必须反映当前资产文件，否则 application 未来按 version_group 选规则会错位。
    """
    colosseum = resolve_ruleset_by_version_group(12)

    assert VERSION_GROUP_TO_GENERATION[12] == 3
    assert colosseum.generation_id == 3
    assert colosseum.version_group_id == 12
    assert colosseum.damage_policy.sandstorm_rock_spdef_multiplier is None
    assert colosseum.damage_policy.snow_ice_defense_multiplier is None


def test_resolve_ruleset_by_version_group_returns_gen6_gen8_and_gen9_profiles():
    """
    验证 version_group resolver 能覆盖第六、第八与第九世代代表编号，并返回对应 policy 风格。
    当前 CSV 中 x-y 是 id 15，omega-ruby-alpha-sapphire 是 id 16，sword-shield 是 id 20，scarlet-violet 是 id 25，
    legends-za 与 mega-dimension 是 id 30 和 31；测试锁住静态映射，避免 unknown 或 modern fallback 掩盖世代差异。
    """
    xy = resolve_ruleset_by_version_group(15)
    oras = resolve_ruleset_by_version_group(16)
    sword_shield = resolve_ruleset_by_version_group(20)
    scarlet_violet = resolve_ruleset_by_version_group(25)
    legends_za = resolve_ruleset_by_version_group(30)
    mega_dimension = resolve_ruleset_by_version_group(31)

    assert xy.generation_id == 6
    assert oras.generation_id == 6
    assert xy.damage_policy.terrain_boost_multiplier == 1.5
    assert sword_shield.generation_id == 8
    assert sword_shield.damage_policy.terrain_boost_multiplier == 1.3
    assert sword_shield.damage_policy.snow_ice_defense_multiplier is None
    assert scarlet_violet.generation_id == 9
    assert legends_za.generation_id == 9
    assert mega_dimension.generation_id == 9
    assert scarlet_violet.damage_policy.terrain_boost_multiplier == 1.3
    assert legends_za.damage_policy.snow_ice_defense_multiplier == 1.5


def test_unknown_generation_and_version_group_raise_domain_errors():
    """
    验证未知 generation_id 与 version_group_id 都会显式失败，而不是静默回退到 modern ruleset。
    resolver 是 domain 规则 profile 入口，unknown id 通常表示调用方传错数据或静态映射需要更新；
    测试要求错误类型和错误信息都携带具体 id，方便 application 层未来捕获并输出可诊断问题。
    """
    with pytest.raises(UnknownGenerationError, match="Unknown generation_id: 999"):
        resolve_ruleset_by_generation(999)

    with pytest.raises(UnknownVersionGroupError, match="Unknown version_group_id: 999"):
        resolve_ruleset_by_version_group(999)
