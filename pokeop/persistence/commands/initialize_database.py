from __future__ import annotations

from pokeop.persistence.bootstrap import init_db


def initialize_database() -> None:
    """执行一次性 PostgreSQL 初始化流水线。

    当前阶段只准备可从 PokeAPI CSV 再生的 `poke_raw` 表和
    `poke_champion` 物化视图。该命令由 Compose `db-init` 一次性服务执行，
    FastAPI 进程不得调用它。

    未来接入 Alembic 时，应在本入口中先升级承载用户配置的 schema，再执行资产
    准备；不能把 migration 重新塞回 HTTP 服务生命周期。

    Side Effects:
        连接 PostgreSQL，按需创建 raw tables、导入 CSV，并创建尚不存在的物化视图。
    """
    init_db(
        create_tables=True,
        import_csv=True,
        create_materialized_views=True,
    )


def main() -> None:
    """运行数据库一次性初始化命令，并将失败通过进程退出码交给编排层处理。"""
    initialize_database()


if __name__ == "__main__":
    main()
