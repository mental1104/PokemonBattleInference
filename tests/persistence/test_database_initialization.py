from __future__ import annotations

from unittest.mock import Mock
from pathlib import Path

from pokeop.persistence.commands import initialize_database as command


def test_initialize_database_prepares_regenerable_assets(monkeypatch) -> None:
    """一次性命令应使用幂等参数准备 raw tables、CSV 和物化视图。

    该断言保护 Compose Job 的稳定职责：正常启动只做可重复的资产准备，不调用
    破坏性 reset，也不在这里创建或迁移 `app`、`audit` 用户配置表。

    Args:
        monkeypatch: pytest 提供的属性替换夹具，用于隔离真实 PostgreSQL。
    """
    init_db = Mock()
    monkeypatch.setattr(command, "init_db", init_db)
    monkeypatch.setattr(command, "_sprites_source_dir", lambda: Path("/data/pokeapi-sprites"))

    command.initialize_database()

    init_db.assert_called_once_with(
        create_tables=True,
        import_csv=True,
        import_sprites=True,
        sprites_dir=Path("/data/pokeapi-sprites"),
        create_materialized_views=True,
        refresh_materialized_views=True,
    )
