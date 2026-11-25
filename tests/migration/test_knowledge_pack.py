"""知识包与固定 CSV 的真实交付验证，不启动外部数据库或更改源数据。"""
from __future__ import annotations
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path
import pytest
from pokeop.domain.models.types import Type, TypeHelper
from tools.data.build_knowledge_pack import KnowledgeManifest, build_knowledge_pack

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "ios/Sources/PokemonAppSupport/Resources/knowledge.sqlite"
MANIFEST = PACK.with_name("manifest.json")


class TestKnowledgePack:
    """公开投影、原知识一致性与可恢复构建，和 Swift 安装测试形成不同职责证据。"""
    def test_bundled_checksum_and_original_type_chart(self) -> None:
        """完整验证字节摘要、外键、所有表数量及 324 项旧知识，不靠文件存在就判定通过。"""
        manifest = KnowledgeManifest.model_validate_json(MANIFEST.read_text())
        assert hashlib.sha256(PACK.read_bytes()).hexdigest() == manifest.sqlite_sha256
        assert PACK.stat().st_size == manifest.byte_size
        with closing(sqlite3.connect(PACK.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            for table, count in manifest.counts.model_dump().items():
                assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == count
            rows = connection.execute("SELECT attacking,defending,percent FROM type_efficacy ORDER BY attacking,defending").fetchall()
            assert len(rows) == 324
            assert all(percent == TypeHelper.get_type_efficacy(Type(first), Type(second)) for first, second, percent in rows)
            assert connection.execute("SELECT name FROM pokemon WHERE id=212").fetchone()[0] == "巨钳螳螂"
            assert connection.execute("SELECT power,pp,priority FROM moves WHERE id=418").fetchone() == (40, 30, 1)

    def test_rebuild_from_pinned_csv(self, tmp_path: Path) -> None:
        """tmp_path 为测试独占输出；按同一固定源重建，比较逻辑版本/数量和同环境字节确定性。"""
        source = ROOT / "submodules/pokeapi/data/v2/csv"
        if not (source / "pokemon.csv").is_file():
            pytest.skip("initialize the pinned pokeapi submodule to run knowledge rebuild validation")
        original = KnowledgeManifest.model_validate_json(MANIFEST.read_text())
        first = build_knowledge_pack(source, tmp_path / "first/knowledge.sqlite", original.source_revision)
        second = build_knowledge_pack(source, tmp_path / "second/knowledge.sqlite", original.source_revision)
        assert first.input_sha256 == original.input_sha256 and first.data_version == original.data_version
        assert first.sources == original.sources and first.counts == original.counts
        assert first.sqlite_sha256 == second.sqlite_sha256

    def test_failed_build_preserves_previous_artifact(self, tmp_path: Path) -> None:
        """tmp_path 为测试独占目录；源缺失时原交付文件不被覆盖或删除。"""
        output = tmp_path / "knowledge.sqlite"
        output.write_bytes(PACK.read_bytes())
        before = hashlib.sha256(output.read_bytes()).hexdigest()
        with pytest.raises(FileNotFoundError):
            build_knowledge_pack(tmp_path / "missing-source", output, "1" * 40)
        assert hashlib.sha256(output.read_bytes()).hexdigest() == before
