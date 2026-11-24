"""离线把现有 ORM 类型及原物化视图编译成 Go 初始化器的固定 SQL/CSV 合同。"""

from __future__ import annotations

import argparse
import csv
import hashlib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, Integer
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from pokeop.persistence.base import RawBase
from pokeop.persistence.views.registry import MATERIALIZED_VIEWS


class ColumnKind(StrEnum):
    """冻结旧 CSV DAO 真正实现的三个类型转换分支。"""

    INTEGER = "integer"
    BOOLEAN = "boolean"
    TEXT = "text"


class ColumnContract(BaseModel):
    """声明单列的固定名称和旧导入类型，不保留 SQLAlchemy 动态对象。"""

    model_config = ConfigDict(frozen=True)
    name: str
    kind: ColumnKind


class CSVTableContract(BaseModel):
    """声明一份固定来源 CSV 与目标表、列顺序及摘要。"""

    model_config = ConfigDict(frozen=True)
    name: str
    relative_path: str
    sha256: str
    parsed_sha256: str
    columns: tuple[ColumnContract, ...]


class KnowledgeContract(BaseModel):
    """Go 初始化器读取的版本化资源清单；所有路径相对固定 PokeAPI CSV 根目录。"""

    model_config = ConfigDict(frozen=True)
    schema_version: int = 1
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str = "LICENSE.pokeapi.txt"
    raw_table_count: int
    raw_schema_sha256: str
    views_sha256: str
    license_sha256: str
    tables: tuple[CSVTableContract, ...]


class _KnowledgeExporter:
    """只读取当前仓库拥有的模型/SQL/许可，输出可审查的 Go 静态初始化资源。"""

    def __init__(self, repository: Path, source_commit: str) -> None:
        """保存 repository、已由调用方核对的 source_commit 和 CSV 根目录；不连接数据库。"""
        self._repository = repository
        self._source = repository / "submodules/pokeapi"
        self._csv = self._source / "data/v2/csv"
        self._source_commit = source_commit

    @staticmethod
    def _column(column: Column[object]) -> ColumnContract:
        """把 ORM column 边界收口为固定类型；空值语义由原 DAO 决定。"""
        if isinstance(column.type, Boolean):
            kind = ColumnKind.BOOLEAN
        elif isinstance(column.type, Integer):
            kind = ColumnKind.INTEGER
        else:
            kind = ColumnKind.TEXT
        return ColumnContract(name=column.name, kind=kind)

    def _tables(self) -> tuple[CSVTableContract, ...]:
        """按原 bootstrap 的相对路径展平规则定位全部 CSV，缺少模型立即失败。"""
        tables: list[CSVTableContract] = []
        for path in sorted(self._csv.rglob("*.csv")):
            relative = path.relative_to(self._csv)
            name = "_".join(relative.with_suffix("").parts)
            table = RawBase.metadata.tables[f"poke_raw.{name}"]
            columns = tuple(self._column(column) for column in table.columns)
            tables.append(CSVTableContract(
                name=name,
                relative_path=relative.as_posix(),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                parsed_sha256=self._parsed_digest(path, columns),
                columns=columns,
            ))
        return tuple(tables)

    @staticmethod
    def _parsed_digest(path: Path, columns: tuple[ColumnContract, ...]) -> str:
        """按原 Python DictReader/DAO 语义生成逐值长度前缀摘要，锁定非标准引号及空值语义。"""
        digest = hashlib.sha256()
        with path.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                for column in columns:
                    raw = row.get(column.name, "")
                    if raw is None:
                        raise ValueError(f"unexpected missing CSV field: {path.name}/{column.name}")
                    if column.kind is ColumnKind.INTEGER:
                        normalized = str(int(raw or "0"))
                    elif column.kind is ColumnKind.BOOLEAN:
                        value = raw.strip().lower()
                        normalized = "0" if value in {"", "0", "f", "false", "n", "no"} else "1"
                    else:
                        normalized = raw
                    data = normalized.encode("utf-8")
                    digest.update(len(data).to_bytes(8, "big"))
                    digest.update(data)
        return digest.hexdigest()

    @staticmethod
    def _raw_sql() -> str:
        """编译全部 raw 表的 additive DDL；不读取或执行参考快照，不包含 DROP。"""
        dialect = postgresql.dialect()
        statements = ["CREATE SCHEMA IF NOT EXISTS poke_raw;"]
        for table in RawBase.metadata.sorted_tables:
            statements.append(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip() + ";")
            statements.extend(
                str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect)).strip() + ";"
                for index in sorted(table.indexes, key=lambda value: value.name or "")
            )
        sql = "-- Generated from owning RawBase metadata; regenerate with export-go-knowledge.py.\n" + "\n\n".join(statements)
        return "\n".join(line.rstrip() for line in sql.splitlines()) + "\n"

    @staticmethod
    def _views_sql() -> str:
        """按原依赖顺序复制创建语义和索引；已有物化视图保持不变。"""
        statements = ["CREATE SCHEMA IF NOT EXISTS poke_champion;"]
        for view in MATERIALIZED_VIEWS:
            statements.append(view.create_sql() + ";")
            statements.extend(index + ";" for index in view.indexes)
        sql = "-- Generated from owning materialized-view registry and SQL.\n" + "\n\n".join(statements)
        return "\n".join(line.rstrip() for line in sql.splitlines()) + "\n"

    def export(self, output: Path) -> None:
        """把 SQL、声明式资源清单和完整许可写入 output，不修改来源数据。"""
        # 注册拥有表定义的包；这两次导入不注册运行时数据库或触发连接。
        import pokeop.persistence.raw.models  # noqa: F401
        import pokeop.persistence.assets.models  # noqa: F401

        raw_sql = self._raw_sql().encode("utf-8")
        views_sql = self._views_sql().encode("utf-8")
        license_text = (self._source / "LICENSE.md").read_bytes()
        contract = KnowledgeContract(
            source_commit=self._source_commit,
            raw_table_count=len(RawBase.metadata.tables),
            raw_schema_sha256=hashlib.sha256(raw_sql).hexdigest(),
            views_sha256=hashlib.sha256(views_sql).hexdigest(),
            license_sha256=hashlib.sha256(license_text).hexdigest(),
            tables=self._tables(),
        )
        output.mkdir(parents=True, exist_ok=True)
        (output / "raw-schema.sql").write_bytes(raw_sql)
        (output / "views.sql").write_bytes(views_sql)
        (output / "LICENSE.pokeapi.txt").write_bytes(license_text)
        (output / "manifest.json").write_text(contract.model_dump_json(indent=2) + "\n", encoding="utf-8")
        print(f"Exported {contract.raw_table_count} raw tables, {len(contract.tables)} CSV contracts and {len(MATERIALIZED_VIEWS)} materialized views.")


def main() -> None:
    """读取 --output-dir 并运行离线导出；失败通过非零退出码交给构建调用方。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    arguments = parser.parse_args()
    _KnowledgeExporter(Path(__file__).resolve().parents[2], arguments.source_commit).export(arguments.output_dir)


if __name__ == "__main__":
    main()
