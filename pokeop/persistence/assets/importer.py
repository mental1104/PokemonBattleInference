from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import mimetypes
from pathlib import Path

from sqlalchemy import func, select, update

from pokeop.persistence.assets.models import SpriteAsset, SpriteImportBatch
from pokeop.persistence.assets.path_parser import parse_sprite_path


@dataclass(frozen=True)
class _ManifestEntry:
    """导入前扫描到的一个文件摘要。

    Args:
        relative_path: 相对于 sprites 根目录的 POSIX 路径。
        absolute_path: 当前导入进程可读的实际文件路径。
        sha256: 文件内容摘要，用于判断是否变化。
        byte_size: 文件字节数。

    Returns:
        importer 内部使用的不可变 manifest 行。
    """

    relative_path: str
    absolute_path: Path
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class SpriteImportResult:
    """sprites 导入结果摘要。

    Args:
        manifest_hash: 本次完整扫描得到的稳定 manifest 摘要。
        skipped: True 表示上一个完成批次 manifest 相同，未重写 raw asset。
        files_seen: 本次扫描看到的文件数。
        inserted: 新增资产行数。
        updated: 内容或元数据变化后更新的资产行数。
        unchanged: 已存在且 sha256 未变化的资产行数。

    Returns:
        调用方可用于日志或测试断言的导入统计。
    """

    manifest_hash: str
    skipped: bool
    files_seen: int
    inserted: int
    updated: int
    unchanged: int


def _sprites_dir(source_root: str | Path) -> Path:
    """把调用方传入的数据源根目录规范化成实际扫描的 `sprites/` 目录。

    Args:
        source_root: PokeAPI/sprites submodule 根目录，或已经指向其中 `sprites/` 目录。

    Returns:
        存在且可扫描的 sprites 目录。

    Raises:
        FileNotFoundError: 传入路径不存在或未包含 sprites 文件目录。
    """
    root = Path(source_root).resolve()
    candidate = root / "sprites"
    if candidate.is_dir():
        return candidate
    if root.is_dir() and root.name == "sprites":
        return root
    raise FileNotFoundError(f"sprites directory not found under: {root}")


def _file_digest(path: Path) -> tuple[str, int]:
    """读取文件并返回 sha256 与字节数。

    Args:
        path: importer 从本地数据源扫描到的普通文件。

    Returns:
        `(sha256_hex, byte_size)`，用于 manifest 和单文件变化判断。
    """
    digest = sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _build_manifest(sprites_dir: Path) -> tuple[tuple[_ManifestEntry, ...], str]:
    """扫描 sprites 目录并计算稳定 manifest。

    Args:
        sprites_dir: 已规范化的 `sprites/` 目录。

    Returns:
        排序后的 manifest entries 与总 manifest hash。
    """
    entries: list[_ManifestEntry] = []
    for path in sorted(item for item in sprites_dir.rglob("*") if item.is_file()):
        relative_path = path.relative_to(sprites_dir).as_posix()
        file_hash, byte_size = _file_digest(path)
        entries.append(
            _ManifestEntry(
                relative_path=relative_path,
                absolute_path=path,
                sha256=file_hash,
                byte_size=byte_size,
            )
        )

    manifest_digest = sha256()
    for entry in entries:
        manifest_digest.update(entry.relative_path.encode("utf-8"))
        manifest_digest.update(b"\0")
        manifest_digest.update(entry.sha256.encode("ascii"))
        manifest_digest.update(b"\0")
        manifest_digest.update(str(entry.byte_size).encode("ascii"))
        manifest_digest.update(b"\n")
    return tuple(entries), manifest_digest.hexdigest()


