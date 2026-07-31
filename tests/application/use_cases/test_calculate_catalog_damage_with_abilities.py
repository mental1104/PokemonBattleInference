from __future__ import annotations

import pytest

from pokeop.application.use_cases.calculate_catalog_damage import CalculatorInputError
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculateCatalogDamageWithAbilitiesCommand,
    CalculateCatalogDamageWithAbilitiesUseCase,
    CalculateCatalogPokemonWithAbilityCommand,
    CalculatorAbilityOption,
)
from pokeop.domain.battle.state import StatStages
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)


class FakeCalculatorAbilityRepository:
    """为 calculator 特性选择测试提供真实归属关系和混合实现状态。"""

    def list_pokemon_ability_options(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> tuple[CalculatorAbilityOption, ...]:
        """按测试 Pokémon 返回普通、隐藏和未实现特性。"""
        if ruleset_id != "pokemon-champion":
            return ()
        if pokemon_id == SCIZOR_ID:
            return (
                CalculatorAbilityOption(
                    ability_id=68,
                    identifier="swarm",
                    display_name="虫之预感",
                    slot=1,
                    is_hidden=False,
                    implemented=False,
                    effect_identifier=None,
                ),
                CalculatorAbilityOption(
                    ability_id=101,
                    identifier="technician",
                    display_name="技术高手",
                    slot=2,
                    is_hidden=False,
                    implemented=True,
                    effect_identifier="technician",
                ),
            )
        if pokemon_id == SYLVEON_ID:
            return (
                CalculatorAbilityOption(
                    ability_id=56,
                    identifier="cute-charm",
                    display_name="迷人之躯",
                    slot=1,
                    is_hidden=False,
                    implemented=False,
                    effect_identifier=None,
                ),
                CalculatorAbilityOption(
                    ability_id=182,
                    identifier="pixilate",
                    display_name="妖精皮肤",
                    slot=3,
                    is_hidden=True,
                    implemented=False,
                    effect_identifier=None,
                ),
            )
        return ()


def ability_command(
    *,
    attacker_ability: str = "swarm",
    defender_ability: str = "cute-charm",
    attacker_stages: StatStages = StatStages(),
    defender_stages: StatStages = StatStages(),
) -> CalculateCatalogDamageWithAbilitiesCommand:
    """创建巨钳螳螂使用子弹拳攻击仙子伊布的特性感知命令。

    Args:
        attacker_ability: 攻击方选择的合法或待校验特性 identifier。
        defender_ability: 防守方选择的合法或待校验特性 identifier。
        attacker_stages: 攻击方当前七项能力等级。
        defender_stages: 防守方当前七项能力等级。

    Returns:
        可交给 calculator application use case 的完整命令。
    """
    return CalculateCatalogDamageWithAbilitiesCommand(
        ruleset_id="pokemon-champion",
        attacker=CalculateCatalogPokemonWithAbilityCommand(
            pokemon_id=SCIZOR_ID,
            level=50,
            stat_preset="max_atk_neutral",
            ability_identifier=attacker_ability,
            stat_stages=attacker_stages,
        ),
        defender=CalculateCatalogPokemonWithAbilityCommand(
            pokemon_id=SYLVEON_ID,
            level=50,
            stat_preset="max_hp",
            ability_identifier=defender_ability,
            stat_stages=defender_stages,
        ),
        move_id=BULLET_PUNCH_ID,
    )


def ability_use_case() -> CalculateCatalogDamageWithAbilitiesUseCase:
    """创建同时注入 catalog 与特性 fake repository 的 use case。

    Returns:
        使用内存 fake repository、无需 PostgreSQL 的 calculator use case。
    """
    return CalculateCatalogDamageWithAbilitiesUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    )


def test_supported_ability_enters_domain_modifier_chain() -> None:
    """
    攻击方选择数据库归属合法且 domain 已实现的技术高手，防守方选择尚未实现但合法的迷人之躯。
    子弹拳固定威力为四十，技术高手应进入 domain 责任链并抬高原始九十九到一百一十七的伤害区间，
    modifier trace 必须出现 technician。该测试保护 API/application 不能只展示特性名称却在计算时丢弃选择，
    也保护实现状态标记与真正进入 BattlePokemon 的枚举值保持同源，避免 UI 显示已实现而后端仍按无特性计算。
    """
    result = ability_use_case().execute(
        ability_command(attacker_ability="technician")
    )

    assert result.damage.min_damage > 99
    assert any(
        str(getattr(modifier.key, "value", modifier.key)) == "ability:technician"
        for modifier in result.damage.applied_modifiers
    )


