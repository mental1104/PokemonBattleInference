from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Type

from sqlalchemy import text

from pokeop.persistence.base import RawBase

_DEFAULT_CSV_DIR = Path(__file__).resolve().parents[1] / "assets_data"
_DEFAULT_SPRITES_DIR = Path(__file__).resolve().parents[2] / "submodules" / "pokeapi-sprites"

_init_lock = threading.Lock()
_inited = False

# 导入幂等标记
_IMPORT_SCHEMA = "poke_raw"
_IMPORT_TABLE = "_csv_import_version"
_IMPORT_KEY = "poke_raw_csv_import_v1"


def _schema_name() -> str:
    """
    RawBase.metadata.schema 可能是 str，也可能是 Enum（如 DBSchema.POKE_RAW）。
    这里统一拿到最终的 schema 字符串。
    """
    s = RawBase.metadata.schema
    if s is None:
        return _IMPORT_SCHEMA
    v = getattr(s, "value", None)
    return v if isinstance(v, str) else str(s)


def _db_runtime():
    from mental1104.db import ConnParams, DBKind, register_db_and_create, tx_scope

    return ConnParams, DBKind, register_db_and_create, tx_scope


def _ensure_import_table(db) -> None:
    schema = _schema_name()
    db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.{_IMPORT_TABLE} (
                k VARCHAR PRIMARY KEY,
                v VARCHAR NOT NULL,
                imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    db.execute(
        text(
            f"""
            ALTER TABLE {schema}.{_IMPORT_TABLE}
            ADD COLUMN IF NOT EXISTS imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            """
        )
    )
    db.flush()


def _is_import_done(db, key: str) -> bool:
    _ensure_import_table(db)
    schema = _schema_name()
    result = db.execute(
        text(f"SELECT k FROM {schema}.{_IMPORT_TABLE} WHERE k = :key LIMIT 1"),
        {"key": key},
    )
    return result.scalar() is not None


def _mark_import_done(db, key: str, value: str) -> None:
    _ensure_import_table(db)
    schema = _schema_name()
    db.execute(
        text(
            f"""
            INSERT INTO {schema}.{_IMPORT_TABLE} (k, v, imported_at)
            VALUES (:key, :value, now())
            ON CONFLICT (k) DO UPDATE
            SET v = EXCLUDED.v,
                imported_at = now()
            """
        ),
        {"key": key, "value": value},
    )
    db.flush()


# -----------------------------
# CSV -> table_name
# -----------------------------

def _table_name_from_csv(csv_dir: Path, csv_path: Path) -> str:
    rel = csv_path.relative_to(csv_dir).with_suffix("")
    return "_".join(rel.parts)


# -----------------------------
# 建映射：table_name -> model；model -> dao_instance
# -----------------------------

def _build_tablename_to_model() -> Dict[str, Type]:
    tab2model: Dict[str, Type] = {}
    for mapper in RawBase.registry.mappers:
        cls = mapper.class_
        tname = getattr(cls, "__tablename__", None)
        if tname:
            tab2model[tname] = cls
    return tab2model


def _build_model_to_dao() -> Dict[Type, object]:
    """
    扫 DAO 包里所有 DAO 类，通过 dao_cls._model 精确映射。
    避免 module_name 冲突导致 *_2 后缀时“猜不到名字”。
    """
    import pokeop.persistence.raw.dao as dao_pkg  # noqa: F401
    from pokeop.persistence.raw.dao.common import CSVImportDAO

    mapping: Dict[Type, object] = {}

    names = getattr(dao_pkg, "__all__", None)
    if not names:
        names = [n for n in dir(dao_pkg) if n.endswith("DAO")]

    for n in names:
        obj = getattr(dao_pkg, n, None)
        if not isinstance(obj, type):
            continue
        if obj is CSVImportDAO:
            continue
        if not issubclass(obj, CSVImportDAO):
            continue
        model = getattr(obj, "_model", None)
        if model is None:
            continue
        mapping[model] = obj()  # 实例化
    return mapping


# -----------------------------
# schema 预创建（必须在 create_all 之前）
# -----------------------------

def _ensure_schema_before_create_all(schema: str) -> None:
    """
    前置条件：DB 已 register（create=False 也行）
    """
    _, DBKind, _, tx_scope = _db_runtime()
    with tx_scope(DBKind.POSTGRES) as db:
        db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        db.flush()


# -----------------------------
# 导入主流程（一个事务内）
# -----------------------------

def _import_all_csv(
    *,
    csv_dir: Path,
    force: bool,
    batch_size: int,
    ignore_conflicts: bool,
) -> None:
    csv_dir = csv_dir.resolve()
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"csv_dir not found: {csv_dir}")

    tab2model = _build_tablename_to_model()
    model2dao = _build_model_to_dao()

    _, DBKind, _, tx_scope = _db_runtime()

    with tx_scope(DBKind.POSTGRES) as db:
        if (not force) and _is_import_done(db, _IMPORT_KEY):
            return

        ok = 0
        for csv_path in sorted(csv_dir.rglob("*.csv")):
            tname = _table_name_from_csv(csv_dir, csv_path)

            model = tab2model.get(tname)
            if model is None:
                raise RuntimeError(f"[import] no ORM model for table '{tname}' (csv={csv_path})")

            dao = model2dao.get(model)
            if dao is None:
                raise RuntimeError(f"[import] no DAO for model '{model.__name__}' (table={tname})")

            # 关键：依赖 AutoSessionDAO 注入 db（和你 demo 一致）
            dao.add_all(  # type: ignore[attr-defined]
                csv_path,
                db=db,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
            )
            ok += 1

        _mark_import_done(db, _IMPORT_KEY, f"done tables={ok}")


