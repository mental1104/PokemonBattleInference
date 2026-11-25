from __future__ import annotations

from enum import Enum


class DBSchema(str, Enum):
    """列出项目显式管理的 PostgreSQL schema。"""

    POKE_RAW = "poke_raw"
    POKE_RUNTIME = "poke_runtime"
    APP = "app"
    AUDIT = "audit"
