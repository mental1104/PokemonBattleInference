#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, Integer, create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, URL


REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_PYTHON = REPO_ROOT / "submodules" / "common" / "python"
DEFAULT_CSV_DIR = REPO_ROOT / "pokeop" / "assets_data"
LOCAL_PG_HOSTS = {"localhost", "127.0.0.1", "::1"}

for path in (REPO_ROOT, COMMON_PYTHON):
    if path.exists() and str(path) not in sys.path:
        sys.path.insert(0, str(path))


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        key, sep, value = line.partition("=")
        if not sep:
            continue

        key = key.strip()
        value = value.strip().split(" #", 1)[0].strip().strip("'\"")
        os.environ.setdefault(key, value)


def require_pg_env() -> None:
    missing = [
        name
        for name in ("PGUSER", "PGPASSWORD", "PGHOST", "PGPORT", "PGDATABASE")
        if not os.environ.get(name)
    ]
    if missing:
        raise SystemExit(f"missing PostgreSQL environment variables: {', '.join(missing)}")


def require_localhost_unless_allowed(*, allow_remote_host: bool) -> None:
    host = os.environ["PGHOST"].strip().lower()
    if allow_remote_host or host in LOCAL_PG_HOSTS:
        return
    raise SystemExit(
        "refusing to reset a non-local PostgreSQL host "
        f"({os.environ['PGHOST']!r}); export PGHOST=localhost or pass "
        "--allow-remote-host if this is intentional"
    )


def postgres_url() -> URL:
    try:
        port = int(os.environ["PGPORT"])
    except ValueError as exc:
        raise SystemExit(f"PGPORT must be an integer: {os.environ['PGPORT']}") from exc

    return URL.create(
        "postgresql+psycopg2",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.environ["PGHOST"],
        port=port,
        database=os.environ["PGDATABASE"],
    )


def make_engine() -> Engine:
    return create_engine(postgres_url(), pool_pre_ping=True)


