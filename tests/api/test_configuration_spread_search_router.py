from __future__ import annotations

import pytest

from pokeop.api.routers import configuration_solver
from pokeop.api.schemas.configuration_solver import (
    ConfigurationGoalRequest,
    SearchConfigurationSpreadsRequest,
)
from pokeop.application.use_cases.search_configuration_spreads import (
    SearchPokemonStatSpreadsUseCase,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalKind,
    DamageRollPolicy,
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


@pytest.mark.anyio
async def test_configuration_spread_search_api_returns_saveable_interval_candidate():
    """
    HTTP 层收到固定待配置 Pokémon、特性、道具和两次击倒目标后，应把请求转换成 application
    属性反推命令，而不是偷偷补入内置配置模板。响应中的首条候选必须标记为 spread，包含代表
    nature、EV、IV、等价性格列表、六项独立安全区间和原有目标伤害证据；这些字段将直接驱动
    前端结果卡片与“添加到 Pokémon 专属配置”按钮，因此任何空字段都会破坏完整保存链路。
    """
    response = await configuration_solver.search_configuration_spreads(
        SearchConfigurationSpreadsRequest(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            goals=[
                ConfigurationGoalRequest(
                    goal_id="attack-sylveon-2hko",
                    kind=ConfigurationGoalKind.ATTACK,
                    target_pokemon_id=SYLVEON_ID,
                    move_id=BULLET_PUNCH_ID,
                    required_turns=2,
                    target_ability_identifier="cute-charm",
                    target_stat_preset="no_investment",
                    damage_roll_policy=DamageRollPolicy.MIN,
                )
            ],
            max_candidates=10,
        ),
        use_case=SearchPokemonStatSpreadsUseCase(
            FakeCalculatorRepository(),
            FakeCalculatorAbilityRepository(),
        ),
    )

    payload = response.model_dump()
    assert payload["reachable"] is True
    assert 1 <= len(payload["candidates"]) <= 10
    candidate = payload["candidates"][0]
    assert candidate["solution_kind"] == "spread"
    assert candidate["nature_id"]
    assert candidate["nature_options"]
    assert candidate["evs"]["speed"] == 0
    assert candidate["ivs"]["speed"] == 31
    assert candidate["ev_ranges"]["attack"]["minimum"] <= candidate["evs"]["attack"]
    assert candidate["iv_ranges"]["attack"]["minimum"] <= candidate["ivs"]["attack"]
    assert candidate["goals"][0]["satisfied"] is True
    assert "EV/IV/性格反推" in payload["scope"]
