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
        # 不依赖 create_all 是否包含它：这里兜底建 schema + 表
        db.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_IMPORT_SCHEMA}"))
        db.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {_IMPORT_SCHEMA}.{_IMPORT_TABLE} (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
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
            inserted = dao.add_all(  # type: ignore[attr-defined]
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

        # 2) 注册 +（可选）建表
        register_db_and_create(
            DBKind.POSTGRES,
            params=params,
            db_name=db_name,
            base=RawBase,
            create=create_tables,
            allow_overwrite=True,  # 避免多次导入/多进程触发重复注册时报错
        )

        # 3) （可选）导入 CSV（幂等）
        if import_csv:
            _import_all_csv(
                csv_dir=Path(csv_dir) if csv_dir is not None else _DEFAULT_CSV_DIR,
                force=force_import,
                batch_size=batch_size,
                ignore_conflicts=ignore_conflicts,
            )

        _inited = True
