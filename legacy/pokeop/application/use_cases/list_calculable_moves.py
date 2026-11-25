from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from pokeop.application.use_cases.calculate_catalog_damage import CalculatorMoveSearchResult


class CalculatorMoveFilterCategory(str, Enum):
    """计算器招式列表支持的类别筛选值。

    该枚举属于 application 查询合同，用于表达“不过滤类别”以及物理、特殊两个
    可计算类别；它不扩展 domain 的 MoveCategory，也不会把 HTTP 字符串直接传入 SQL。
    """

    ALL = "all"
    PHYSICAL = "physical"
    SPECIAL = "special"


@dataclass(frozen=True)
class CalculatorMoveTypeOption:
    """当前规则集支持的一个招式属性筛选项。"""

    identifier: str
    display_name: str


@dataclass(frozen=True)
class ListCalculatorMovesQuery:
    """查询一只 Pokémon 可计算招式的筛选与分页输入。

    Attributes:
        ruleset_id: 稳定规则集标识，repository 由此定位 version group 读取模型。
        pokemon_id: 当前攻击方的 PokeAPI Pokémon ID。
        query: 中文名或 identifier 的模糊搜索词，application 会去除首尾空白。
        category: 全部、物理或特殊的显式类别筛选。
        type_identifiers: 属性 identifier 集合；多个值之间使用 OR，空集合表示不过滤。
        limit: 单页条数，合法范围为 1 到 50。
        offset: 从稳定排序结果起点跳过的条数，必须大于或等于 0。
    """

    ruleset_id: str
    pokemon_id: int
    query: str
    category: CalculatorMoveFilterCategory
    type_identifiers: tuple[str, ...]
    limit: int
    offset: int


@dataclass(frozen=True)
class CalculatorMovePage:
    """application 返回给 API 的稳定分页结果。"""

    items: tuple[CalculatorMoveSearchResult, ...]
    total: int
    limit: int
    offset: int
    has_more: bool
    available_types: tuple[CalculatorMoveTypeOption, ...]


class CalculatorMoveQueryError(ValueError):
    """表示招式筛选或分页参数不符合当前规则集查询合同。"""


class CalculatorMoveCatalogRepository(Protocol):
    """招式筛选 use case 依赖的持久化读取端口。"""

    def list_move_filter_types(
        self,
        *,
        ruleset_id: str,
    ) -> tuple[CalculatorMoveTypeOption, ...]:
        """返回当前规则集完整且稳定排序的属性筛选元数据。"""

    def search_calculable_moves(
        self,
        *,
        request: ListCalculatorMovesQuery,
    ) -> tuple[tuple[CalculatorMoveSearchResult, ...], int]:
        """执行去重、复合过滤、稳定排序和分页，并返回当前页与总数。"""


class ListCalculatorMovesUseCase:
    """校验招式筛选输入并编排规则集属性元数据与分页查询。"""

    def __init__(self, repository: CalculatorMoveCatalogRepository) -> None:
        """保存只负责 calculator 招式读取的 repository 端口。

        Args:
            repository: 提供规则集属性元数据和可计算招式分页读取的持久化实现。
        """
        self._repository = repository

    def execute(self, request: ListCalculatorMovesQuery) -> CalculatorMovePage:
        """执行一次招式复合过滤和分页查询。

        Args:
            request: 包含规则集、攻击方、文本、类别、属性和分页参数的查询对象。

        Returns:
            包含当前页、稳定总数、是否仍有后续结果及完整属性元数据的分页对象。

        Raises:
            CalculatorMoveQueryError: limit、offset 或属性 identifier 非法。
        """
        if request.limit < 1 or request.limit > 50:
            raise CalculatorMoveQueryError("limit must be between 1 and 50")
        if request.offset < 0:
            raise CalculatorMoveQueryError("offset must be greater than or equal to 0")

        available_types = self._repository.list_move_filter_types(
            ruleset_id=request.ruleset_id,
        )
        allowed_type_identifiers = {item.identifier for item in available_types}
        normalized_type_identifiers = tuple(dict.fromkeys(request.type_identifiers))
        invalid_type_identifiers = sorted(
            set(normalized_type_identifiers) - allowed_type_identifiers
        )
        if invalid_type_identifiers:
            joined = ", ".join(invalid_type_identifiers)
            raise CalculatorMoveQueryError(f"unsupported move type: {joined}")

        normalized_request = ListCalculatorMovesQuery(
            ruleset_id=request.ruleset_id,
            pokemon_id=request.pokemon_id,
            query=request.query.strip(),
            category=CalculatorMoveFilterCategory(request.category),
            type_identifiers=normalized_type_identifiers,
            limit=request.limit,
            offset=request.offset,
        )
        items, total = self._repository.search_calculable_moves(
            request=normalized_request,
        )
        return CalculatorMovePage(
            items=items,
            total=total,
            limit=normalized_request.limit,
            offset=normalized_request.offset,
            has_more=normalized_request.offset + len(items) < total,
            available_types=available_types,
        )


__all__ = [
    "CalculatorMoveCatalogRepository",
    "CalculatorMoveFilterCategory",
    "CalculatorMovePage",
    "CalculatorMoveQueryError",
    "CalculatorMoveTypeOption",
    "ListCalculatorMovesQuery",
    "ListCalculatorMovesUseCase",
]
