from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from pokeop.persistence.assets.importer import import_sprite_assets
from pokeop.persistence.assets.models import SpriteAsset, SpriteImportBatch
from pokeop.persistence.base import RawBase


@pytest.fixture()
def db_session():
    """创建带 poke_raw schema 的 SQLite session，验证 importer 事务语义。"""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _attach_poke_raw(dbapi_connection, _connection_record):
        """每个 SQLite 连接都 attach poke_raw，模拟 PostgreSQL schema 名称。"""
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS poke_raw")

    RawBase.metadata.create_all(bind=engine)
    with Session(engine) as session:
        yield session


def _write(path: Path, content: bytes) -> None:
    """写入测试用 sprite 文件，并确保父目录存在。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_import_sprites_inserts_all_files_and_skips_unchanged_manifest(
    tmp_path: Path,
    db_session: Session,
):
    """首次导入保存所有文件；manifest 未变化时跳过 BYTEA 重写。"""
    _write(tmp_path / "sprites" / "pokemon" / "212.png", b"scizor")
    _write(tmp_path / "sprites" / "items" / "master-ball.png", b"item")

    first = import_sprite_assets(db_session, source_root=tmp_path)
    db_session.commit()
    second = import_sprite_assets(db_session, source_root=tmp_path)

    assets = db_session.execute(select(SpriteAsset)).scalars().all()
    assert first.skipped is False
    assert first.inserted == 2
    assert second.skipped is True
    assert len(assets) == 2
    assert {asset.relative_path for asset in assets} == {
        "pokemon/212.png",
        "items/master-ball.png",
    }
    assert next(asset for asset in assets if asset.relative_path == "pokemon/212.png").content == b"scizor"


def test_import_sprites_updates_changed_file_and_deactivates_deleted_file(
    tmp_path: Path,
    db_session: Session,
):
    """单文件变化只更新对应资产，上游删除文件在完整成功导入后才失效。"""
    scizor = tmp_path / "sprites" / "pokemon" / "212.png"
    sylveon = tmp_path / "sprites" / "pokemon" / "700.png"
    _write(scizor, b"old")
    _write(sylveon, b"keep")
    import_sprite_assets(db_session, source_root=tmp_path)
    db_session.commit()

    _write(scizor, b"new")
    sylveon.unlink()
    result = import_sprite_assets(db_session, source_root=tmp_path)
    db_session.commit()

    scizor_asset = db_session.execute(
        select(SpriteAsset).where(SpriteAsset.relative_path == "pokemon/212.png")
    ).scalar_one()
    sylveon_asset = db_session.execute(
        select(SpriteAsset).where(SpriteAsset.relative_path == "pokemon/700.png")
    ).scalar_one()
    assert result.updated == 1
    assert scizor_asset.content == b"new"
    assert scizor_asset.is_active is True
    assert sylveon_asset.is_active is False


def test_failed_import_does_not_mark_batch_completed_or_deactivate_old_assets(
    tmp_path: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """导入中途失败时事务回滚，旧资产仍保持 active。"""
    _write(tmp_path / "sprites" / "pokemon" / "212.png", b"old")
    import_sprite_assets(db_session, source_root=tmp_path)
    db_session.commit()

    _write(tmp_path / "sprites" / "pokemon" / "212.png", b"new")
    _write(tmp_path / "sprites" / "pokemon" / "700.png", b"boom")

    original_read_bytes = Path.read_bytes

    def _fail_on_sylveon(path: Path) -> bytes:
        """模拟读取第二个文件时失败，触发 importer 事务回滚。"""
        if path.name == "700.png":
            raise OSError("read failed")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", _fail_on_sylveon)
    with pytest.raises(OSError):
        import_sprite_assets(db_session, source_root=tmp_path)
    db_session.rollback()

    completed_batches = db_session.execute(
        select(SpriteImportBatch).where(SpriteImportBatch.status == "completed")
    ).scalars().all()
    asset = db_session.execute(
        select(SpriteAsset).where(SpriteAsset.relative_path == "pokemon/212.png")
    ).scalar_one()
    assert len(completed_batches) == 1
    assert asset.content == b"old"
    assert asset.is_active is True
