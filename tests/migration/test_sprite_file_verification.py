"""独立HDD核验工具的边界测试；全部输入与正文属于测试临时目录。"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from tools.migration.verify_sprite_files import verify_sprite_files

COMMIT = "a" * 40


def _fixture(directory: Path) -> tuple[Path, Path, Path]:
    """在directory写入一份真实正文和对应CSV，返回清单、快照父目录及正文路径。"""
    root = directory / "snapshots"
    filename = root / COMMIT / "sprites/pokemon/212.png"
    filename.parent.mkdir(parents=True)
    content = b"owned independent sprite bytes"
    filename.write_bytes(content)
    manifest = directory / "metadata.csv"
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source_commit", "relative_path", "sha256", "byte_size"])
        writer.writerow([
            COMMIT, "pokemon/212.png", hashlib.sha256(content).hexdigest(), len(content)
        ])
    return manifest, root, filename


class TestSpriteFileVerification:
    """完整性、数量、版本和路径边界必须全部满足；文件存在不能代替字节核验。"""

    def test_complete_verification(self, tmp_path: Path) -> None:
        """tmp_path拥有输入；真实读盘后核对全部回执字段与独立清单摘要。"""
        manifest, root, filename = _fixture(tmp_path)
        actual = verify_sprite_files(manifest, root, 1, COMMIT)
        assert actual.rows == 1
        assert actual.bytes == filename.stat().st_size
        assert actual.manifest_sha256 == hashlib.sha256(manifest.read_bytes()).hexdigest()
        assert actual.source_commit == COMMIT

    def test_same_size_corruption(self, tmp_path: Path) -> None:
        """同长度正文被修改也必须失败，不能只检查stat或PG自报的SHA。"""
        manifest, root, filename = _fixture(tmp_path)
        filename.write_bytes(b"x" * filename.stat().st_size)
        with pytest.raises(ValueError, match="checksum"):
            verify_sprite_files(manifest, root, 1, COMMIT)

    def test_wrong_size(self, tmp_path: Path) -> None:
        """长度变化必须在哈希之前明确拒绝。"""
        manifest, root, filename = _fixture(tmp_path)
        filename.write_bytes(b"short")
        with pytest.raises(ValueError, match="size"):
            verify_sprite_files(manifest, root, 1, COMMIT)

    def test_missing_file(self, tmp_path: Path) -> None:
        """缺失正文不能被认为元数据核验成功。"""
        manifest, root, filename = _fixture(tmp_path)
        filename.unlink()
        with pytest.raises(FileNotFoundError):
            verify_sprite_files(manifest, root, 1, COMMIT)

    def test_wrong_count_and_version(self, tmp_path: Path) -> None:
        """固定Git数量和来源版本均独立检查。"""
        manifest, root, _ = _fixture(tmp_path)
        with pytest.raises(ValueError, match="count"):
            verify_sprite_files(manifest, root, 2, COMMIT)
        with pytest.raises(ValueError, match="record"):
            verify_sprite_files(manifest, root, 1, "b" * 40)

    def test_duplicate_record(self, tmp_path: Path) -> None:
        """重复行不得通过累计数量伪装为两个不同文件。"""
        manifest, root, _ = _fixture(tmp_path)
        records = manifest.read_text().splitlines(keepends=True)
        manifest.write_text("".join([*records, records[1]]))
        with pytest.raises(ValueError, match="duplicate"):
            verify_sprite_files(manifest, root, 2, COMMIT)

    def test_escaping_symlink(self, tmp_path: Path) -> None:
        """外部文件即使长度/SHA正确也不可从快照根之外读取。"""
        manifest, root, filename = _fixture(tmp_path)
        outside = tmp_path / "outside"
        outside.write_bytes(filename.read_bytes())
        filename.unlink()
        filename.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes"):
            verify_sprite_files(manifest, root, 1, COMMIT)
