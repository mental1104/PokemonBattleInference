from __future__ import annotations

from unittest.mock import MagicMock

from scripts.reset_postgres_db import drop_business_schemas


def test_drop_business_schemas_only_drops_regenerable_asset_schemas() -> None:
    """资产重建只删除三个可再生业务 schema。

    ``poke_champion``、``poke_runtime`` 与 ``poke_raw`` 都能由导入和初始化流程
    重建；``app``、``audit`` 以及未来新增的用户配置 schema 不在白名单中。
    """
    engine = MagicMock()
    connection = engine.begin.return_value.__enter__.return_value

    drop_business_schemas(engine)

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == [
        "DROP SCHEMA IF EXISTS poke_champion CASCADE",
        "DROP SCHEMA IF EXISTS poke_runtime CASCADE",
        "DROP SCHEMA IF EXISTS poke_raw CASCADE",
    ]
    assert all(" app " not in f" {statement} " for statement in statements)
    assert all(" audit " not in f" {statement} " for statement in statements)
