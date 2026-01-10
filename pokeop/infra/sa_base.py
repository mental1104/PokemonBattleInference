# infra/sa_base.py
from __future__ import annotations
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import MetaData
from pokeop.schema.db.db_schema import DBSchema


class RawBase(DeclarativeBase):
    metadata = MetaData(schema=DBSchema.POKE_RAW)

class AppBase(DeclarativeBase):
    metadata = MetaData(schema=DBSchema.APP)

class AuditBase(DeclarativeBase):
    metadata = MetaData(schema=DBSchema.AUDIT)
