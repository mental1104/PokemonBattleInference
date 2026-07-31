from __future__ import annotations

import pytest

from pokeop.application.use_cases.calculate_catalog_damage import CalculatorInputError
from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculateCatalogDamageWithAbilitiesCommand,
    CalculateCatalogDamageWithAbilitiesUseCase,
    CalculateCatalogPokemonWithAbilityCommand,
    CalculatorAbilityOption,
)
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
) -> CalculateCatalogDamageWithAbilitiesCommand:
    """创建巨钳螳螂使用子弹拳攻击仙子伊布的特性感知命令。"""
    return CalculateCatalogDamageWithAbilitiesCommand(
        ruleset_id="pokemon-champion",
        attacker=CalculateCatalogPokemonWithAbilityCommand(
            pokemon_id=SCIZOR_ID,
            level=50,
            stat_preset="max_atk_neutral",
            ability_identifier=attacker_ability,
        ),
        defender=CalculateCatalogPokemonWithAbilityCommand(
            pokemon_id=SYLVEON_ID,
            level=50,
            stat_preset="max_hp",
            ability_identifier=defender_ability,
        ),
        move_id=BULLET_PUNCH_ID,
    )


def ability_use_case() -> CalculateCatalogDamageWithAbilitiesUseCase:
    """创建同时注入 catalog 与特性 fake repository 的 use case。"""
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
