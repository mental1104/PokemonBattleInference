"""独立核对PG导出的图片元数据与HDD快照正文；不导入应用解析器，也不持有数据库凭据。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class _SpriteFile:
    """CSV边界的固定四列；正文路径属于source_commit版本，长度和SHA由PG登记。"""

    source_commit: str
    relative_path: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class SpriteVerification:
    """一次完整独立核验的回执；数量/字节来自实际文件，清单摘要便于重启和恢复比较。"""

    rows: int
    bytes: int
    manifest_sha256: str
    source_commit: str


class _ManifestReader:
    """只负责把PG COPY CSV解码为固定记录，拒绝缺列/额外列，不泄露JSON形状到内部。"""

    @staticmethod
    def records(manifest: Path) -> Iterator[_SpriteFile]:
        """读取manifest的四列并逐行返回记录；CSV/数字错误使整次核验失败。"""
        with manifest.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            if next(reader, None) != [
                "source_commit", "relative_path", "sha256", "byte_size"
            ]:
                raise ValueError("invalid sprite manifest header")
            for row in reader:
                if len(row) != 4:
                    raise ValueError("invalid sprite manifest field count")
                yield _SpriteFile(row[0], row[1], row[2], int(row[3]))


class _SnapshotVerifier:
    """绑定一个显式快照父目录和预期版本，只读核验路径范围、长度及真实字节摘要。"""

    def __init__(self, root: Path, source_commit: str) -> None:
        """root必须为已有目录，source_commit必须为40位小写SHA；不创建任何文件。"""
        if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
            raise ValueError("invalid expected sprite source commit")
        self._root = root.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("sprite root is not a directory")
        self._commit = source_commit

    def verify(self, record: _SpriteFile) -> int:
        """核验一条已解码record，返回实际字节数；路径逃逸、缺失或内容不符均抛错。"""
        relative = PurePosixPath(record.relative_path)
        if (
            record.source_commit != self._commit
            or not record.relative_path
            or record.relative_path == "."
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != record.relative_path
            or record.byte_size < 0
            or re.fullmatch(r"[0-9a-f]{64}", record.sha256) is None
        ):
            raise ValueError("invalid sprite manifest record")
        filename = (
            self._root / record.source_commit / "sprites" / relative
        ).resolve(strict=True)
        if not filename.is_relative_to(self._root) or not filename.is_file():
            raise ValueError("sprite file escapes its snapshot root")
        if filename.stat().st_size != record.byte_size:
            raise ValueError("sprite file size differs from metadata")
        with filename.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != record.sha256:
            raise ValueError("sprite file checksum differs from metadata")
        return record.byte_size


def verify_sprite_files(
    manifest: Path, root: Path, expected_count: int, source_commit: str
) -> SpriteVerification:
    """独立读取所有登记文件，生成可归档的精确回执，不使用应用导入器的成功标记。

    Args:
        manifest: PG COPY导出的四列CSV，含表头；不会修改。
        root: HDD版本快照父目录，正文为<commit>/sprites/<relative_path>。
        expected_count: 固定Git树的文件数量，必须与全部唯一登记行一致。
        source_commit: 本次固定的40位小写Git SHA，拒绝混入其他版本。

    Returns:
        完整核验成功的行数、字节和清单SHA；任何错误直接失败，不返回部分PASS。
    """
    verifier = _SnapshotVerifier(root, source_commit)
    seen: set[str] = set()
    byte_count = 0
    for record in _ManifestReader.records(manifest):
        if record.relative_path in seen:
            raise ValueError("duplicate sprite manifest record")
        byte_count += verifier.verify(record)
        seen.add(record.relative_path)
    if len(seen) != expected_count:
        raise ValueError("sprite count differs from expected source tree")
    with manifest.open("rb") as handle:
        manifest_sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return SpriteVerification(len(seen), byte_count, manifest_sha256, source_commit)


def main() -> None:
    """解析独立文件核验参数，成功输出ASCII JSON；错误保留非零退出和原始原因。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--expected-count", required=True, type=int)
    parser.add_argument("--source-commit", required=True)
    arguments = parser.parse_args()
    report = verify_sprite_files(
        arguments.manifest, arguments.root, arguments.expected_count,
        arguments.source_commit,
    )
    print(json.dumps(asdict(report), sort_keys=True))


if __name__ == "__main__":
    main()