def connection_label() -> str:
    return (
        f"{os.environ['PGUSER']}@{os.environ['PGHOST']}:"
        f"{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )


def import_raw_models():
    """导入所有 poke_raw SQLAlchemy model，包括 generated CSV 表和手写资产表。"""
    import pokeop.persistence.raw.models  # noqa: F401
    import pokeop.persistence.assets.models  # noqa: F401
    from pokeop.persistence.base import RawBase

    return RawBase


def drop_business_schemas(engine: Engine) -> None:
    """删除可重建读取模型、运行时任务和 raw 数据 schema。

    Args:
        engine: 已通过本地/显式远端安全检查的目标 PostgreSQL engine。
    """
    from pokeop.persistence.schema.db_schema import DBSchema
    from pokeop.persistence.views.registry import CHAMPION_SCHEMA

    with engine.begin() as conn:
        for schema in (
            CHAMPION_SCHEMA,
            DBSchema.POKE_RUNTIME.value,
            DBSchema.POKE_RAW.value,
        ):
            conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def create_runtime_tables(engine: Engine) -> None:
    """创建 poke_runtime schema 中的后台任务运行时表。

    Args:
        engine: 指向 reset 目标 database 的 SQLAlchemy engine。
    """
    from pokeop.persistence.runtime_schema import create_runtime_tables as create_tables

    create_tables(engine)


def create_raw_tables(engine: Engine) -> None:
    from pokeop.persistence.schema.db_schema import DBSchema

    RawBase = import_raw_models()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {DBSchema.POKE_RAW.value}"))
    RawBase.metadata.create_all(bind=engine)


def table_name_from_csv(csv_dir: Path, csv_path: Path) -> str:
    return "_".join(csv_path.relative_to(csv_dir).with_suffix("").parts)


def convert_value(col, raw: str) -> Any:
    if raw == "":
        if isinstance(col.type, Integer):
            return 0
        if isinstance(col.type, Boolean):
            return False
        return ""
    if isinstance(col.type, Integer):
        return int(raw)
    if isinstance(col.type, Boolean):
        return raw.strip().lower() in {"1", "t", "true", "y", "yes"}
    return raw


def insert_batch(conn, table, rows: list[dict[str, Any]], *, ignore_conflicts: bool) -> int:
    if not rows:
        return 0

    stmt = pg_insert(table).values(rows)
    pk_cols = [col.name for col in table.primary_key.columns]
    if ignore_conflicts and pk_cols:
        stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
    result = conn.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


def import_csv_data(
    engine: Engine,
    *,
    csv_dir: Path,
    batch_size: int,
    ignore_conflicts: bool,
) -> int:
    RawBase = import_raw_models()
    csv_dir = csv_dir.resolve()
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"csv_dir not found: {csv_dir}")

    tables_by_name = {table.name: table for table in RawBase.metadata.tables.values()}
    imported_tables = 0

    with engine.begin() as conn:
        for csv_path in sorted(csv_dir.rglob("*.csv")):
            table_name = table_name_from_csv(csv_dir, csv_path)
            table = tables_by_name.get(table_name)
            if table is None:
                raise RuntimeError(f"no SQLAlchemy table for CSV: {csv_path}")

            cols = list(table.columns)
            rows: list[dict[str, Any]] = []
            with csv_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for csv_row in reader:
                    rows.append(
                        {
                            col.name: convert_value(col, csv_row.get(col.name, ""))
                            for col in cols
                        }
                    )
                    if len(rows) >= batch_size:
                        insert_batch(conn, table, rows, ignore_conflicts=ignore_conflicts)
                        rows.clear()

            insert_batch(conn, table, rows, ignore_conflicts=ignore_conflicts)
            imported_tables += 1

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS poke_raw._csv_import_version (
                    k VARCHAR PRIMARY KEY,
                    v VARCHAR NOT NULL,
                    imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO poke_raw._csv_import_version (k, v, imported_at)
                VALUES ('poke_raw_csv_import_v1', :value, now())
                ON CONFLICT (k) DO UPDATE
                SET v = EXCLUDED.v,
                    imported_at = now()
                """
            ),
            {"value": f"done tables={imported_tables}"},
        )

    return imported_tables


def create_materialized_views(engine: Engine) -> None:
    from pokeop.persistence.views.registry import MATERIALIZED_VIEWS

    with engine.begin() as conn:
        for schema in sorted({view.schema for view in MATERIALIZED_VIEWS}):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

        for view in MATERIALIZED_VIEWS:
            conn.execute(text(view.create_sql()))
            for index_sql in view.indexes:
                conn.execute(text(index_sql))
            if view.comment:
                escaped = view.comment.replace("'", "''")
                conn.execute(
                    text(
                        f"COMMENT ON MATERIALIZED VIEW {view.qualified_name} "
                        f"IS '{escaped}'"
                    )
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reset PokemonBattleInference PostgreSQL schemas in the current PGDATABASE, "
            "then recreate SQLAlchemy tables and import CSV data."
        )
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=REPO_ROOT / ".env",
        help="Load PG* variables from this file if they are not already exported.",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=DEFAULT_CSV_DIR,
        help="CSV root to import. Defaults to pokeop/assets_data.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=5000,
        help="Rows per CSV import batch.",
    )
    parser.add_argument(
        "--skip-csv-import",
        action="store_true",
        help="Only recreate SQLAlchemy tables.",
    )
    parser.add_argument(
        "--with-materialized-views",
        action="store_true",
        help="Also recreate Pokemon Champion materialized views.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the target connection and exit without changing PostgreSQL.",
    )
    parser.add_argument(
        "--allow-remote-host",
        action="store_true",
        help="Allow resetting a PostgreSQL host other than localhost/127.0.0.1.",
    )
    return parser.parse_args()


def main() -> None:
    """按安全检查、schema、raw 数据和可选视图顺序重建本地数据库。"""
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be greater than 0")

    load_env_file(args.env_file)
    require_pg_env()
    require_localhost_unless_allowed(allow_remote_host=args.allow_remote_host)

    print(f"target PostgreSQL: {connection_label()}")
    print("schemas to reset: poke_champion, poke_runtime, poke_raw")
    if args.dry_run:
        print("dry run only; no PostgreSQL changes were made")
        return

    engine = make_engine()
    try:
        drop_business_schemas(engine)
        print("dropped business schemas")

        create_runtime_tables(engine)
        print("created poke_runtime SQLAlchemy tables")

        create_raw_tables(engine)
        print("created poke_raw SQLAlchemy tables")

        if not args.skip_csv_import:
            imported_tables = import_csv_data(
                engine,
                csv_dir=args.csv_dir,
                batch_size=args.batch_size,
                ignore_conflicts=True,
            )
            print(f"imported CSV tables: {imported_tables}")

        if args.with_materialized_views:
            create_materialized_views(engine)
            print("created poke_champion materialized views")
    finally:
        engine.dispose()

    print("reset completed")


if __name__ == "__main__":
    main()