def _run_materialized_view_actions(
    *,
    create_materialized_views: bool,
    recreate_materialized_views: bool,
    refresh_materialized_views: bool,
) -> None:
    if not (create_materialized_views or recreate_materialized_views or refresh_materialized_views):
        return

    from pokeop.persistence.views import (
        create_materialized_views as _create_materialized_views,
        recreate_materialized_views as _recreate_materialized_views,
        refresh_materialized_views as _refresh_materialized_views,
    )

    if recreate_materialized_views:
        _recreate_materialized_views()
    elif create_materialized_views:
        _create_materialized_views()

    if refresh_materialized_views:
        _refresh_materialized_views()


def _import_all_sprites(
    *,
    sprites_dir: Path,
    source_commit: str | None,
) -> bool:
    """在一个事务内导入 sprites 二进制资产。

    Args:
        sprites_dir: PokeAPI/sprites submodule 根目录，或其中的 `sprites/` 目录。
        source_commit: 调用方传入的可选 submodule commit；容器内不读取宿主机 git 元数据。

    Returns:
        manifest 未变化时返回 False；发生实际导入或清理时返回 True。
    """
    from pokeop.persistence.assets import import_sprite_assets

    _, DBKind, _, tx_scope = _db_runtime()
    with tx_scope(DBKind.POSTGRES) as db:
        result = import_sprite_assets(
            db,
            source_root=sprites_dir,
            source_commit=source_commit,
        )
    return not result.skipped


# -----------------------------
# init_db：注册/建表/可选导入
# -----------------------------

