# Auto-generated. DO NOT EDIT BY HAND.
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import Boolean, Integer
from sqlalchemy.dialects.postgresql import insert as pg_insert

from mental1104.db import AutoSessionDAO

BOOL_VALUES_TRUE = ['1', 't', 'true', 'y', 'yes']
BOOL_VALUES_FALSE = ['0', 'f', 'false', 'n', 'no']


def to_bool(v: str) -> bool:
    s = v.strip().lower()
    if s in BOOL_VALUES_TRUE:
        return True
    if s in BOOL_VALUES_FALSE:
        return False
    return bool(s)


class CSVImportDAO(AutoSessionDAO):
    """
    通用 CSV 导入 DAO 基类：子类只需要设置 _model。
    - 批量 insert
    - 可选 ON CONFLICT DO NOTHING（基于主键/联合主键）
    - Integer/Boolean/Text 简单类型转换
    """

    def add_all(
        self,
        csv_path: str | Path,
        *,
        db,
        batch_size: int = 5000,
        ignore_conflicts: bool = True,
    ) -> int:
        p = Path(csv_path)
        table = self._model.__table__
        cols = list(table.columns)
        pk_cols = [c.name for c in table.primary_key.columns]

        def convert(col, raw: str) -> Any:
            # 空值 → 默认值（按你的要求）
            if raw == "":
                typ = col.type
                if isinstance(typ, Integer):
                    return 0
                if isinstance(typ, Boolean):
                    return False
                # Text/String 一律用空串
                return ""

            typ = col.type
            if isinstance(typ, Integer):
                return int(raw)
            if isinstance(typ, Boolean):
                return to_bool(raw)
            return raw

        inserted = 0
        buf: List[Dict[str, Any]] = []

        with p.open('r', encoding='utf-8', newline='') as f:
            r = csv.DictReader(f)
            for row in r:
                data: Dict[str, Any] = {}
                for c in cols:
                    raw = row.get(c.name, '')
                    v = convert(c, raw)
                    if v is None and (not c.nullable):
                        raise ValueError(
                            f"CSV {p.name}: column '{c.name}' is NOT NULL but got empty"
                        )
                    data[c.name] = v

                buf.append(data)
                if len(buf) >= batch_size:
                    stmt = pg_insert(table).values(buf)
                    if ignore_conflicts and pk_cols:
                        stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
                    res = db.execute(stmt)
                    inserted += int(getattr(res, 'rowcount', 0) or 0)
                    buf.clear()

        if buf:
            stmt = pg_insert(table).values(buf)
            if ignore_conflicts and pk_cols:
                stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)
            res = db.execute(stmt)
            inserted += int(getattr(res, 'rowcount', 0) or 0)

        db.flush()
        return inserted


__all__ = ['to_bool', 'CSVImportDAO']
