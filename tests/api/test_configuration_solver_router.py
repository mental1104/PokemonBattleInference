from __future__ import annotations

import pytest

from pokeop.api.routers import configuration_solver
from pokeop.api.schemas.configuration_solver import (
    ConfigurationGoalRequest,
    SolveConfigurationRequest,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalKind,
    DamageRollPolicy,
    SolvePokemonConfigurationUseCase,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)


@pytest.mark.anyio
async def test_configuration_solver_api_returns_reachable_candidate():
    """router 应把反向求解结果转换成前端可直接展示的候选配置和目标证据。"""
    response = await configuration_solver.solve_configuration(
        SolveConfigurationRequest(
            subject_pokemon_id=SCIZOR_ID,
            goals=[
                ConfigurationGoalRequest(
                    goal_id="attack-sylveon-2hko",
                    kind=ConfigurationGoalKind.ATTACK,
                    target_pokemon_id=SYLVEON_ID,
                    move_id=BULLET_PUNCH_ID,
                    required_turns=2,
                    target_stat_preset="no_investment",
                    damage_roll_policy=DamageRollPolicy.MIN,
                )
            ],
            allowed_stat_presets=["max_atk_neutral"],
        ),
        use_case=SolvePokemonConfigurationUseCase(FakeCalculatorRepository()),
    )

    payload = response.model_dump()
    assert payload["reachable"] is True
    assert payload["subject"]["display_name"] == "巨钳螳螂"
    assert payload["candidates"][0]["stat_preset"] == "max_atk_neutral"
    assert payload["candidates"][0]["goals"][0]["satisfied"] is True
    assert payload["candidates"][0]["goals"][0]["roll_policy"] == "min"
    assert payload["candidates"][0]["goals"][0]["total_damage"] == 198
    assert "同一套配置同时验收全部目标" in payload["scope"]
