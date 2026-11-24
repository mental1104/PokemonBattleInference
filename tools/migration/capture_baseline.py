"""离线导出原 Python 的 HTTP 与 PostgreSQL schema 合同，不启动服务或连接数据库。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pokeop.main import create_app
from pokeop.persistence.base import RawBase
from pokeop.persistence.runtime_schema import import_runtime_models


def capture_baseline(output_dir: Path) -> None:
    """把参考实现的生成合同保存为可审查文件。

    Args:
        output_dir: 合同输出目录，可新建；已有同名快照会被重写。

    Side Effects:
        写入 OpenAPI、逐项路由列表、SQLAlchemy PostgreSQL DDL 及 SHA-256 清单。
        只编译 SQL，不执行任何 SQL，也不触发 FastAPI lifespan。
    """
    import pokeop.persistence.raw.models  # noqa: F401 - 注册固定版本的原始表。

    output_dir.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    (output_dir / "legacy-openapi.v1.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    routes = [
        f"{method.upper()}\t{path}\t{operation.get('operationId', '')}"
        for path, methods in schema["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "post", "put", "delete", "patch", "head", "options"}
    ]
    (output_dir / "legacy-routes.v1.tsv").write_text(
        "\n".join(sorted(routes)) + "\n", encoding="utf-8"
    )
    # RawBase 的生成模型和 RuntimeBase 的手写表都属于迁移基线，不能只记录运行时表。
    metadata_owners = (RawBase, import_runtime_models())
    statements: list[str] = []
    dialect = postgresql.dialect()
    for owner in metadata_owners:
        for table in owner.metadata.sorted_tables:
            statements.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";")
            statements.extend(
                str(CreateIndex(index).compile(dialect=dialect)).strip() + ";"
                for index in sorted(table.indexes, key=lambda value: value.name or "")
            )
    (output_dir / "legacy-schema.v1.sql").write_text(
        "-- Generated reference DDL only; do not execute as a migration.\n\n"
        + "\n\n".join(statements)
        + "\n",
        encoding="utf-8",
    )
    checksums = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}"
        for path in sorted(output_dir.glob("legacy-*"))
        if path.is_file()
    ]
    (output_dir / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"Captured {len(routes)} HTTP operations and {sum(len(owner.metadata.tables) for owner in metadata_owners)} tables.")


def main() -> None:
    """解析唯一输出目录参数，生成离线参考合同；输入或依赖错误直接失败。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    capture_baseline(args.output_dir)


if __name__ == "__main__":
    main()
