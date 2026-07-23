from __future__ import annotations

import pytest

from pokeop.application.use_cases.calculate_catalog_damage import CalculatorMoveSearchResult
from pokeop.application.use_cases.list_calculable_moves import (
    CalculatorMoveFilterCategory,
    CalculatorMoveQueryError,
    CalculatorMoveTypeOption,
    ListCalculatorMovesQuery,
    ListCalculatorMovesUseCase,
)
from pokeop.domain.battle.context import MoveCategory


class FakeMoveCatalogRepository:
    """记录 application 查询对象并返回固定分页数据的内存 repository。"""

    def __init__(self) -> None:
        """初始化可用属性、固定招式以及最近一次收到的查询。"""
        self.last_request: ListCalculatorMovesQuery | None = None
        self.available_types = (
            CalculatorMoveTypeOption("electric", "电"),
            CalculatorMoveTypeOption("water", "水"),
            CalculatorMoveTypeOption("fire", "火"),
        )

    def list_move_filter_types(
        self,
        *,
        ruleset_id: str,
    ) -> tuple[CalculatorMoveTypeOption, ...]:
        """返回当前测试规则集支持的三个属性筛选项。"""
        assert ruleset_id == "pokemon-champion"
        return self.available_types

    def search_calculable_moves(
        self,
        *,
        request: ListCalculatorMovesQuery,
    ) -> tuple[tuple[CalculatorMoveSearchResult, ...], int]:
        """保存规范化后的查询，并返回两条固定物理招式和三条总数。"""
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
                CalculatorMoveSearchResult(
                    move_id=57,
                    identifier="surf",
                    display_name="冲浪",
                    type="water",
                    type_name="水",
                    category=MoveCategory.SPECIAL,
                    power=90,
                ),
            ),
            3,
        )


def _query(**overrides: object) -> ListCalculatorMovesQuery:
    """构造默认招式分页查询，并允许测试覆盖单个字段。"""
    values: dict[str, object] = {
        "ruleset_id": "pokemon-champion",
        "pokemon_id": 25,
        "query": "  bolt  ",
        "category": CalculatorMoveFilterCategory.SPECIAL,
        "type_identifiers": ("water", "electric", "water"),
        "limit": 2,
        "offset": 0,
    }
    values.update(overrides)
    return ListCalculatorMovesQuery(**values)  # type: ignore[arg-type]


def test_move_list_use_case_normalizes_filters_and_builds_page_metadata() -> None:
    """
    用户同时选择水与电属性、特殊类别并输入带首尾空白的搜索词时，application 必须先读取当前规则集
    的完整属性元数据，再按首次出现顺序去重属性 identifier，并把规范化后的查询交给 persistence。
    测试还断言总数为三而当前页只有两项时 has_more 为真，从而保护前端“查看全部”入口不依赖猜测；
    available_types 必须保持完整三项，不能只从当前返回的水、电两条招式反推出筛选选项。
    """
    repository = FakeMoveCatalogRepository()

    result = ListCalculatorMovesUseCase(repository).execute(_query())

    assert repository.last_request is not None
    assert repository.last_request.query == "bolt"
    assert repository.last_request.type_identifiers == ("water", "electric")
    assert repository.last_request.category is CalculatorMoveFilterCategory.SPECIAL
    assert result.total == 3
    assert result.has_more is True
    assert tuple(item.identifier for item in result.available_types) == (
        "electric",
        "water",
        "fire",
    )


def test_move_list_use_case_rejects_type_outside_ruleset_metadata() -> None:
    """
    属性筛选值来自 HTTP 重复参数，不能被直接传入 SQL。测试请求当前规则集元数据中不存在的 shadow，
    期望 use case 在调用分页查询之前抛出稳定的 CalculatorMoveQueryError，并在错误文本中指出非法值。
    该边界避免拼写错误被悄悄解释为空结果，也确保未来不同世代缺失属性时仍由 application 按规则集
    元数据验证，而不是让前端硬编码十八属性或让 persistence 自行决定是否忽略非法输入。
    """
    repository = FakeMoveCatalogRepository()

    with pytest.raises(CalculatorMoveQueryError, match="shadow"):
        ListCalculatorMovesUseCase(repository).execute(
            _query(type_identifiers=("electric", "shadow"))
        )

    assert repository.last_request is None


@pytest.mark.parametrize(
    ("limit", "offset", "message"),
    ((0, 0, "limit"), (51, 0, "limit"), (10, -1, "offset")),
)
def test_move_list_use_case_rejects_invalid_pagination(
    limit: int,
    offset: int,
    message: str,
) -> None:
    """
    分页范围同时受 HTTP 和 application 双层保护：limit 必须位于一到五十之间，offset 不得为负数。
    参数化场景覆盖零条、超过服务端硬上限以及负偏移，断言全部在读取属性元数据和执行 SQL 之前失败。
    这保证任何绕过 FastAPI 直接调用 use case 的消费者也无法一次拉取全部招式，或者构造含义不明确的
    负数页，服务端五十条硬上限不会只依赖网关层 Query 配置而在内部调用时失效。
    """
    repository = FakeMoveCatalogRepository()

    with pytest.raises(CalculatorMoveQueryError, match=message):
        ListCalculatorMovesUseCase(repository).execute(
            _query(limit=limit, offset=offset)
        )

    assert repository.last_request is None
