from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Dict, Type

from sqlalchemy import String, select, text
from sqlalchemy.orm import Mapped, mapped_column

from mental1104.db import (
    AutoSessionDAO,
    ConnParams,
    DBKind,
    register_db_and_create,
    tx_scope,
)

from pokeop.infra.sa_base import RawBase

_DEFAULT_CSV_DIR = Path(__file__).resolve().parents[1] / "data"

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


# -----------------------------
# 导入版本表：用 ORM + DAO（走自动注入 db）
# -----------------------------

class _CSVImportVersion(RawBase):
    __tablename__ = _IMPORT_TABLE
    k: Mapped[str] = mapped_column(String, primary_key=True)
    v: Mapped[str] = mapped_column(String, nullable=False)


class _CSVImportVersionDAO(AutoSessionDAO):
    _model = _CSVImportVersion

    def ensure_table(self, *, db) -> None:
        # 仍然用 SQLAlchemy 方式创建（不写原生 CREATE TABLE），但 schema 必须先存在
        schema = _schema_name()
        db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        # SQLAlchemy DDL：checkfirst=True 幂等
        self._model.__table__.create(bind=db.get_bind(), checkfirst=True)
        db.flush()

    def is_done(self, key: str, *, db) -> bool:
        self.ensure_table()
        r = db.execute(select(self._model.k).where(self._model.k == key).limit(1))
        return r.scalar() is not None

    def mark_done(self, key: str, value: str, *, db) -> None:
        self.ensure_table()
        row = self._model(k=key, v=value)
        db.merge(row)
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
    import pokeop.dao.poke_raw as dao_pkg  # noqa: F401
    from pokeop.dao.poke_raw.common import CSVImportDAO

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

class _BootstrapDAO(AutoSessionDAO):
    def ensure_schema(self, schema: str, *, db) -> None:
        db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        db.flush()


def _ensure_schema_before_create_all(schema: str) -> None:
    """
    前置条件：DB 已 register（create=False 也行）
    """
    boot = _BootstrapDAO()
    with tx_scope(DBKind.POSTGRES):
        boot.ensure_schema(schema)


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

    ver = _CSVImportVersionDAO()

    with tx_scope(DBKind.POSTGRES):
        if (not force) and ver.is_done(_IMPORT_KEY):
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
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
            )
            ok += 1

        ver.mark_done(_IMPORT_KEY, f"done tables={ok}")


# -----------------------------
# init_db：注册/建表/可选导入
# -----------------------------

def init_db(
    *,
    db_name: str = "default",
    create_tables: bool = True,
    import_csv: bool = False,
    csv_dir: str | Path | None = None,
    force_import: bool = False,
    batch_size: int = 5000,
    ignore_conflicts: bool = True,
) -> None:
    global _inited
    if _inited:
        return

    with _init_lock:
        if _inited:
            return

        # 1) 先 import 所有 ORM 模型：让 RawBase.metadata 收集到全部表
        import pokeop.model.poke_raw as _poke_raw_models  # noqa: F401
        # 也 import DAO 包，保证 __all__ 可用（不强依赖，但更稳）
        import pokeop.dao.poke_raw as _poke_raw_daos  # noqa: F401

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

        _inited = True
