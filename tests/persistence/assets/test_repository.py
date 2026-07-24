from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pokeop.persistence.assets import repository as repository_module


def _install_db(monkeypatch: pytest.MonkeyPatch, db: MagicMock) -> None:
    """把 assets repository 的数据库 runtime 替换为可检查的事务替身。

    Args:
        monkeypatch: pytest 提供的属性替换工具。
        db: 由测试配置 execute 返回值的 SQLAlchemy session 替身。
    """
    db_kind = SimpleNamespace(POSTGRES="postgres")
    tx_scope = MagicMock(return_value=nullcontext(db))
    monkeypatch.setattr(
        repository_module,
        "_db_runtime",
        MagicMock(return_value=(db_kind, tx_scope)),
    )


def test_type_sprite_repository_resolves_identifier_to_fixed_postgres_asset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """属性 repository 只能从固定 Sword/Shield 路径读取有效 BYTEA。

    测试断言 SQL 通过 ``poke_raw.types.id`` 生成数字文件名，并且目录前缀作为服务端
    固定绑定参数传入；用户只提供 identifier，不能把任意 raw 相对路径注入查询。
    """
    result = MagicMock()
    result.first.return_value = SimpleNamespace(
        _mapping={
            "asset_id": 42,
            "type_identifier": "electric",
            "mime_type": "image/png",
            "sha256": "abc123",
            "content": memoryview(b"type-png"),
        }
    )
    db = MagicMock()
    db.execute.return_value = result
    _install_db(monkeypatch, db)

    asset = repository_module.RawTypeSpriteRepository().get_type_sprite(
        type_identifier="electric",
    )

    statement, params = db.execute.call_args.args
    normalized_sql = " ".join(str(statement).split())
    assert "FROM poke_raw.types type_row" in normalized_sql
    assert "JOIN poke_raw.sprite_assets raw" in normalized_sql
    assert ":path_prefix || type_row.id::text || '.png'" in normalized_sql
    assert "raw.asset_category = 'types'" in normalized_sql
    assert "raw.is_active IS TRUE" in normalized_sql
    assert params == {
        "path_prefix": "types/generation-viii/sword-shield/",
        "type_identifier": "electric",
    }
    assert asset is not None
    assert asset.asset_id == 42
    assert asset.type_identifier == "electric"
    assert asset.content == b"type-png"


def test_type_sprite_repository_returns_none_when_asset_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """属性或有效图片不存在时返回 None，由 application/API 统一转换成 404。"""
    result = MagicMock()
    result.first.return_value = None
    db = MagicMock()
    db.execute.return_value = result
    _install_db(monkeypatch, db)

    asset = repository_module.RawTypeSpriteRepository().get_type_sprite(
        type_identifier="shadow",
    )

    assert asset is None
