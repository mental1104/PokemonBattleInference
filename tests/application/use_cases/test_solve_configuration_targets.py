from __future__ import annotations

from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalKind,
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


def test_configuration_solver_finds_candidate_that_satisfies_attack_goal():
    """首版反向求解应能在允许模板中找到同一套满足攻击目标的配置。"""
    result = SolvePokemonConfigurationUseCase(FakeCalculatorRepository()).execute(
        SolvePokemonConfigurationCommand(
            subject_pokemon_id=SCIZOR_ID,
            goals=(
                ConfigurationGoalCommand(
                    goal_id="attack-sylveon-2hko",
                    kind=ConfigurationGoalKind.ATTACK,
                    target_pokemon_id=SYLVEON_ID,
                    move_id=BULLET_PUNCH_ID,
                    required_turns=2,
                    target_stat_preset="no_investment",
                    damage_roll_policy=DamageRollPolicy.MIN,
                ),
            ),
            allowed_stat_presets=("max_atk_neutral", "no_investment"),
        )
    )

    assert result.reachable is True
    assert result.candidates[0].preset.key == "max_atk_neutral"
    goal = result.candidates[0].goal_results[0]
    assert goal.satisfied is True
    assert goal.selected_damage == 99
    assert goal.total_damage == 198
    assert goal.hp_threshold == 170


def test_configuration_solver_returns_unreachable_without_relaxing_goal():
    """当所有候选都不满足用户目标时，求解器必须显式返回不可达和失败证据。"""
    result = SolvePokemonConfigurationUseCase(FakeCalculatorRepository()).execute(
        SolvePokemonConfigurationCommand(
            subject_pokemon_id=SCIZOR_ID,
            goals=(
                ConfigurationGoalCommand(
                    goal_id="attack-sylveon-ohko",
                    kind=ConfigurationGoalKind.ATTACK,
                    target_pokemon_id=SYLVEON_ID,
                    move_id=BULLET_PUNCH_ID,
                    required_turns=1,
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
