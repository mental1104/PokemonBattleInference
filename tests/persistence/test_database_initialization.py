from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

from pokeop.persistence import bootstrap
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


def test_postgres_conn_params_allows_passwordless_compose_trust_auth(monkeypatch) -> None:
    """本地 Compose 初始化允许不设置 `PGPASSWORD`。

    当前 Compose 只把 PostgreSQL 发布到 `127.0.0.1`，并通过容器内 trust 认证支撑
    可再生资产导入；该场景不应为了满足 Python 读取环境变量而重新把密码写回
    Compose 配置。测试直接保护 bootstrap 连接参数组装边界：host、port、database
    和 user 仍是必填，只有 password 可以在缺省时进入 shared common 的 `None` 路径。

    Args:
        monkeypatch: pytest 提供的环境变量替换夹具，用于隔离开发机真实 PostgreSQL 设置。
    """
    monkeypatch.setenv("PGHOST", "postgres")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGDATABASE", "pokemon_battle_inference")
    monkeypatch.setenv("PGUSER", "pokeop")
    monkeypatch.delenv("PGPASSWORD", raising=False)

    params = bootstrap._postgres_conn_params_from_env(SimpleNamespace)

    assert params.ip == "postgres"
    assert params.port == 5432
    assert params.database == "pokemon_battle_inference"
    assert params.user == "pokeop"
    assert params.password is None


def test_register_postgres_runtime_only_registers_default_connection(monkeypatch) -> None:
    """backend 启动只注册当前进程数据库连接，不执行资产初始化副作用。

    HTTP 服务的职责是读取 `db-init` 已经准备好的物化视图；如果启动阶段误调用建表、
    CSV 导入或物化视图刷新，多 worker 与滚动部署都会重新触发重型数据库写入。本测试用
    fake runtime 验证 `register_postgres_runtime` 只把标准 PG 环境组装成连接参数，并以
    `create=False` 注册到 shared common registry。

    Args:
        monkeypatch: pytest 提供的替换夹具，用于隔离真实 `mental1104.db` registry。
    """
    register_db_and_create = Mock()
    db_kind = SimpleNamespace(POSTGRES="postgres")
    monkeypatch.setenv("PGHOST", "postgres")
    monkeypatch.setenv("PGPORT", "5432")
    monkeypatch.setenv("PGDATABASE", "pokemon_battle_inference")
    monkeypatch.setenv("PGUSER", "pokeop")
    monkeypatch.delenv("PGPASSWORD", raising=False)
    monkeypatch.setattr(
        bootstrap,
        "_db_runtime",
        lambda: (SimpleNamespace, db_kind, register_db_and_create, object()),
    )

    bootstrap.register_postgres_runtime()

    register_db_and_create.assert_called_once()
    args, kwargs = register_db_and_create.call_args
    assert args == ("postgres",)
    assert kwargs["db_name"] == "default"
    assert kwargs["base"] is bootstrap.RawBase
    assert kwargs["create"] is False
    assert kwargs["allow_overwrite"] is True
    assert kwargs["params"].ip == "postgres"
    assert kwargs["params"].password is None
