from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculatorPokemonSearchResult,
)
from pokeop.persistence.calculator import repository as repository_module


STABLE_POKEMON_ORDER = (
    "ORDER BY pokemon_id ASC, "
    "form_identifier ASC NULLS FIRST, "
    "pokemon_identifier ASC"
)


def _pokemon_row(
    *,
    pokemon_id: int,
    identifier: str,
    form_identifier: str | None = None,
) -> SimpleNamespace:
    """构造 repository 搜索测试使用的最小 SQLAlchemy Row 替身。

    Args:
        pokemon_id: 物化视图中的 Pokémon ID，也是默认列表的主排序键。
        identifier: Pokémon 或具体形态的稳定英文 identifier。
        form_identifier: 形态 identifier；基础形态使用 None。

    Returns:
        带有 ``_mapping`` 属性的轻量对象，可被 repository 的行转换逻辑直接读取。
    """
    return SimpleNamespace(
        _mapping={
            "pokemon_id": pokemon_id,
            "pokemon_identifier": identifier,
            "pokemon_name": identifier,
            "form_identifier": form_identifier,
            "type_1_identifier": "normal",
            "type_1_name": "一般",
            "type_2_identifier": None,
            "type_2_name": None,
        }
    )


def _execute_search(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query: str,
    rows: list[SimpleNamespace],
    limit: int = 20,
) -> tuple[tuple[CalculatorPokemonSearchResult, ...], str, dict[str, Any]]:
    """使用可检查的数据库替身执行一次 Pokémon 搜索。

    Args:
        monkeypatch: pytest 提供的属性替换工具，用于隔离真实 PostgreSQL runtime。
        query: 传给 repository 的原始搜索词，可包含需要被去除的首尾空白。
        rows: 假数据库按 SQL 排序结果返回的行对象。
        limit: 本次查询允许返回的最大数量。

    Returns:
        依次返回 repository 结果、压缩空白后的 SQL 文本和实际绑定参数。
    """
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    db_kind = SimpleNamespace(POSTGRES="postgres")
    tx_scope = MagicMock(return_value=nullcontext(db))
    runtime = MagicMock(return_value=(db_kind, tx_scope))
    monkeypatch.setattr(repository_module, "_db_runtime", runtime)

    results = repository_module.MaterializedViewCalculatorRepository().search_pokemon(
        ruleset_id="pokemon-champion",
        query=query,
        limit=limit,
    )

    statement, params = db.execute.call_args.args
    normalized_sql = " ".join(str(statement).split())
    return results, normalized_sql, params


def test_empty_query_orders_default_list_by_pokemon_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    空搜索代表用户第一次展开攻击方或防守方 Pokémon 选择列表。测试使用妙蛙种子和妙蛙草两行结果，
    断言 repository 输出保持数据库按 ID 返回的次序，并且生成的 SQL 明确以 pokemon_id 升序作为
    第一排序键。这个场景保护默认列表从当前规则集最小 Pokémon ID 开始，而不是回退到英文名称的
    字符串顺序；同时确认空白搜索词会被规范化为空字符串，既不改变既有过滤语义，也不改变 limit。
    """
    results, sql, params = _execute_search(
        monkeypatch,
        query="   ",
        rows=[
            _pokemon_row(pokemon_id=1, identifier="bulbasaur"),
            _pokemon_row(pokemon_id=2, identifier="ivysaur"),
        ],
    )

    assert tuple(item.pokemon_id for item in results) == (1, 2)
    assert STABLE_POKEMON_ORDER in sql
    assert params == {
        "ruleset_id": "pokemon-champion",
        "query": "",
        "pattern": "%%",
        "limit": 20,
    }


def test_filtered_query_keeps_the_same_stable_id_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    用户输入中文名或 identifier 后，搜索条件只负责缩小候选集合，不应切换到另一套排序规则。测试
    传入带首尾空格的 saur 搜索词，验证绑定参数会规范化为 saur 和百分号模糊匹配，同时 SQL 仍然
    使用 pokemon_id、form_identifier、pokemon_identifier 的完整稳定排序链。这样可以防止空查询与
    有搜索词查询在相同候选上出现顺序跳动，也确保 API 现有 query、ruleset_id、limit 合同保持不变。
    """
    results, sql, params = _execute_search(
        monkeypatch,
        query="  saur  ",
        rows=[
            _pokemon_row(pokemon_id=2, identifier="ivysaur"),
            _pokemon_row(pokemon_id=3, identifier="venusaur"),
        ],
        limit=10,
    )

    assert tuple(item.identifier for item in results) == ("ivysaur", "venusaur")
    assert STABLE_POKEMON_ORDER in sql
    assert params["query"] == "saur"
    assert params["pattern"] == "%saur%"
    assert params["limit"] == 10


def test_same_pokemon_forms_use_explicit_tie_breakers(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    当物化视图为同一个 pokemon_id 返回基础形态和多个特殊形态时，仅按 ID 排序会留下数据库执行计划
    相关的不确定顺序。测试构造三条相同 ID 的皮卡丘记录，确认基础形态位于带 form_identifier 的形态
    之前，并要求 SQL 继续以 pokemon_identifier 作为最终稳定键。该断言保护重复请求得到一致顺序，
    同时避免前端或 application 层再做二次排序，确保排序责任仍完整留在 persistence repository 中。
    """
    results, sql, _ = _execute_search(
        monkeypatch,
        query="pikachu",
        rows=[
            _pokemon_row(pokemon_id=25, identifier="pikachu"),
            _pokemon_row(
                pokemon_id=25,
                identifier="pikachu-cosplay",
                form_identifier="cosplay",
            ),
            _pokemon_row(
                pokemon_id=25,
                identifier="pikachu-rock-star",
                form_identifier="rock-star",
            ),
        ],
    )

    assert tuple((item.form_identifier, item.identifier) for item in results) == (
        (None, "pikachu"),
        ("cosplay", "pikachu-cosplay"),
        ("rock-star", "pikachu-rock-star"),
    )
    assert STABLE_POKEMON_ORDER in sql
