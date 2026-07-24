from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from pokeop.persistence.schema.db_schema import DBSchema


class RawBase(DeclarativeBase):
    """承载可从 PokeAPI 静态资产重建的 poke_raw 表。"""

    metadata = MetaData(schema=DBSchema.POKE_RAW.value)


class RuntimeBase(DeclarativeBase):
    """承载不可从静态 CSV 重建的后台任务运行时表。"""

    metadata = MetaData(schema=DBSchema.POKE_RUNTIME.value)


class AppBase(DeclarativeBase):
    """承载既有 app schema 的 SQLAlchemy 模型。"""

    metadata = MetaData(schema=DBSchema.APP.value)


class AuditBase(DeclarativeBase):
    """承载既有 audit schema 的 SQLAlchemy 模型。"""

    metadata = MetaData(schema=DBSchema.AUDIT.value)
