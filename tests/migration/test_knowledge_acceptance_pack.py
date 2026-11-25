"""验证人工知识更新包的真实版本变化、事实保留和失败保护，不操作业务用户库。"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from tools.data.build_knowledge_acceptance_pack import build_knowledge_acceptance_pack
from tools.data.build_knowledge_pack import KnowledgeManifest

SOURCE = Path(__file__).resolve().parents[2] / "ios/Sources/PokemonAppSupport/Resources"


class TestKnowledgeAcceptancePack:
    """围绕交付生成器验证有效更新和故意损坏清单的边界，不复写客户端更新规则。"""

    def test_new_version_preserves_all_knowledge_facts(self, tmp_path: Path) -> None:
        """tmp_path为独占输出；逐表完整比较事实，源SQLite字节不变，新版本/实际摘要一致。"""
        before = (SOURCE / "knowledge.sqlite").read_bytes()
        original = KnowledgeManifest.model_validate_json((SOURCE / "manifest.json").read_text())
        output = tmp_path / "acceptance"
        manifest = build_knowledge_acceptance_pack(SOURCE, output)
        assert (SOURCE / "knowledge.sqlite").read_bytes() == before
        assert manifest.data_version == original.data_version + "-acceptance-r1"
        assert manifest.sqlite_sha256 != original.sqlite_sha256
        assert manifest.sqlite_sha256 == hashlib.sha256((output / "knowledge.sqlite").read_bytes()).hexdigest()
        assert manifest.byte_size == (output / "knowledge.sqlite").stat().st_size
        assert manifest.source_revision == original.source_revision
        assert manifest.input_sha256 == original.input_sha256
        assert manifest.sources == original.sources and manifest.counts == original.counts
        with (
            closing(sqlite3.connect(SOURCE / "knowledge.sqlite")) as source_db,
            closing(sqlite3.connect(output / "knowledge.sqlite")) as updated_db,
        ):
            for table in original.counts.model_fields:
                assert source_db.execute(f"SELECT * FROM {table} ORDER BY 1,2,3").fetchall() == updated_db.execute(
                    f"SELECT * FROM {table} ORDER BY 1,2,3"
                ).fetchall()
            assert updated_db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            assert updated_db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert updated_db.execute(
                "SELECT value FROM metadata WHERE key='data_version'"
            ).fetchall() == [(manifest.data_version,)]
        assert (output / "POKEAPI-LICENSE.txt").read_bytes() == (SOURCE / "POKEAPI-LICENSE.txt").read_bytes()
        assert "not a newer PokeAPI dataset" in (output / "ACCEPTANCE-NOTICE.txt").read_text()

    def test_bad_checksum_manifest_only_changes_digest(self, tmp_path: Path) -> None:
        """tmp_path为独占输出；负例与有效清单仅摘要不同，保证校验失败有明确归因。"""
        output = tmp_path / "acceptance"
        manifest = build_knowledge_acceptance_pack(SOURCE, output)
        bad = KnowledgeManifest.model_validate_json((output / "manifest-bad-sha.json").read_text())
        assert bad.sqlite_sha256 != manifest.sqlite_sha256
        assert bad.model_copy(update={"sqlite_sha256": manifest.sqlite_sha256}) == manifest
        assert {path.name for path in output.iterdir()} == {
            "knowledge.sqlite", "manifest.json", "manifest-bad-sha.json",
            "POKEAPI-LICENSE.txt", "ACCEPTANCE-NOTICE.txt",
        }

    def test_existing_output_is_never_overwritten(self, tmp_path: Path) -> None:
        """tmp_path内已有交付物时必须失败，原内容和目录项均保留。"""
        output = tmp_path / "existing"
        output.mkdir()
        (output / "keep.txt").write_text("keep")
        with pytest.raises(FileExistsError):
            build_knowledge_acceptance_pack(SOURCE, output)
        assert (output / "keep.txt").read_text() == "keep"
        assert [path.name for path in output.iterdir()] == ["keep.txt"]

    def test_corrupt_source_is_rejected_before_output(self, tmp_path: Path) -> None:
        """tmp_path中的损坏输入不能生成看似有效的目录，也不能改动原首装包。"""
        source = tmp_path / "source"
        source.mkdir()
        for name in ("manifest.json", "POKEAPI-LICENSE.txt"):
            shutil.copyfile(SOURCE / name, source / name)
        (source / "knowledge.sqlite").write_bytes(b"invalid SQLite source")
        output = tmp_path / "acceptance"
        with pytest.raises(ValueError, match="checksum mismatch"):
            build_knowledge_acceptance_pack(source, output)
        assert not output.exists()
