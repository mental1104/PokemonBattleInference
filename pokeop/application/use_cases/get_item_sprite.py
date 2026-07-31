from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ItemSpriteContent:
    """application/API 可读取的一份道具图标二进制内容。

    Args:
        asset_id: ``poke_raw.sprite_assets`` 中的资产主键。
        item_identifier: PokeAPI item 稳定 identifier，例如 ``life-orb``。
        mime_type: HTTP 响应使用的 Content-Type。
        sha256: 图片内容摘要，用于浏览器 ETag 缓存协商。
        content: PostgreSQL BYTEA 中读取出的原始图片字节。
    """

    asset_id: int
    item_identifier: str
    mime_type: str
    sha256: str
    content: bytes


class ItemSpriteRepository(Protocol):
    """application 层依赖的道具图标读取端口。"""

    def get_item_sprite(self, *, item_identifier: str) -> ItemSpriteContent | None:
        """按 PokeAPI item identifier 读取图标；不存在时返回 None。

        Args:
            item_identifier: PokeAPI 稳定 item identifier，必须是规范化的小写字符串。

        Returns:
            找到时返回图片内容；数据库中没有有效资产时返回 None。
        """


@dataclass(frozen=True)
class GetItemSpriteCommand:
    """读取一个道具展示图标的输入命令。

    Args:
        item_identifier: PokeAPI 稳定 item identifier，例如 ``choice-band``。
    """

    item_identifier: str


class GetItemSpriteUseCase:
    """编排项目内道具 sprite 二进制读取。"""

    def __init__(self, repository: ItemSpriteRepository) -> None:
        """保存道具图标 repository 端口实现。

        Args:
            repository: 可按 item identifier 返回 PostgreSQL 图片内容的读取端口。
        """
        self._repository = repository

    def execute(self, command: GetItemSpriteCommand) -> ItemSpriteContent | None:
        """执行一次道具图标读取。

        Args:
            command: 包含规范化 item identifier 的读取命令。

        Returns:
            存在时返回图片内容；不存在时返回 None，由 API 层转换成 404。
        """
        return self._repository.get_item_sprite(
            item_identifier=command.item_identifier,
        )


__all__ = [
    "GetItemSpriteCommand",
    "GetItemSpriteUseCase",
    "ItemSpriteContent",
    "ItemSpriteRepository",
]
