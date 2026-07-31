from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pokeop.persistence.calculator import item_catalog_repository as repository_module


def _item_row(*, item_id: int, identifier: str, display_name: str) -> SimpleNamespace:
    """构造完整道具目录测试使用的 SQLAlchemy Row 替身。

    Args:
        item_id: PokeAPI 道具主键。
        identifier: PokeAPI 稳定英文 identifier。
        display_name: 当前规则集语言下的展示名称。

    Returns:
        带有 ``_mapping`` 属性、可直接进入 repository 转换函数的轻量对象。
    """
    return SimpleNamespace(
        _mapping={
            "item_id": item_id,
            "item_identifier": identifier,
            "item_name": display_name,
        }
    )


def test_item_catalog_keeps_unimplemented_battle_items_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    道具选择接口应覆盖当前世代全部可战斗携带道具，而不能继续用 DamageItem 枚举作为 SQL 白名单。
    测试让数据库依次返回尚未实现的吃剩的东西和已实现的生命宝珠，断言查询中不再出现 identifier ANY
    过滤条件，绑定参数只保留 ruleset_id；返回结果必须包含两项，并把已实现道具排到未实现道具之前。
    同时验证未实现道具的 effect_identifier 为 None，而生命宝珠仍保留原 identifier，保护前端能够展示
    完整目录、可靠禁用未实现项，又不会破坏已接入 domain 的既有伤害效果映射。
    """
    db = MagicMock()
    db.execute.return_value.all.return_value = [
        _item_row(item_id=234, identifier="leftovers", display_name="吃剩的东西"),
        _item_row(item_id=247, identifier="life-orb", display_name="生命宝珠"),
    ]
    db_kind = SimpleNamespace(POSTGRES="postgres")
    tx_scope = MagicMock(return_value=nullcontext(db))
    monkeypatch.setattr(
        repository_module,
        "_db_runtime",
        MagicMock(return_value=(db_kind, tx_scope)),
    )

    results = repository_module.MaterializedViewCalculatorRepository().list_battle_item_options(
        ruleset_id="pokemon-champion"
    )

    statement, params = db.execute.call_args.args
    normalized_sql = " ".join(str(statement).split())
    assert "item.identifier = ANY" not in normalized_sql
    assert params == {"ruleset_id": "pokemon-champion"}
    assert tuple(item.identifier for item in results) == (
        "none",
        "life-orb",
        "leftovers",
    )
    assert tuple(item.effect_identifier for item in results) == (
        None,
        "life-orb",
        None,
    )
