from __future__ import annotations

import pytest
from fastapi import HTTPException

from pokeop.api.routers import calculator
from pokeop.application.use_cases.calculate_catalog_damage import CalculatorMoveSearchResult
from pokeop.application.use_cases.list_calculable_moves import (
    CalculatorMoveFilterCategory,
    CalculatorMoveTypeOption,
    ListCalculatorMovesQuery,
    ListCalculatorMovesUseCase,
)
from pokeop.domain.battle.context import MoveCategory


class FakeMoveRepository:
    """为 router 测试记录查询并返回固定招式分页结果。"""

    def __init__(self, *, fail_type: bool = False) -> None:
        """配置是否让属性元数据排除请求中的 shadow。"""
        self.last_request: ListCalculatorMovesQuery | None = None
        self.fail_type = fail_type

    def list_move_filter_types(
        self,
        *,
        ruleset_id: str,
    ) -> tuple[CalculatorMoveTypeOption, ...]:
        """返回电和水两个当前规则集属性筛选项。"""
        return (
            CalculatorMoveTypeOption("electric", "电"),
            CalculatorMoveTypeOption("water", "水"),
        )

    def search_calculable_moves(
        self,
        *,
        request: ListCalculatorMovesQuery,
    ) -> tuple[tuple[CalculatorMoveSearchResult, ...], int]:
        """保存 HTTP 转换后的查询并返回一条十万伏特。"""
        self.last_request = request
        return (
            (
                CalculatorMoveSearchResult(
                    move_id=85,
                    identifier="thunderbolt",
                    display_name="十万伏特",
                    type="electric",
                    type_name="电",
                    category=MoveCategory.SPECIAL,
                    power=90,
                ),
            ),
            12,
        )


@pytest.mark.anyio
async def test_move_router_returns_filtered_page_envelope() -> None:
    """
    HTTP 层接收 category 和重复 type 参数后，只负责构造 application 查询对象并把分页结果转换成
    JSON schema。测试传入特殊类别、电和水两个属性、limit 十与 offset 零，断言 use case 收到完整
    复合条件；响应包含一条十万伏特、总数十二、has_more 为真及完整属性元数据。该场景保护 endpoint
    不再返回裸数组，也确保 category、types 和分页字段不会在 router 转换时丢失或被拼成 SQL。
    """
    repository = FakeMoveRepository()

    response = await calculator.list_pokemon_moves(
        pokemon_id=25,
        ruleset_id="pokemon-champion",
        query="bolt",
        category=CalculatorMoveFilterCategory.SPECIAL,
        type_identifiers=["electric", "water"],
        limit=10,
        offset=0,
        use_case=ListCalculatorMovesUseCase(repository),
    )

    assert repository.last_request is not None
    assert repository.last_request.category is CalculatorMoveFilterCategory.SPECIAL
    assert repository.last_request.type_identifiers == ("electric", "water")
    assert response.total == 12
    assert response.has_more is True
    assert response.items[0].identifier == "thunderbolt"
    assert [item.identifier for item in response.available_types] == ["electric", "water"]


@pytest.mark.anyio
async def test_move_router_converts_invalid_type_to_400() -> None:
    """
    FastAPI 已通过枚举和 Query 范围约束处理非法 category、limit 与 offset；规则集相关的属性合法性
    则由 application 校验。测试向当前只支持电和水的 fake ruleset 传入 shadow，期望 router 把
    CalculatorMoveQueryError 转换为明确的 HTTP 400，而不是泄漏成 500 或静默返回空数组。该行为让
    前端可以区分“筛选后没有结果”和“筛选参数本身无效”，并防止规则集属性差异被忽略。
    """
    with pytest.raises(HTTPException) as exc_info:
        await calculator.list_pokemon_moves(
            pokemon_id=25,
            ruleset_id="pokemon-champion",
            query="",
            category=CalculatorMoveFilterCategory.ALL,
            type_identifiers=["shadow"],
            limit=10,
            offset=0,
            use_case=ListCalculatorMovesUseCase(FakeMoveRepository()),
        )

    assert exc_info.value.status_code == 400
    assert "shadow" in str(exc_info.value.detail)
