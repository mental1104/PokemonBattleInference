"""创建业务运行时 PostgreSQL schema 和手写 SQLAlchemy 表。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from pokeop.persistence.base import RuntimeBase
from pokeop.persistence.schema.db_schema import DBSchema


def import_runtime_models() -> type[RuntimeBase]:
    """导入全部 poke_runtime SQLAlchemy model 并返回 metadata owner。

    Returns:
        已注册后台任务、进度和配置 case 表的 ``RuntimeBase``。
    """
    import pokeop.persistence.battle_inference.job_models  # noqa: F401

    return RuntimeBase


def create_runtime_tables(engine: Engine) -> None:
    """幂等创建 poke_runtime schema 和全部运行时表。

    Args:
        engine: 指向明确目标 PostgreSQL database 的 SQLAlchemy engine。

    Side Effects:
        在目标 database 创建 ``poke_runtime`` schema，并按 ``RuntimeBase.metadata``
        创建缺失表、约束和索引；不会删除或迁移已有数据。
    """
    runtime_base = import_runtime_models()
    with engine.begin() as connection:
        connection.execute(
            text(f"CREATE SCHEMA IF NOT EXISTS {DBSchema.POKE_RUNTIME.value}")
        )
    runtime_base.metadata.create_all(bind=engine)


__all__ = ["create_runtime_tables", "import_runtime_models"]
