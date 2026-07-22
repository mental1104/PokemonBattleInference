from __future__ import annotations

from unittest.mock import MagicMock

from scripts.reset_postgres_db import drop_business_schemas


def test_drop_business_schemas_only_drops_regenerable_asset_schemas() -> None:
    """资产重建只能删除 `poke_champion` 和 `poke_raw` 两个白名单 schema。

    `app`、`audit` 以及未来新增的用户配置 schema 不在白名单中，因此不得出现在
    任何 `DROP SCHEMA` 语句里。
    """
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value

    drop_business_schemas(engine)

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == [
        "DROP SCHEMA IF EXISTS poke_champion CASCADE",
        "DROP SCHEMA IF EXISTS poke_raw CASCADE",
    ]
    assert all(" app " not in f" {statement} " for statement in statements)
    assert all(" audit " not in f" {statement} " for statement in statements)