def init_db(
    *,
    db_name: str = "default",
    create_tables: bool = True,
    import_csv: bool = False,
    csv_dir: str | Path | None = None,
    import_sprites: bool | None = None,
    sprites_dir: str | Path | None = None,
    sprites_source_commit: str | None = None,
    force_import: bool = False,
    batch_size: int = 5000,
    ignore_conflicts: bool = True,
    create_materialized_views: bool = False,
    recreate_materialized_views: bool = False,
    refresh_materialized_views: bool = False,
) -> None:
    global _inited
    if _inited:
        if import_sprites or (import_sprites is None and os.environ.get("POKEOP_SPRITES_DIR")):
            changed = _import_all_sprites(
                sprites_dir=Path(
                    sprites_dir
                    if sprites_dir is not None
                    else os.environ.get("POKEOP_SPRITES_DIR", _DEFAULT_SPRITES_DIR)
                ),
                source_commit=sprites_source_commit or os.environ.get("POKEOP_SPRITES_COMMIT"),
            )
            refresh_materialized_views = refresh_materialized_views or changed
        _run_materialized_view_actions(
            create_materialized_views=create_materialized_views,
            recreate_materialized_views=recreate_materialized_views,
            refresh_materialized_views=refresh_materialized_views,
        )
        return

    with _init_lock:
        if _inited:
            if import_sprites or (import_sprites is None and os.environ.get("POKEOP_SPRITES_DIR")):
                changed = _import_all_sprites(
                    sprites_dir=Path(
                        sprites_dir
                        if sprites_dir is not None
                        else os.environ.get("POKEOP_SPRITES_DIR", _DEFAULT_SPRITES_DIR)
                    ),
                    source_commit=sprites_source_commit or os.environ.get("POKEOP_SPRITES_COMMIT"),
                )
                refresh_materialized_views = refresh_materialized_views or changed
            _run_materialized_view_actions(
                create_materialized_views=create_materialized_views,
                recreate_materialized_views=recreate_materialized_views,
                refresh_materialized_views=refresh_materialized_views,
            )
            return

        # 1) 先 import 所有 ORM 模型：让 RawBase.metadata 收集到全部表
        import pokeop.persistence.raw.models as _poke_raw_models  # noqa: F401
        import pokeop.persistence.assets.models as _poke_sprite_models  # noqa: F401
        # 也 import DAO 包，保证 __all__ 可用（不强依赖，但更稳）
        import pokeop.persistence.raw.dao as _poke_raw_daos  # noqa: F401

        ConnParams, DBKind, register_db_and_create, _ = _db_runtime()

        params = ConnParams(
            ip=os.environ["PGHOST"],
            port=int(os.environ["PGPORT"]),
            database=os.environ["PGDATABASE"],
            user=os.environ["PGUSER"],
            password=os.environ["PGPASSWORD"],
        )

        # 2) 先注册（create=False），拿到可用的 DB 连接能力
        register_db_and_create(
            DBKind.POSTGRES,
            params=params,
            db_name=db_name,
            base=RawBase,
            create=False,
            allow_overwrite=True,
        )

        # 3) 在 create_all 之前创建 schema（关键）
        schema = _schema_name()
        _ensure_schema_before_create_all(schema)

        # 4) 再触发 SQLAlchemy create_all（此时 schema 已存在）
        if create_tables:
            register_db_and_create(
                DBKind.POSTGRES,
                params=params,
                db_name=db_name,
                base=RawBase,
                create=True,
                allow_overwrite=True,
            )

        # 5) （可选）导入 CSV（幂等）
        if import_csv:
            _import_all_csv(
                csv_dir=Path(csv_dir) if csv_dir is not None else _DEFAULT_CSV_DIR,
                force=force_import,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
            )

        should_import_sprites = (
            import_sprites
            if import_sprites is not None
            else bool(os.environ.get("POKEOP_SPRITES_DIR"))
        )
        if should_import_sprites:
            changed = _import_all_sprites(
                sprites_dir=Path(
                    sprites_dir
                    if sprites_dir is not None
                    else os.environ.get("POKEOP_SPRITES_DIR", _DEFAULT_SPRITES_DIR)
                ),
                source_commit=sprites_source_commit or os.environ.get("POKEOP_SPRITES_COMMIT"),
            )
            refresh_materialized_views = refresh_materialized_views or changed

        _run_materialized_view_actions(
            create_materialized_views=create_materialized_views,
            recreate_materialized_views=recreate_materialized_views,
            refresh_materialized_views=refresh_materialized_views,
        )

        _inited = True
