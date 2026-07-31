from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from pokeop.persistence.calculator import ability_repository as repository_module


def _ability_row(
    *,
    ability_id: int,
    identifier: str,
    display_name: str,
    slot: int,
    is_hidden: bool,
) -> SimpleNamespace:
    """构造 calculator 特性 repository 使用的最小 SQLAlchemy Row 替身。"""
    return SimpleNamespace(
        _mapping={
            "ability_id": ability_id,
            "ability_identifier": identifier,
            "ability_name": display_name,
            "slot": slot,
            "is_hidden": is_hidden,
        }
    )


def _execute_query(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows: list[SimpleNamespace],
) -> tuple[tuple[Any, ...], str, dict[str, Any]]:
    """注入数据库替身并返回 projection、规范化 SQL 和绑定参数。"""
    db = MagicMock()
    db.execute.return_value.all.return_value = rows
    db_kind = SimpleNamespace(POSTGRES="postgres")
    tx_scope = MagicMock(return_value=nullcontext(db))
    monkeypatch.setattr(
        repository_module,
        "_db_runtime",
        MagicMock(return_value=(db_kind, tx_scope)),
    )

    results = (
        repository_module.MaterializedViewCalculatorAbilityRepository()
        .list_pokemon_ability_options(
            ruleset_id="pokemon-champion",
            pokemon_id=212,
        )
    )
    statement, params = db.execute.call_args.args
    return results, " ".join(str(statement).split()), params


def test_repository_restores_history_and_marks_domain_implementation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Calculator 特性查询必须以当前 ruleset 的 generation 为历史还原边界，从 pokemon_abilities 的槽位出发，
    使用 pokemon_abilities_past 中最接近且仍适用的旧 ability_id，再关联主系列 abilities 与本地化名称。
    测试同时返回尚未实现的虫之预感和已实现的技术高手，断言前者完整保留但 effect_identifier 为空，后者
    映射为可进入 domain 的 identifier；SQL 还必须按槽位稳定排序，保证前端默认选择遵循 PokeAPI 原始顺序。
    """
    results, sql, params = _execute_query(
        monkeypatch,
        rows=[
            _ability_row(
                ability_id=68,
                identifier="swarm",
                display_name="虫之预感",
                slot=1,
                is_hidden=False,
            ),
            _ability_row(
                ability_id=101,
                identifier="technician",
                display_name="技术高手",
                slot=2,
                is_hidden=False,
            ),
        ],
    )

    assert [item.identifier for item in results] == ["swarm", "technician"]
    assert results[0].implemented is False
    assert results[0].effect_identifier is None
    assert results[1].implemented is True
    assert results[1].effect_identifier == "technician"
    assert "FROM poke_raw.pokemon_abilities pa" in sql
    assert "FROM poke_raw.pokemon_abilities_past pap" in sql
    assert "pap.generation_id >= rc.generation_id" in sql
    assert "ORDER BY resolved.slot, resolved.is_hidden, a.id" in sql
    assert params == {"ruleset_id": "pokemon-champion", "pokemon_id": 212}


def test_repository_preserves_hidden_ability_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    隐藏特性与普通特性都属于当前 Pokémon 的合法必选候选，persistence 不能因为 domain 尚未实现对应 effect
    就过滤记录或丢失 is_hidden 和 slot。测试模拟仙子伊布第三槽的妖精皮肤，验证 projection 保留数据库 ID、
    中文名、槽位及隐藏标记，同时明确 implemented=false 和无 effect_identifier；这保证 API 能展示“隐藏特性”
    与“当前未实现”两个独立事实，并让 application 在校验合法归属后安全地将该选择降级为无特性计算。
    """
    results, _, _ = _execute_query(
        monkeypatch,
        rows=[
            _ability_row(
                ability_id=182,
                identifier="pixilate",
                display_name="妖精皮肤",
                slot=3,
                is_hidden=True,
            )
        ],
    )

    assert len(results) == 1
    assert results[0].ability_id == 182
    assert results[0].display_name == "妖精皮肤"
    assert results[0].slot == 3
    assert results[0].is_hidden is True
    assert results[0].implemented is False
    assert results[0].effect_identifier is None