def _latest_completed_manifest(db) -> str | None:
    """读取最近一次成功完成的 sprites manifest hash。

    Args:
        db: common tx_scope 提供的 SQLAlchemy session。

    Returns:
        最近完成批次的 manifest_hash；没有完成批次时返回 None。
    """
    return db.execute(
        select(SpriteImportBatch.manifest_hash)
        .where(SpriteImportBatch.status == "completed")
        .order_by(SpriteImportBatch.completed_at.desc(), SpriteImportBatch.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def _mime_type(relative_path: str) -> str:
    """根据扩展名推断浏览器响应使用的 MIME type。

    Args:
        relative_path: asset 的 POSIX 相对路径。

    Returns:
        可用于 HTTP Content-Type 的 MIME type；无法识别时返回
        `application/octet-stream`。
    """
    guessed, _ = mimetypes.guess_type(relative_path)
    return guessed or "application/octet-stream"


def import_sprite_assets(
    db,
    *,
    source_root: str | Path,
    source_commit: str | None = None,
) -> SpriteImportResult:
    """幂等导入 PokeAPI sprites 二进制资产。

    Args:
        db: 当前事务内的 SQLAlchemy session，调用方负责提交或回滚。
        source_root: PokeAPI/sprites submodule 根目录，或其中的 `sprites/` 目录。
        source_commit: 调用方可选传入的 submodule commit；容器内不要求读取 `.git`。

    Returns:
        本次导入统计；manifest 未变化时 `skipped=True` 且不会重写 BYTEA。

    Raises:
        FileNotFoundError: 数据源目录不存在。
        OSError: 文件读取失败时抛出，事务应回滚，批次不会标记完成。
    """
    sprites_dir = _sprites_dir(source_root)
    entries, manifest_hash = _build_manifest(sprites_dir)
    if _latest_completed_manifest(db) == manifest_hash:
        return SpriteImportResult(
            manifest_hash=manifest_hash,
            skipped=True,
            files_seen=len(entries),
            inserted=0,
            updated=0,
            unchanged=len(entries),
        )

    batch = SpriteImportBatch(
        manifest_hash=manifest_hash,
        source_commit=source_commit,
        status="running",
        files_seen=len(entries),
    )
    db.add(batch)
    db.flush()

    inserted = 0
    updated_count = 0
    unchanged = 0
    seen_paths: set[str] = set()

    for entry in entries:
        seen_paths.add(entry.relative_path)
        metadata = parse_sprite_path(entry.relative_path)
        existing = db.execute(
            select(SpriteAsset).where(SpriteAsset.relative_path == entry.relative_path).limit(1)
        ).scalar_one_or_none()
        values = {
            "asset_category": metadata.asset_category,
            "pokemon_id": metadata.pokemon_id,
            "generation_identifier": metadata.generation_identifier,
            "version_identifier": metadata.version_identifier,
            "collection": metadata.collection,
            "render_style": metadata.render_style,
            "sprite_slot": metadata.sprite_slot,
            "is_front": metadata.is_front,
            "is_back": metadata.is_back,
            "is_female": metadata.is_female,
            "is_shiny": metadata.is_shiny,
            "is_animated": metadata.is_animated,
            "parse_status": metadata.parse_status,
            "mime_type": _mime_type(entry.relative_path),
            "byte_size": entry.byte_size,
            "sha256": entry.sha256,
            "last_seen_batch_id": batch.id,
            "is_active": True,
        }
        if existing is None:
            db.add(
                SpriteAsset(
                    relative_path=entry.relative_path,
                    content=entry.absolute_path.read_bytes(),
                    first_seen_batch_id=batch.id,
                    **values,
                )
            )
            inserted += 1
            continue

        if existing.sha256 == entry.sha256:
            for key, value in values.items():
                setattr(existing, key, value)
            unchanged += 1
            continue

        for key, value in values.items():
            setattr(existing, key, value)
        existing.content = entry.absolute_path.read_bytes()
        updated_count += 1

    # 只有完整扫描和逐文件写入都成功后，才把上游已移除文件标记为 inactive。
    if seen_paths:
        db.execute(
            update(SpriteAsset)
            .where(SpriteAsset.relative_path.not_in(seen_paths))
            .values(is_active=False)
        )
    else:
        db.execute(update(SpriteAsset).values(is_active=False))

    batch.status = "completed"
    batch.completed_at = db.execute(select(func.now())).scalar_one()
    db.flush()
    return SpriteImportResult(
        manifest_hash=manifest_hash,
        skipped=False,
        files_seen=len(entries),
        inserted=inserted,
        updated=updated_count,
        unchanged=unchanged,
    )


__all__ = ["SpriteImportResult", "import_sprite_assets"]
