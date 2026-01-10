#!/usr/bin/env python3
# gen_dao_from_csv.py
from __future__ import annotations

import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

MODEL_PKG_ROOT = "pokeop.model.poke_raw"

BOOL_VALUES_TRUE = {"1", "true", "t", "yes", "y"}
BOOL_VALUES_FALSE = {"0", "false", "f", "no", "n"}


@dataclass(frozen=True)
class Item:
    table_name: str
    module_name: str
    class_name: str
    dao_module: str
    dao_class: str


def snake_to_pascal(s: str) -> str:
    parts = [p for p in s.split("_") if p]
    out = "".join(p[:1].upper() + p[1:] for p in parts) or "T"
    if out[0].isdigit():
        out = "T" + out
    return out


def safe_ident(s: str) -> str:
    s2 = re.sub(r"\W", "_", s)
    if not s2:
        s2 = "t"
    if s2[0].isdigit():
        s2 = "t_" + s2
    if keyword.iskeyword(s2):
        s2 += "_"
    return s2.lower()


def table_name_from_path(csv_dir: Path, csv_path: Path) -> str:
    rel = csv_path.relative_to(csv_dir).with_suffix("")
    return "_".join(rel.parts)


def ensure_pkg_chain_inits(out_pkg: Path) -> None:
    for p in [out_pkg, out_pkg.parent, out_pkg.parent.parent]:
        if p.exists() and p.is_dir():
            init_py = p / "__init__.py"
            if not init_py.exists():
                init_py.write_text("", encoding="utf-8")


def collect_items(csv_dir: Path) -> List[Item]:
    items: List[Item] = []
    seen: set[str] = set()

    for csv_path in sorted(csv_dir.rglob("*.csv")):
        tname = table_name_from_path(csv_dir, csv_path)
        module_name = safe_ident(tname)

        # 与你的 model 生成器一致：module_name 冲突时追加 _2/_3...
        if module_name in seen:
            i = 2
            while f"{module_name}_{i}" in seen:
                i += 1
            module_name = f"{module_name}_{i}"
        seen.add(module_name)

        class_name = snake_to_pascal(tname)
        items.append(
            Item(
                table_name=tname,
                module_name=module_name,
                class_name=class_name,
                dao_module=f"{module_name}_dao",
                dao_class=f"{class_name}DAO",
            )
        )
    return items


def emit_common_py() -> str:
    # 把 to_bool + CSVImportDAO（含 add_all）统一放到 common.py
    return "\n".join(
        [
            "# Auto-generated. DO NOT EDIT BY HAND.",
            "from __future__ import annotations",
            "",
            "import csv",
            "from pathlib import Path",
            "from typing import Any, Dict, List",
            "",
            "from sqlalchemy import Boolean, Integer",
            "from sqlalchemy.dialects.postgresql import insert as pg_insert",
            "",
            "from mental1104.db import AutoSessionDAO",
            "",
            f"BOOL_VALUES_TRUE = {sorted(BOOL_VALUES_TRUE)!r}",
            f"BOOL_VALUES_FALSE = {sorted(BOOL_VALUES_FALSE)!r}",
            "",
            "",
            "def to_bool(v: str) -> bool:",
            "    s = v.strip().lower()",
            "    if s in BOOL_VALUES_TRUE:",
            "        return True",
            "    if s in BOOL_VALUES_FALSE:",
            "        return False",
            "    return bool(s)",
            "",
            "",
            "class CSVImportDAO(AutoSessionDAO):",
            "    \"\"\"",
            "    通用 CSV 导入 DAO 基类：子类只需要设置 _model。",
            "    - 批量 insert",
            "    - 可选 ON CONFLICT DO NOTHING（基于主键/联合主键）",
            "    - Integer/Boolean/Text 简单类型转换",
            "    \"\"\"",
            "",
            "    def add_all(",
            "        self,",
            "        csv_path: str | Path,",
            "        *,",
            "        db,",
            "        batch_size: int = 5000,",
            "        ignore_conflicts: bool = True,",
            "    ) -> int:",
            "        p = Path(csv_path)",
            "        table = self._model.__table__",
            "        cols = list(table.columns)",
            "        pk_cols = [c.name for c in table.primary_key.columns]",
            "",
            "        def convert(col, raw: str) -> Any:",
            "            if raw == \"\":",
            "                return None",
            "            typ = col.type",
            "            if isinstance(typ, Integer):",
            "                return int(raw)",
            "            if isinstance(typ, Boolean):",
            "                return to_bool(raw)",
            "            return raw",
            "",
            "        inserted = 0",
            "        buf: List[Dict[str, Any]] = []",
            "",
            "        with p.open('r', encoding='utf-8', newline='') as f:",
            "            r = csv.DictReader(f)",
            "            for row in r:",
            "                data: Dict[str, Any] = {}",
            "                for c in cols:",
            "                    raw = row.get(c.name, '')",
            "                    v = convert(c, raw)",
            "                    if v is None and (not c.nullable):",
            "                        raise ValueError(",
            "                            f\"CSV {p.name}: column '{c.name}' is NOT NULL but got empty\"",
            "                        )",
            "                    data[c.name] = v",
            "",
            "                buf.append(data)",
            "                if len(buf) >= batch_size:",
            "                    stmt = pg_insert(table).values(buf)",
            "                    if ignore_conflicts and pk_cols:",
            "                        stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)",
            "                    res = db.execute(stmt)",
            "                    inserted += int(getattr(res, 'rowcount', 0) or 0)",
            "                    buf.clear()",
            "",
            "        if buf:",
            "            stmt = pg_insert(table).values(buf)",
            "            if ignore_conflicts and pk_cols:",
            "                stmt = stmt.on_conflict_do_nothing(index_elements=pk_cols)",
            "            res = db.execute(stmt)",
            "            inserted += int(getattr(res, 'rowcount', 0) or 0)",
            "",
            "        db.flush()",
            "        return inserted",
            "",
            "",
            "__all__ = ['to_bool', 'CSVImportDAO']",
            "",
        ]
    )


