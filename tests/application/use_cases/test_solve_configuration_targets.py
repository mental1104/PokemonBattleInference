from __future__ import annotations

import pytest

from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalKind,
    ConfigurationSolverInputError,
    DamageRollPolicy,
    SolvePokemonConfigurationCommand,
    SolvePokemonConfigurationUseCase,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import (
    FakeCalculatorAbilityRepository,
)


def solver_use_case() -> SolvePokemonConfigurationUseCase:
    """创建同时提供 catalog 和合法特性关系的反向求解用例。"""
    return SolvePokemonConfigurationUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    )


def attack_command(
    *,
    subject_ability: str = "swarm",
    subject_item: str | None = None,
    target_ability: str = "cute-charm",
    target_item: str | None = None,
) -> SolvePokemonConfigurationCommand:
    """创建巨钳螳螂攻击仙子伊布的两次击倒目标。"""
    return SolvePokemonConfigurationCommand(
        subject_pokemon_id=SCIZOR_ID,
        subject_ability_identifier=subject_ability,
        subject_item_identifier=subject_item,
        goals=(
            ConfigurationGoalCommand(
                goal_id="attack-sylveon-2hko",
                kind=ConfigurationGoalKind.ATTACK,
                target_pokemon_id=SYLVEON_ID,
                move_id=BULLET_PUNCH_ID,
                required_turns=2,
                target_ability_identifier=target_ability,
                target_item_identifier=target_item,
                target_stat_preset="no_investment",
                damage_roll_policy=DamageRollPolicy.MIN,
            ),
        ),
        allowed_stat_presets=("max_atk_neutral", "no_investment"),
    )


def test_configuration_solver_finds_candidate_that_satisfies_attack_goal():
    """未实现特性降级为无效果后，原有确定性配置搜索结果保持不变。"""
    result = solver_use_case().execute(attack_command())

    assert result.reachable is True
    assert result.candidates[0].preset.key == "max_atk_neutral"
    goal = result.candidates[0].goal_results[0]
    assert goal.satisfied is True
    assert goal.selected_damage == 99
    assert goal.total_damage == 198
    assert goal.hp_threshold == 170
    assert any("待配置 Pokémon" in warning for warning in result.warnings)
    assert any("攻目标防守方" in warning for warning in result.warnings)


def test_configuration_solver_returns_unreachable_without_relaxing_goal():
    """当所有候选都不满足用户目标时，求解器必须显式返回不可达和失败证据。"""
    result = solver_use_case().execute(
        SolvePokemonConfigurationCommand(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            goals=(
                ConfigurationGoalCommand(
                    goal_id="attack-sylveon-ohko",
                    kind=ConfigurationGoalKind.ATTACK,
                    target_pokemon_id=SYLVEON_ID,
                    move_id=BULLET_PUNCH_ID,
                    required_turns=1,
                    target_ability_identifier="cute-charm",
                    target_stat_preset="max_hp",
                    damage_roll_policy=DamageRollPolicy.MAX,
                ),
            ),
            allowed_stat_presets=("max_atk_neutral",),
        )
    )

    assert result.reachable is False
    assert result.candidates == ()
    assert result.rejected_goal_results[0].goal_id == "attack-sylveon-ohko"
    assert result.rejected_goal_results[0].satisfied is False
    assert result.rejected_goal_results[0].remaining_hp == 85


def test_configuration_solver_applies_selected_ability_and_item():
    """待配置 Pokémon 的技术高手和生命宝珠必须共同进入 domain 伤害链。"""
    baseline = solver_use_case().execute(attack_command())
    enhanced = solver_use_case().execute(
        attack_command(subject_ability="technician", subject_item="life-orb")
    )

    baseline_damage = baseline.candidates[0].goal_results[0].selected_damage
    enhanced_damage = enhanced.candidates[0].goal_results[0].selected_damage
    assert enhanced_damage > baseline_damage
    assert not any("待配置 Pokémon 特性" in warning for warning in enhanced.warnings)


def test_configuration_solver_rejects_ability_from_another_pokemon():
    """未实现降级不能绕过特性归属校验。"""
    with pytest.raises(ConfigurationSolverInputError, match="not available for subject"):
        solver_use_case().execute(attack_command(subject_ability="pixilate"))
