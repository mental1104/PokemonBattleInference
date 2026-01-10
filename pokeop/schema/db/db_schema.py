# infra/db_schema.py
from __future__ import annotations
from enum import Enum  # py>=3.11；若你是3.10用: from enum import Enum

class DBSchema(str, Enum):
    POKE_RAW = "poke_raw"
    APP = "app"
    AUDIT = "audit"

from pokeop.schema.db.db_schema import DBSchema  # py>=3.11；若你是3.10用: from pokeop.schema.db.db_schema import DBSchema
