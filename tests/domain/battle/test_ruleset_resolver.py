from __future__ import annotations

import pytest

from pokeop.domain.battle.rulesets.errors import (
    UnknownGenerationError,
    UnknownVersionGroupError,
)
from pokeop.domain.battle.rulesets.resolver import (
    VERSION_GROUP_TO_GENERATION,
    resolve_ruleset_by_generation,
    resolve_ruleset_by_version_group,
)


def test_resolve_ruleset_by_generation_five_returns_legacy_gen5_policy():
    """
    验证 generation resolver 在第五世代返回当前粗粒度 legacy damage policy，而不是错误回退到现代规则。
    该 profile 代表本阶段 Gen1 到 Gen5 共享的旧规则形状：没有现代雪天冰系物防增强，也没有现代一点三场地倍率；
    测试保护 resolver 的入口语义，确保 application 未来按 generation_id 选择规则时不会默默套用 Gen9 行为。
    """
    ruleset = resolve_ruleset_by_generation(5)

    assert ruleset.generation_id == 5
    assert ruleset.version_group_id is None
    assert ruleset.damage_policy.terrain_boost_multiplier == 1.0
    assert ruleset.damage_policy.snow_ice_defense_multiplier is None
    assert ruleset.damage_policy.hail_ice_defense_multiplier is None


def test_resolve_ruleset_by_generation_six_and_seven_returns_terrain_legacy_policy():
    """
    验证第六、第七世代 resolver 返回同一类 Gen6/Gen7 风格 policy，特别是场地增伤仍为一点五。
    这不是完整官方全世代 ruleset，而是当前 DamagePolicy 粒度下的规则 profile；
    测试明确锁住 terrain-era legacy 与 modern profile 的差异，避免后续把所有 generation 都导向现代 policy。
    """
    gen6 = resolve_ruleset_by_generation(6)
    gen7 = resolve_ruleset_by_generation(7)

    assert gen6.generation_id == 6
    assert gen7.generation_id == 7
    assert gen6.damage_policy.terrain_boost_multiplier == 1.5
    assert gen7.damage_policy.terrain_boost_multiplier == 1.5
    assert gen6.damage_policy.snow_ice_defense_multiplier is None
    assert gen7.damage_policy.snow_ice_defense_multiplier is None


def test_resolve_ruleset_by_generation_eight_and_nine_returns_modern_policy():
    """
    验证第八、第九世代 resolver 返回现代 damage policy，当前现代 profile 使用一点三场地增伤。
    这个测试保护默认现代规则与 resolver 输出一致：显式解析 generation_id 后得到的 policy，
    应与不传 ruleset 时伤害链采用的现代规则同源，后续 application 通过 resolver 接入不会改变当前默认行为。
    """
    gen8 = resolve_ruleset_by_generation(8)
    gen9 = resolve_ruleset_by_generation(9)

    assert gen8.generation_id == 8
    assert gen9.generation_id == 9
    assert gen8.damage_policy.terrain_boost_multiplier == 1.3
    assert gen9.damage_policy.terrain_boost_multiplier == 1.3
    assert gen8.damage_policy.snow_ice_defense_multiplier == 1.5
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
    assert colosseum.damage_policy.snow_ice_defense_multiplier is None


def test_resolve_ruleset_by_version_group_returns_gen6_and_gen9_profiles():
    """
    验证 version_group resolver 能覆盖第六世代与第九世代的代表编号，并返回对应 policy 风格。
    当前 CSV 中 x-y 是 id 15，omega-ruby-alpha-sapphire 是 id 16，scarlet-violet 是 id 25，
    legends-za 与 mega-dimension 是 id 30 和 31；测试锁住这些静态映射，避免 unknown 或 modern fallback 掩盖错误。
    """
    xy = resolve_ruleset_by_version_group(15)
    oras = resolve_ruleset_by_version_group(16)
    scarlet_violet = resolve_ruleset_by_version_group(25)
    legends_za = resolve_ruleset_by_version_group(30)
    mega_dimension = resolve_ruleset_by_version_group(31)

    assert xy.generation_id == 6
    assert oras.generation_id == 6
    assert xy.damage_policy.terrain_boost_multiplier == 1.5
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
