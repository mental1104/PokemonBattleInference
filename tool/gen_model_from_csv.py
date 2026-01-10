#!/usr/bin/env python3
# gen_sa_models_pkg.py
from __future__ import annotations

import csv
import keyword
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# 生成出来的代码将以这个包名作为“唯一根引用”
PKG_ROOT = "pokeop.model.poke_raw"

SAMPLE_ROWS = 300
BOOL_NAME_RE = re.compile(r"^(is_|has_|can_|should_|requires_)", re.I)
BOOL_VALUES = {"0", "1", "true", "false", "t", "f"}


@dataclass(frozen=True)
class Col:
    name: str
    py_attr: str
    sa_type: str  # "Integer" | "Boolean" | "Text"
    nullable: bool
    is_pk: bool   # 只有“第一个字段精确为 id”时才会为 True


@dataclass(frozen=True)
class Table:
    name: str
    module_name: str
    class_name: str
    cols: List[Col]


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


def safe_attr(name: str) -> str:
    n = re.sub(r"\W", "_", name)
    if not n:
        n = "col"
    if n[0].isdigit():
        n = "_" + n
    if keyword.iskeyword(n):
        n += "_"
    return n


def read_header_and_sample(csv_path: Path, limit: int) -> Tuple[List[str], List[List[str]]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        header = [h.strip() for h in next(r)]
        rows: List[List[str]] = []
        for i, row in enumerate(r):
            rows.append(row)
            if i + 1 >= limit:
                break
    return header, rows


def is_int_values(values: Sequence[str]) -> bool:
    non_empty = [v for v in values if v != ""]
    return bool(non_empty) and all(v.isdigit() for v in non_empty)


def is_bool_values(values: Sequence[str]) -> bool:
    non_empty = [v.lower() for v in values if v != ""]
    return bool(non_empty) and set(non_empty).issubset(BOOL_VALUES)


def infer_sa_type(col: str, values: Sequence[str]) -> str:
    # 仍保留类型推断（不涉及任何约束推断）
    if col == "id" or col.endswith("_id") or col in ("slot", "position", "order"):
        return "Integer"
    if BOOL_NAME_RE.match(col) and is_bool_values(values):
        return "Boolean"
    if is_int_values(values):
        return "Integer"
    return "Text"


def table_name_from_path(csv_dir: Path, csv_path: Path) -> str:
    rel = csv_path.relative_to(csv_dir).with_suffix("")
    return "_".join(rel.parts)


def build_tables(csv_dir: Path) -> List[Table]:
    csv_files = sorted(csv_dir.rglob("*.csv"))

    seen_modules: set[str] = set()
    tables: List[Table] = []

    for p in csv_files:
        tname = table_name_from_path(csv_dir, p)
        header, rows = read_header_and_sample(p, SAMPLE_ROWS)
        if not header:
            continue

        # 新规则：只有第一个字段精确为 "id" 才设置主键；否则完全不设 PK
        pk_col = "id" if header[0] == "id" else None

        values_by_col: Dict[str, List[str]] = {c: [] for c in header}
        for row in rows:
            for i, c in enumerate(header):
                values_by_col[c].append(row[i] if i < len(row) else "")

        cols: List[Col] = []
        for c in header:
            values = values_by_col[c]
            sa_type = infer_sa_type(c, values)
            nullable = any(v == "" for v in values)

            is_pk = (pk_col is not None and c == pk_col)
            if is_pk:
                # 主键列强制非空（只在这种唯一允许的 PK 情况下）
                nullable = False

            cols.append(
                Col(
                    name=c,
                    py_attr=safe_attr(c),
                    sa_type=sa_type,
                    nullable=nullable,
                    is_pk=is_pk,
                )
            )

        class_name = snake_to_pascal(tname)
        module_name = safe_ident(tname)

        if module_name in seen_modules:
            i = 2
            while f"{module_name}_{i}" in seen_modules:
                i += 1
            module_name = f"{module_name}_{i}"
        seen_modules.add(module_name)

        tables.append(
            Table(
                name=tname,
                module_name=module_name,
                class_name=class_name,
                cols=cols,
            )
        )

    return tables


def ensure_pkg_chain_inits(out_pkg: Path) -> None:
    """
    确保 out_pkg 及其上两级目录存在 __init__.py（通常是 poke_raw/ 和 model/）
    让 `pokeop.model.poke_raw` 绝对导入更稳。
    """
    for p in [out_pkg, out_pkg.parent, out_pkg.parent.parent]:
        if p.exists() and p.is_dir():
            init_py = p / "__init__.py"
            if not init_py.exists():
                init_py.write_text("", encoding="utf-8")


def emit_base_py() -> str:
    """
    生成包内 Base：直接别名为你项目里的 RawBase（metadata.schema 已固定为 DBSchema.POKE_RAW）
    """
    return "\n".join(
        [
            "# Auto-generated. DO NOT EDIT BY HAND.",
            "from __future__ import annotations",
            "",
            "from pokeop.infra.sa_base import RawBase as Base",
            "",
            "__all__ = ['Base']",
            "",
        ]
    )


def _table_needs_optional(t: Table) -> bool:
    # 只要存在 nullable 且非 pk 字段，就需要 Optional
    return any(c.nullable and not c.is_pk for c in t.cols)


def _collect_sa_imports(t: Table) -> List[str]:
    """
    只导入用到的 sqlalchemy 类型。
    注意：不生成任何 FK/PK 约束，因此不导入 ForeignKey / PrimaryKeyConstraint。
    """
    used_types = {c.sa_type for c in t.cols}
    sa_imports: List[str] = []
    for typ in ("Boolean", "Integer", "Text"):
        if typ in used_types:
            sa_imports.append(typ)
    if not sa_imports:
        sa_imports.append("Text")
    return sa_imports


def emit_model_py(t: Table) -> str:
    need_optional = _table_needs_optional(t)
    sa_imports = _collect_sa_imports(t)

    lines: List[str] = []
    lines.append("from __future__ import annotations")
    lines.append("")

    if need_optional:
        lines.append("from typing import Optional")
        lines.append("")

    lines.append(f"from sqlalchemy import {', '.join(sa_imports)}")
    lines.append("from sqlalchemy.orm import Mapped, mapped_column")
    lines.append("")
    lines.append(f"from {PKG_ROOT}.base import Base")
    lines.append("")
    lines.append("")
    lines.append(f"class {t.class_name}(Base):")
    lines.append(f"    __tablename__ = {t.name!r}")

    for c in t.cols:
        py_t = "int" if c.sa_type == "Integer" else "bool" if c.sa_type == "Boolean" else "str"
        ann = f"Optional[{py_t}]" if (need_optional and c.nullable and not c.is_pk) else py_t

        col_args: List[str] = []
        if c.is_pk:
            col_args.append("primary_key=True")
            # 不再显式写 nullable=...，交给 primary_key 语义 + 上面强制 nullable=False
        else:
            col_args.append(f"nullable={str(c.nullable)}")

        needs_name = (c.py_attr != c.name)
        if needs_name:
            lines.append(
                f'    {c.py_attr}: Mapped[{ann}] = mapped_column("{c.name}", {c.sa_type}, {", ".join(col_args)})'
            )
        else:
            lines.append(
                f"    {c.py_attr}: Mapped[{ann}] = mapped_column({c.sa_type}, {', '.join(col_args)})"
            )

    lines.append("")
    return "\n".join(lines)


def emit_init_py(tables: List[Table]) -> str:
    lines: List[str] = []
    lines.append("# Auto-generated. DO NOT EDIT BY HAND.")
    lines.append(f"from {PKG_ROOT}.base import Base")
    for t in tables:
        lines.append(f"from {PKG_ROOT}.{t.module_name} import {t.class_name}")
    lines.append("")

    all_names = ["Base"] + [t.class_name for t in tables]

    lines.append("# fmt: off")
    lines.append("__all__ = [")
    for n in all_names:
        lines.append(f"    {n!r},")
    lines.append("]")
    lines.append("# fmt: on")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python gen_sa_models_pkg.py <csv_dir> <out_pkg_dir>")

    csv_dir = Path(sys.argv[1]).resolve()
    out_pkg = Path(sys.argv[2]).resolve()
    out_pkg.mkdir(parents=True, exist_ok=True)

    ensure_pkg_chain_inits(out_pkg)

    tables = build_tables(csv_dir)

    (out_pkg / "base.py").write_text(emit_base_py(), encoding="utf-8")

    for t in tables:
        (out_pkg / f"{t.module_name}.py").write_text(emit_model_py(t), encoding="utf-8")

    (out_pkg / "__init__.py").write_text(emit_init_py(tables), encoding="utf-8")

    print(f"[gen] csv_dir={csv_dir}")
    print(f"[gen] out_pkg={out_pkg}")
    print(f"[gen] models={len(tables)}")
    print(f"[gen] pkg_root={PKG_ROOT}")


if __name__ == "__main__":
    main()