def emit_dao_py(it: Item) -> str:
    # 每个 DAO 文件只绑定 _model；导入都从 common.py 来
    return "\n".join(
        [
            "# Auto-generated. DO NOT EDIT BY HAND.",
            "from __future__ import annotations",
            "",
            "from .common import CSVImportDAO",
            f"from {MODEL_PKG_ROOT}.{it.module_name} import {it.class_name}",
            "",
            "",
            f"class {it.dao_class}(CSVImportDAO):",
            f"    _model = {it.class_name}",
            "",
            "",
            f"__all__ = [{it.dao_class!r}]",
            "",
        ]
    )


def emit_init_py(items: List[Item]) -> str:
    lines: List[str] = []
    lines.append("# Auto-generated. DO NOT EDIT BY HAND.")
    lines.append("from .common import CSVImportDAO, to_bool")
    for it in items:
        lines.append(f"from .{it.dao_module} import {it.dao_class}")
    lines.append("")
    lines.append("# fmt: off")
    lines.append("__all__ = [")
    lines.append("    'CSVImportDAO',")
    lines.append("    'to_bool',")
    for it in items:
        lines.append(f"    {it.dao_class!r},")
    lines.append("]")
    lines.append("# fmt: on")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: python gen_dao_from_csv.py <csv_dir> <model_pkg_dir> <out_dao_pkg_dir>")

    csv_dir = Path(sys.argv[1]).resolve()
    model_pkg_dir = Path(sys.argv[2]).resolve()  # 保留签名，便于你未来做一致性校验
    out_dao_pkg = Path(sys.argv[3]).resolve()

    if not csv_dir.is_dir():
        raise SystemExit(f"csv_dir not found: {csv_dir}")
    if not model_pkg_dir.is_dir():
        raise SystemExit(f"model_pkg_dir not found: {model_pkg_dir}")

    out_dao_pkg.mkdir(parents=True, exist_ok=True)
    ensure_pkg_chain_inits(out_dao_pkg)

    items = collect_items(csv_dir)

    (out_dao_pkg / "common.py").write_text(emit_common_py(), encoding="utf-8")

    for it in items:
        (out_dao_pkg / f"{it.dao_module}.py").write_text(emit_dao_py(it), encoding="utf-8")

    (out_dao_pkg / "__init__.py").write_text(emit_init_py(items), encoding="utf-8")

    print(f"[gen] csv_dir={csv_dir}")
    print(f"[gen] model_pkg_dir={model_pkg_dir}")
    print(f"[gen] out_dao_pkg_dir={out_dao_pkg}")
    print(f"[gen] daos={len(items)}")


if __name__ == "__main__":
    main()
