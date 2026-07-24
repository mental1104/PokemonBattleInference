from __future__ import annotations
from enum import Enum

class DBSchema(str, Enum):
    POKE_RAW = "poke_raw"
    APP = "app"
    AUDIT = "audit"
