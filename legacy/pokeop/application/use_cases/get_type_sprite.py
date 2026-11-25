from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TypeSpriteContent:
    """application/API 可读取的一份属性图片二进制内容。

    Args:
        asset_id: ``poke_raw.sprite_assets`` 中的资产主键。
        type_identifier: PokeAPI 属性稳定 identifier，例如 ``electric``。
        mime_type: HTTP 响应使用的 Content-Type。
        sha256: 图片内容摘要，用于浏览器 ETag 缓存协商。
        content: PostgreSQL BYTEA 中读取出的原始图片字节。

    Returns:
        不可变内容记录，由 persistence repository 从 raw 表组装。
    """

    asset_id: int
    type_identifier: str
    mime_type: str
    sha256: str
    content: bytes


class TypeSpriteRepository(Protocol):
    """application 层依赖的属性图片读取端口。

    persistence 实现负责把属性 identifier 映射到固定 Sword/Shield type sprite 路径，
    application 不理解 raw 表、文件编号或 SQL。
    """

    def get_type_sprite(self, *, type_identifier: str) -> TypeSpriteContent | None:
        """按属性 identifier 读取图片；资源不存在或已失效时返回 None。

        Args:
            type_identifier: PokeAPI 稳定属性 identifier，必须是规范化的小写字符串。

        Returns:
            找到时返回图片内容；数据库中没有有效资产时返回 None。
        """


@dataclass(frozen=True)
class GetTypeSpriteCommand:
    """读取一个属性展示图片的输入命令。

    Args:
        type_identifier: PokeAPI 稳定属性 identifier，例如 ``fire``。

    Returns:
        dataclass 仅封装输入，不直接执行数据库或文件 I/O。
    """

    type_identifier: str


class GetTypeSpriteUseCase:
    """编排项目内属性 sprite 二进制读取。

    该 use case 保持 API 与 persistence 解耦，使前端 URL 不依赖 raw 路径结构，
    也避免 API router 直接查询 PostgreSQL。
    """

    def __init__(self, repository: TypeSpriteRepository) -> None:
        """保存属性图片 repository 端口实现。

        Args:
            repository: 可按属性 identifier 返回 PostgreSQL 图片内容的读取端口。
        """
        self._repository = repository

    def execute(self, command: GetTypeSpriteCommand) -> TypeSpriteContent | None:
        """执行一次属性图片读取。

        Args:
            command: 包含规范化属性 identifier 的读取命令。

        Returns:
            存在时返回图片内容；不存在时返回 None，由 API 层转换成 404。
        """
        return self._repository.get_type_sprite(
            type_identifier=command.type_identifier,
        )


__all__ = [
    "GetTypeSpriteCommand",
    "GetTypeSpriteUseCase",
    "TypeSpriteContent",
    "TypeSpriteRepository",
]
