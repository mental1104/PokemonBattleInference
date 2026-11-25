"""生成同源知识更新验收包；只改变测试版本标识，不修改知识事实、首装资源或用户数据库。"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from tools.data.build_knowledge_pack import KnowledgeManifest


class _AcceptancePackBuilder:
    """拥有只读首装来源，校验后向全新目录交付可更新版本和故意错误的SHA清单。"""

    def __init__(self, source: Path) -> None:
        """source包含首装SQLite、manifest和许可；构造不读取或修改文件。"""
        self._source = source

    def _validated_source(self) -> KnowledgeManifest:
        """完整校验来源字节、SQLite结构、版本及九表数量，返回具体合同模型。"""
        manifest = KnowledgeManifest.model_validate_json(
            (self._source / "manifest.json").read_text(encoding="utf-8")
        )
        database = self._source / "knowledge.sqlite"
        if (
            database.stat().st_size != manifest.byte_size
            or hashlib.sha256(database.read_bytes()).hexdigest() != manifest.sqlite_sha256
        ):
            raise ValueError("source knowledge checksum mismatch")
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            if (
                connection.execute("PRAGMA user_version").fetchall() != [(1,)]
                or connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]
                or connection.execute("PRAGMA foreign_key_check").fetchall()
                or connection.execute(
                    "SELECT value FROM metadata WHERE key='data_version'"
                ).fetchall() != [(manifest.data_version,)]
            ):
                raise ValueError("source knowledge metadata or integrity mismatch")
            counts = manifest.counts
            tables = (
                ("pokemon", counts.pokemon), ("pokemon_stats", counts.pokemon_stats),
                ("pokemon_types", counts.pokemon_types), ("pokemon_abilities", counts.pokemon_abilities),
                ("moves", counts.moves), ("types", counts.types), ("natures", counts.natures),
                ("abilities", counts.abilities), ("type_efficacy", counts.type_efficacy),
            )
            for table, count in tables:
                if connection.execute(f"SELECT count(*) FROM {table}").fetchall() != [(count,)]:
                    raise ValueError("source knowledge row count mismatch")
        return manifest

    @staticmethod
    def _manifest(source: KnowledgeManifest, version: str, digest: str, size: int) -> KnowledgeManifest:
        """保留source真实来源和数量，使用已写入数据库的version及实际digest/size构造清单。"""
        return KnowledgeManifest(
            data_version=version, source_revision=source.source_revision,
            input_sha256=source.input_sha256, sqlite_sha256=digest, byte_size=size,
            counts=source.counts, sources=source.sources,
        )

    def build(self, output: Path) -> KnowledgeManifest:
        """output必须为新目录；返回有效包清单，失败保留现场且不覆盖既有交付物。"""
        if output.exists():
            raise FileExistsError("acceptance output directory already exists")
        source = self._validated_source()
        license_text = (self._source / "POKEAPI-LICENSE.txt").read_text(encoding="utf-8")
        version = source.data_version + "-acceptance-r1"
        output.mkdir(parents=True)
        database = output / "knowledge.sqlite"
        shutil.copyfile(self._source / "knowledge.sqlite", database)
        # 唯一事实差异是metadata中的验收版本；知识表、源输入身份和首装文件全部保留。
        with closing(sqlite3.connect(database)) as connection, connection:
            changed = connection.execute(
                "UPDATE metadata SET value=? WHERE key='data_version'", (version,)
            ).rowcount
            if changed != 1:
                raise ValueError("acceptance version metadata update failed")
        manifest = self._manifest(
            source, version, hashlib.sha256(database.read_bytes()).hexdigest(), database.stat().st_size
        )
        (output / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        # 负例保持全部其他字段和真实正文，仅使用必然错误的摘要验证客户端拒绝安装。
        bad_digest = "0" * 64 if manifest.sqlite_sha256 != "0" * 64 else "1" * 64
        bad_manifest = self._manifest(source, version, bad_digest, manifest.byte_size)
        (output / "manifest-bad-sha.json").write_text(
            bad_manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        (output / "POKEAPI-LICENSE.txt").write_text(license_text, encoding="utf-8")
        (output / "ACCEPTANCE-NOTICE.txt").write_text(
            "Acceptance fixture only. Knowledge facts match the bundled pack.\n"
            "Only the metadata data_version changes; this is not a newer PokeAPI dataset.\n"
            "manifest-bad-sha.json intentionally fails checksum verification.\n",
            encoding="utf-8",
        )
        return manifest


def build_knowledge_acceptance_pack(source: Path, output: Path) -> KnowledgeManifest:
    """从source只读首装包生成output新验收目录，返回有效清单；不访问网络或用户数据。"""
    return _AcceptancePackBuilder(source).build(output)


def main() -> None:
    """解析来源/新输出目录，成功打印有效manifest；任何校验或文件错误使CLI非零退出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    manifest = build_knowledge_acceptance_pack(arguments.source, arguments.output)
    print(manifest.model_dump_json())


if __name__ == "__main__":
    main()
