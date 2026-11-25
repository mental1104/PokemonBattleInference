from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from sqlalchemy import text


SQL_DIR = Path(__file__).resolve().parent / "sql"


@dataclass(frozen=True)
class MaterializedView:
    schema: str
    name: str
    select_sql: str
    indexes: Sequence[str] = field(default_factory=tuple)
    comment: str | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.schema}.{self.name}"

    def load_select_sql(self) -> str:
        sql_path = SQL_DIR / self.select_sql
        return sql_path.read_text(encoding="utf-8").strip().rstrip(";")

    def create_sql(self) -> str:
        return (
            f"CREATE MATERIALIZED VIEW IF NOT EXISTS {self.qualified_name} AS\n"
            f"{self.load_select_sql()}\n"
            "WITH DATA"
        )

    def drop_sql(self) -> str:
        return f"DROP MATERIALIZED VIEW IF EXISTS {self.qualified_name} CASCADE"

    def refresh_sql(self, *, concurrently: bool = False) -> str:
        mode = " CONCURRENTLY" if concurrently else ""
        return f"REFRESH MATERIALIZED VIEW{mode} {self.qualified_name}"


def _execute_statements(statements: Iterable[str]) -> None:
    from mental1104.db import DBKind, tx_scope

    with tx_scope(DBKind.POSTGRES) as db:
        for statement in statements:
            db.execute(text(statement))


def create_schemas(views: Sequence[MaterializedView]) -> None:
    schemas = sorted({view.schema for view in views})
    _execute_statements(f"CREATE SCHEMA IF NOT EXISTS {schema}" for schema in schemas)


def create_all(views: Sequence[MaterializedView]) -> None:
    create_schemas(views)
    statements: list[str] = []
    for view in views:
        statements.append(view.create_sql())
        statements.extend(view.indexes)
        if view.comment:
            escaped = view.comment.replace("'", "''")
            statements.append(f"COMMENT ON MATERIALIZED VIEW {view.qualified_name} IS '{escaped}'")
    _execute_statements(statements)


def drop_all(views: Sequence[MaterializedView]) -> None:
    _execute_statements(view.drop_sql() for view in reversed(views))


def recreate_all(views: Sequence[MaterializedView]) -> None:
    drop_all(views)
    create_all(views)


def refresh_all(views: Sequence[MaterializedView], *, concurrently: bool = False) -> None:
    _execute_statements(view.refresh_sql(concurrently=concurrently) for view in views)
