from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.persistence.base import RawBase


class SpriteImportBatch(RawBase):
    """记录一次 sprites 全量扫描导入批次。

    该模型位于 persistence 层的 poke_raw schema，只描述可再生二进制资产的导入
    状态，不参与 domain 计算。manifest_hash 是以相对路径、sha256 和大小排序后计算
    的稳定摘要，用于识别重复导入。
    """

    __tablename__ = "sprite_import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_commit: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    files_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SpriteAsset(RawBase):
    """保存 PokeAPI sprites 仓库中的一个原始文件。

    一行对应 `sprites/` 目录下的一个文件，`content` 使用 PostgreSQL BYTEA 持久化；
    业务视图只引用 `id` 和元数据，避免把二进制复制到物化视图。
    """

    __tablename__ = "sprite_assets"
    __table_args__ = (
        UniqueConstraint("relative_path", name="sprite_assets_relative_path_uq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    asset_category: Mapped[str] = mapped_column(Text, nullable=False)
    pokemon_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection: Mapped[str | None] = mapped_column(Text, nullable=True)
    render_style: Mapped[str | None] = mapped_column(Text, nullable=True)
    sprite_slot: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_front: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_back: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_female: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_shiny: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_animated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    parse_status: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    first_seen_batch_id: Mapped[int] = mapped_column(
        ForeignKey("poke_raw.sprite_import_batches.id"),
        nullable=False,
    )
    last_seen_batch_id: Mapped[int] = mapped_column(
        ForeignKey("poke_raw.sprite_import_batches.id"),
        nullable=False,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


__all__ = ["SpriteAsset", "SpriteImportBatch"]
