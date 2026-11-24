"""原 Python importer 与纯 Go BYTEA 导入及公开图片 HTTP 的真实差分。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from pokeop.persistence.assets.importer import import_sprite_assets
from pokeop.persistence.assets.models import SpriteAsset
from pokeop.persistence.base import RawBase


class _SpriteRecord(BaseModel):
    """两种持久化结果共有的完整业务行；数据库自增ID/时刻不参与值比较。"""

    model_config = ConfigDict(strict=True, from_attributes=True, frozen=True)

    relative_path: str
    asset_category: str
    pokemon_id: int | None
    generation_identifier: str | None
    version_identifier: str | None
    collection: str | None
    render_style: str | None
    sprite_slot: str | None
    is_front: bool | None
    is_back: bool | None
    is_female: bool | None
    is_shiny: bool | None
    is_animated: bool | None
    parse_status: Literal["parsed", "unparsed"]
    mime_type: str
    byte_size: int
    sha256: str
    content: bytes
    is_active: bool


class _SpriteReport(BaseModel):
    """原公开 SpriteImportResult 的固定边界，与 Go CLI 子回执逐字段比较。"""

    model_config = ConfigDict(strict=True, frozen=True)

    manifest_hash: str
    skipped: bool
    files_seen: int
    inserted: int
    updated: int
    unchanged: int


class _InitializationReport(BaseModel):
    """只读取 CLI 与本验收相关的 sprites 子回执，其余知识字段由独立验收负责。"""

    sprites: _SpriteReport


class TestGoSpriteImport:
    """外部 runner 管理自有 Go/PG 生命周期，本类只经原 importer/SQL/HTTP 核验行为。"""

    def test_original_importer_rows_and_replay(self) -> None:
        """与 SQLite 中运行的原 importer 比较每个字段、原始图片字节及首次/重跑统计。"""
        dsn = os.environ.get("PBI_SPRITES_TEST_DSN")
        source = os.environ.get("PBI_SPRITES_TEST_SOURCE")
        reports = os.environ.get("PBI_SPRITES_TEST_REPORTS")
        if not dsn or not source or not reports:
            pytest.skip("explicit isolated sprite database, source and reports are required")
        source_root = Path(source)
        report_root = Path(reports)
        original = create_engine("sqlite:///:memory:")
        actual = create_engine(dsn)
        try:
            # 原已有 importer 测试也用 SQLite attach；不替换原解析/manifest/导入算法。
            with original.begin() as connection:
                connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS poke_raw")
                RawBase.metadata.create_all(bind=connection)
            with Session(original) as session:
                expected_first = import_sprite_assets(session, source_root=source_root)
                session.commit()
                expected_replay = import_sprite_assets(session, source_root=source_root)
                expected_rows = tuple(
                    _SpriteRecord.model_validate(asset)
                    for asset in session.scalars(select(SpriteAsset).order_by(SpriteAsset.relative_path))
                )
            with actual.connect() as connection:
                actual_rows = tuple(
                    _SpriteRecord.model_validate(row)
                    for row in connection.execute(
                        text("SELECT * FROM poke_raw.sprite_assets ORDER BY relative_path")
                    ).mappings()
                )
            assert actual_rows == expected_rows
            assert actual_rows, "sprite acceptance source must contain actual files"
            for filename, expected in (("initialization.json", expected_first), ("reuse.json", expected_replay)):
                report = _InitializationReport.model_validate_json((report_root / filename).read_text())
                assert report.sprites == _SpriteReport.model_validate(expected, from_attributes=True)
        finally:
            actual.dispose()
            original.dispose()

    @pytest.mark.parametrize(
        ("endpoint", "relative"),
        (
            ("pokemon/212", "pokemon/212.png"),
            ("pokemon/242", "pokemon/242.png"),
            ("pokemon/149", "pokemon/149.png"),
            ("items/life-orb", "items/life-orb.png"),
            ("types/fire", "types/generation-viii/sword-shield/10.png"),
        ),
    )
    def test_public_original_bytes_and_etag(self, endpoint: str, relative: str) -> None:
        """endpoint 是原图片路径，relative 是固定 upstream 真文件；核对完整字节及真实304。"""
        url = os.environ.get("PBI_SPRITES_TEST_URL")
        source = os.environ.get("PBI_SPRITES_TEST_SOURCE")
        if not url or not source:
            pytest.skip("explicit isolated sprite HTTP and upstream source are required")
        with httpx.Client(timeout=10) as client:
            response = client.get(f"{url}/v1/assets/{endpoint}/sprite")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content == (Path(source) / "sprites" / relative).read_bytes()
            assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
            cached = client.get(
                f"{url}/v1/assets/{endpoint}/sprite",
                headers={"If-None-Match": response.headers["etag"]},
            )
            assert cached.status_code == 304
            assert cached.content == b""