def test_unimplemented_ability_is_legal_but_degrades_to_no_effect() -> None:
    """
    双方都选择 PokeAPI 中真实归属、但当前 DamageAbility 尚未实现的特性时，请求仍然必须被接受，
    伤害结果保持无特性基线九十九到一百一十七，同时 warnings 明确说明攻击方和防守方均按无特性处理。
    该场景区分“特性不属于这只宝可梦”的非法输入与“特性合法但机制尚未开发”的能力缺口，防止后者被禁用、
    静默套用错误效果或直接抛出 unsupported 错误，也保证未来新增实现后只需更新 domain 枚举和 effect 映射。
    """
    result = ability_use_case().execute(ability_command())

    assert (result.damage.min_damage, result.damage.max_damage) == (99, 117)
    assert len(result.warnings) == 2
    assert all("按无特性处理" in warning for warning in result.warnings)


def test_ability_must_belong_to_selected_pokemon() -> None:
    """
    请求把仙子伊布的妖精皮肤伪造为巨钳螳螂的攻击方特性时，即使该 identifier 在全局 abilities 表真实存在，
    application 仍必须根据当前 ruleset 和 pokemon_id 的候选集合拒绝组合。这个测试保护服务端不信任前端枚举，
    避免用户手工提交任意特性获得不合法伤害结果；同时确保“未实现按无特性处理”只适用于合法归属的特性，
    不能成为绕过 Pokémon 特性约束的通用 UNKNOWN 降级通道。
    """
    with pytest.raises(CalculatorInputError, match="not available for attacker"):
        ability_use_case().execute(
            ability_command(attacker_ability="pixilate")
        )


def test_battle_stat_stages_change_effective_stats_and_damage() -> None:
    """
    单次伤害计算页面选择攻击方攻击提升二级时，50 级满攻中性巨钳螳螂的基础攻击仍应在结果 stats 中保持
    一百八十二，供用户理解配置模板；真正进入伤害公式的 effective_attack 则应按二倍提升到三百六十四，
    子弹拳伤害必须明显高于无等级变化的九十九到一百一十七。随后把仙子伊布防御提升二级，防御应从
    八十五提高到一百七十，并抵消攻击方同样的二级提升，使伤害回到原基线。该测试保护“配置能力值”和
    “战斗中能力等级”两个概念不会混写，也验证攻防等级在同一倍率下可以正确相消，而不是重复应用或只改展示。
    """
    boosted_attack = ability_use_case().execute(
        ability_command(attacker_stages=StatStages(attack=2))
    )

    assert boosted_attack.attacker.stats.attack == 182
    assert boosted_attack.attacker.effective_attack == 364
    assert boosted_attack.damage.min_damage > 99

    cancelled = ability_use_case().execute(
        ability_command(
            attacker_stages=StatStages(attack=2),
            defender_stages=StatStages(defense=2),
        )
    )

    assert cancelled.defender.stats.defense == 85
    assert cancelled.defender.effective_defense == 170
    assert (cancelled.damage.min_damage, cancelled.damage.max_damage) == (99, 117)


def test_non_damage_stat_stages_are_preserved_with_explicit_warning() -> None:
    """
    用户可以在红框区域选择速度、命中和回避等级，但基础单次伤害结果是“招式已经命中后的十六档伤害”，
    不包含行动顺序或命中概率。因此攻击方速度提升一级、防守方回避提升两级时，请求必须正常完成并保持
    九十九到一百一十七的伤害基线，同时 warnings 只增加一条清晰说明，告知这些值已被接收但不改变本次
    伤害。该场景防止前端可选字段被后端直接拒绝，也防止系统偷偷把命中率当作伤害倍率；未来接入命中和
    行动顺序后，可以在独立结果模型中消费这些字段，而无需改变当前请求合同。
    """
    result = ability_use_case().execute(
        ability_command(
            attacker_stages=StatStages(speed=1, accuracy=1),
            defender_stages=StatStages(evasion=2),
        )
    )

    assert (result.damage.min_damage, result.damage.max_damage) == (99, 117)
    assert any("速度、命中和回避等级" in warning for warning in result.warnings)
    assert "速度/命中/回避对单次伤害值的影响" in result.scope.excluded
