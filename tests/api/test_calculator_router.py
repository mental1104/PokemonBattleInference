from __future__ import annotations

import pytest
from fastapi import HTTPException

from pokeop.api.routers import calculator
from pokeop.api.schemas.calculator import CalculateDamageRequest, CalculatorPokemonInput
from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculateCatalogDamageUseCase,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)


def _request() -> CalculateDamageRequest:
    """创建 API 层计算请求对象。

    该请求只包含用户选择和模板 key，不携带任何前端伪造的派生战斗资料。
    """
    return CalculateDamageRequest(
        ruleset_id="pokemon-champion",
        attacker=CalculatorPokemonInput(
            pokemon_id=SCIZOR_ID,
            level=50,
            stat_preset="max_atk_neutral",
        ),
        defender=CalculatorPokemonInput(
            pokemon_id=SYLVEON_ID,
            level=50,
            stat_preset="max_hp",
        ),
        move_id=BULLET_PUNCH_ID,
    )


@pytest.mark.anyio
async def test_calculator_damage_api_returns_frontend_ready_result():
    """
    通过 router 函数执行巨钳螳螂、子弹拳、仙子伊布的基础伤害计算。测试断言响应包含
    前端首屏需要的双方名称、有效攻击/HP/防御、伤害区间、KO 字段和基础模式范围说明。
    这里直接注入 use case，避免 TestClient 在当前 pytest 插件组合下触发不稳定等待。
    """
    response = await calculator.calculate_damage(
        _request(),
        use_case=CalculateCatalogDamageUseCase(FakeCalculatorRepository()),
    )

    payload = response.model_dump()
    assert payload["ruleset_id"] == "pokemon-champion"
    assert payload["attacker"]["display_name"] == "巨钳螳螂"
    assert payload["attacker"]["effective_attack"] == 182
    assert payload["defender"]["display_name"] == "仙子伊布"
    assert payload["defender"]["effective_hp"] == 202
    assert payload["defender"]["effective_defense"] == 85
    assert payload["move"]["display_name"] == "子弹拳"
    assert payload["move"]["type"] == "steel"
    assert payload["damage"]["min"] == 99
    assert payload["damage"]["max"] == 117
    assert len(payload["damage"]["rolls"]) == 16
    assert "ohko_probability" in payload["ko"]
    assert "动态威力招式" in payload["scope"]["excluded"]


@pytest.mark.anyio
async def test_calculator_damage_api_returns_400_for_illegal_move_combination():
    """
    当 application 层拒绝非法宝可梦/招式组合时，router 必须返回 400 和可读错误，
    而不是把异常泄漏为 500。这个行为让前端可以把过期选择或伪造请求展示成表单错误。
    """
    with pytest.raises(HTTPException) as exc_info:
        await calculator.calculate_damage(
            _request(),
            use_case=CalculateCatalogDamageUseCase(FakeCalculatorRepository(allow_move=False)),
        )

    assert exc_info.value.status_code == 400
    assert "move is not available" in str(exc_info.value.detail)
