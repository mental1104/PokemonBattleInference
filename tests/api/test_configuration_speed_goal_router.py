from __future__ import annotations

import pytest

from pokeop.api.routers import configuration_solver
from pokeop.api.schemas.configuration_solver_with_speed import (
    ConfigurationSpeedGoalRequest,
    SearchConfigurationSpreadsWithSpeedRequest,
)
from pokeop.application.use_cases.search_configuration_spreads_with_speed import (
    SearchPokemonStatSpreadsWithSpeedUseCase,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import (
    FakeCalculatorAbilityRepository,
)


@pytest.mark.anyio
async def test_speed_goal_api_returns_strict_speed_evidence_and_spread() -> None:
    """
    HTTP 层接收只有速度目标、没有伤害目标的属性反推请求时，必须把目标 Pokémon、极限速度配置和
    候选上限完整转换到 application 命令。场景要求巨钳螳螂严格快于极限速度仙子伊布，响应应包含
    开朗性格、二百二十 Speed EV、一百二十四实际速度，以及目标一百二十三速度和正一点差值。
    该测试保护新增 speed_goals 字段可以独立提交，同时确保响应模型不会把速度证据塞入原伤害结构，
    并验证前端需要的 rejected_speed_goals、candidate.speed_goals 与区间字段都能稳定序列化。
    """
    response = await configuration_solver.search_configuration_spreads(
        SearchConfigurationSpreadsWithSpeedRequest(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            goals=[],
            speed_goals=[
                ConfigurationSpeedGoalRequest(
                    goal_id="outspeed-sylveon",
                    target_pokemon_id=SYLVEON_ID,
                    target_stat_preset="max_speed_plus",
                )
            ],
            max_candidates=3,
        ),
        use_case=SearchPokemonStatSpreadsWithSpeedUseCase(
            FakeCalculatorRepository(),
            FakeCalculatorAbilityRepository(),
        ),
    )

    payload = response.model_dump()
    assert payload["reachable"] is True
    assert payload["candidates"][0]["solution_kind"] == "spread"
    assert payload["candidates"][0]["nature_id"] == "jolly"
    assert payload["candidates"][0]["evs"]["speed"] == 220
    speed_evidence = payload["candidates"][0]["speed_goals"][0]
    assert speed_evidence["satisfied"] is True
    assert speed_evidence["subject_speed"] == 124
    assert speed_evidence["target_speed"] == 123
    assert speed_evidence["speed_margin"] == 1
    assert payload["rejected_speed_goals"] == []
