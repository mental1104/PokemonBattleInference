from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pokeop.application.use_cases.list_calculable_moves import (
    CalculatorMoveFilterCategory,
    ListCalculatorMovesQuery,
)
from pokeop.persistence.calculator import repository as repository_module


def _move_row(
    *,
    move_id: int,
    identifier: str,
    type_identifier: str,
    category: str,
    power: int,
) -> SimpleNamespace:
    """构造 repository 招式分页测试使用的最小 SQLAlchemy Row 替身。"""
    return SimpleNamespace(
        _mapping={
            "move_id": move_id,
            "move_identifier": identifier,
            "move_name": identifier,
            "type_identifier": type_identifier,
            "type_name": type_identifier,
            "damage_class_identifier": category,
            "power": power,
        }
    )


def _type_row(type_id: int, identifier: str, name: str) -> SimpleNamespace:
    """构造规则集属性元数据查询使用的最小 Row 替身。"""
    return SimpleNamespace(
        _mapping={
            "damage_type_id": type_id,
            "damage_type_identifier": identifier,
            "damage_type_name": name,
        }
    )


def _install_db(
    monkeypatch: pytest.MonkeyPatch,
    db: MagicMock,
) -> None:
    """把 repository 的数据库 runtime 替换为可检查的事务和 session 替身。"""
    db_kind = SimpleNamespace(POSTGRES="postgres")
    tx_scope = MagicMock(return_value=nullcontext(db))
    monkeypatch.setattr(
        repository_module,
        "_db_runtime",
        MagicMock(return_value=(db_kind, tx_scope)),
    )


@pytest.mark.parametrize(
    ("category", "types"),
    (
        (CalculatorMoveFilterCategory.ALL, ()),
        (CalculatorMoveFilterCategory.PHYSICAL, ("electric",)),
        (CalculatorMoveFilterCategory.SPECIAL, ("electric", "water")),
    ),
)
def test_repository_builds_deduplicated_stable_filtered_page(
    monkeypatch: pytest.MonkeyPatch,
    category: CalculatorMoveFilterCategory,
    types: tuple[str, ...],
) -> None:
    """
    persistence 必须在 SQL 内完成 learnset 多记录去重、类别过滤、属性 OR、文本 AND、稳定排序和 offset
    分页。参数化场景覆盖全部、物理和特殊三个类别以及零个、单个和多个属性；测试检查两次查询共享同一
    组绑定参数，CTE 使用 DISTINCT ON(move_id)，外层顺序严格为威力降序、属性 identifier 降序、
    move_id 升序和最终 identifier 升序。返回结果总数来自去重后的 count，不得用当前页长度代替。
    """
    count_result = MagicMock()
    count_result.scalar_one.return_value = 3
    page_result = MagicMock()
    page_result.all.return_value = [
        _move_row(
            move_id=85,
            identifier="thunderbolt",
            type_identifier="electric",
            category="special",
            power=90,
        ),
        _move_row(
            move_id=57,
            identifier="surf",
            type_identifier="water",
            category="special",
            power=90,
        ),
    ]
    db = MagicMock()
    db.execute.side_effect = [count_result, page_result]
    _install_db(monkeypatch, db)

    request = ListCalculatorMovesQuery(
        ruleset_id="pokemon-champion",
        pokemon_id=25,
        query="bolt",
        category=category,
        type_identifiers=types,
        limit=2,
        offset=1,
    )
    items, total = repository_module.MaterializedViewCalculatorRepository().search_calculable_moves(
        request=request
    )

    count_statement, count_params = db.execute.call_args_list[0].args
    page_statement, page_params = db.execute.call_args_list[1].args
    normalized_count_sql = " ".join(str(count_statement).split())
    normalized_page_sql = " ".join(str(page_statement).split())

    assert "SELECT DISTINCT ON (move_id)" in normalized_count_sql
    assert "damage_class_identifier IN ('physical', 'special')" in normalized_count_sql
    assert ":category = 'all' OR damage_class_identifier = :category" in normalized_count_sql
    assert "type_identifier = ANY(CAST(:type_identifiers AS TEXT[]))" in normalized_count_sql
    assert "ORDER BY power DESC, type_identifier DESC, move_id ASC, move_identifier ASC" in normalized_page_sql
    assert count_params == page_params
    assert page_params["category"] == category.value
    assert page_params["type_identifiers"] == list(types)
    assert page_params["type_count"] == len(types)
    assert page_params["limit"] == 2
    assert page_params["offset"] == 1
    assert total == 3
    assert tuple(item.move_id for item in items) == (85, 57)


def test_repository_returns_complete_ruleset_type_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    前端属性按钮不能从当前 Pokémon 的前十条招式推断，因此 repository 必须从 version-aware 的
    type_efficacy_mv 读取当前 ruleset 全部攻击属性。测试提供电、水、火三行并断言结果保持 type_id
    顺序和本地化名称，同时检查 SQL 只按 ruleset_id 过滤且明确按 damage_type_id 升序。该场景保护
    属性元数据不会随着当前 Pokémon、文本筛选或分页内容变化，也不会直接读取前端硬编码常量。
    """
    result = MagicMock()
    result.all.return_value = [
        _type_row(10, "fire", "火"),
        _type_row(11, "water", "水"),
        _type_row(13, "electric", "电"),
    ]
    db = MagicMock()
    db.execute.return_value = result
    _install_db(monkeypatch, db)

    options = repository_module.MaterializedViewCalculatorRepository().list_move_filter_types(
        ruleset_id="pokemon-champion"
    )

    statement, params = db.execute.call_args.args
    normalized_sql = " ".join(str(statement).split())
    assert "FROM poke_champion.type_efficacy_mv" in normalized_sql
    assert "ORDER BY damage_type_id ASC" in normalized_sql
    assert params == {"ruleset_id": "pokemon-champion"}
    assert tuple((item.identifier, item.display_name) for item in options) == (
        ("fire", "火"),
        ("water", "水"),
        ("electric", "电"),
    )
