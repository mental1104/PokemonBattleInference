from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from pokeop.persistence.bootstrap import init_db
from pokeop.persistence.runtime_schema import create_runtime_tables


def _sprites_source_dir() -> Path:
    """选择一次性初始化命令可读取的 sprites 数据源目录。

    `POKEOP_SPRITES_DIR` 可以是单个路径，也可以用 `os.pathsep` 分隔多个候选路径。
    Compose 会同时挂载顶层 `submodules/pokeapi-sprites` 和嵌套
    `submodules/pokeapi/data/v2/sprites`；这里优先使用第一个实际包含 `sprites/`
    子目录的候选项，保证顶层 submodule 初始化前后都能幂等运行同一条命令。

    Returns:
        PokeAPI/sprites 仓库根目录，或已经指向其中 `sprites/` 的目录。

    Raises:
        FileNotFoundError: 所有候选路径都不存在或都不包含 sprites 文件目录。
    """
    raw_value = os.environ.get("POKEOP_SPRITES_DIR", "/data/pokeapi-sprites")
    candidates = [Path(value) for value in raw_value.split(os.pathsep) if value]
    for candidate in candidates:
        if (candidate / "sprites").is_dir() or (candidate.is_dir() and candidate.name == "sprites"):
            return candidate
    raise FileNotFoundError(
        "sprites directory not found in candidates: "
        + ", ".join(str(candidate) for candidate in candidates)
    )


def _postgres_url() -> URL:
    """从标准 PostgreSQL 环境变量构造 SQLAlchemy 连接 URL。

    `PGPASSWORD` 允许缺省或为空，以兼容本地 Compose 绑定在回环地址上的 trust 认证；
    host、port、database 和 user 仍然由初始化进程显式提供。

    Returns:
        使用 psycopg 驱动、指向当前 Compose PostgreSQL database 的 SQLAlchemy URL。

    Raises:
        KeyError: `PGHOST`、`PGPORT`、`PGDATABASE` 或 `PGUSER` 缺失时抛出。
        ValueError: `PGPORT` 不是整数时抛出。
    """
    return URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ.get("PGPASSWORD") or None,
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        database=os.environ["PGDATABASE"],
    )


def _prepare_runtime_tables() -> None:
    """幂等创建 `poke_runtime` schema 和后台任务运行时表。

    本函数只在一次性 `db-init` 进程中创建短生命周期 SQLAlchemy engine。无论建表成功
    还是抛出异常，都会释放连接池；FastAPI 和 worker 进程仍然只注册运行时连接，不承担
    数据库结构变更。

    Side Effects:
        连接当前 PostgreSQL database，创建缺失的 `poke_runtime` schema、表、约束和索引。

    Raises:
        SQLAlchemyError: 建立连接或创建运行时表失败时透传底层 SQLAlchemy 异常。
    """
    engine: Engine = create_engine(_postgres_url(), pool_pre_ping=True)
    try:
        create_runtime_tables(engine)
    finally:
        engine.dispose()


def initialize_database() -> None:
    """执行一次性 PostgreSQL 初始化流水线。

    先幂等补齐不可由静态资产再生的 `poke_runtime` 后台任务表，再准备可从 PokeAPI CSV
    和 sprites 再生的 `poke_raw` 表、二进制资产和 `poke_champion` 物化视图。该命令由
    Compose `db-init` 一次性服务执行，FastAPI 和 worker 进程不得调用它。

    未来接入 Alembic 时，应在本入口中先升级承载运行时任务或用户配置的 schema，再执行
    资产准备；不能把 migration 重新塞回 HTTP 服务生命周期。

    Side Effects:
        连接 PostgreSQL，创建运行时表，按需创建 raw tables、导入 CSV/sprites，并创建或
        刷新物化视图。
    """
    sprites_dir = _sprites_source_dir()
    _prepare_runtime_tables()
    init_db(
        create_tables=True,
        import_csv=True,
        import_sprites=True,
        sprites_dir=sprites_dir,
        create_materialized_views=True,
        refresh_materialized_views=True,
    )


def main() -> None:
    """运行数据库一次性初始化命令，并将失败通过进程退出码交给编排层处理。"""
    initialize_database()


if __name__ == "__main__":
    main()
