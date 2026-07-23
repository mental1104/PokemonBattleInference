from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PokemonSpriteContent:
    """application/API 可读取的一份图片二进制内容。

    Args:
        asset_id: poke_raw.sprite_assets 主键。
        pokemon_id: 该图片对应的 PokeAPI pokemon_id。
        sprite_slot: 业务槽位，例如 front_default。
        mime_type: HTTP Content-Type。
        sha256: 稳定内容摘要，可作为 ETag。
        content: PostgreSQL BYTEA 中取出的原始字节。

    Returns:
        不可变内容记录，由 repository 从 raw 表和物化视图组装。
    """

    asset_id: int
    pokemon_id: int
    sprite_slot: str
    mime_type: str
    sha256: str
    content: bytes


class PokemonSpriteRepository(Protocol):
    """application 层依赖的图片读取端口。

    实现类负责通过物化视图和 raw 表读取二进制内容；application 不理解 sprites
    路径结构、SQL 或 SQLAlchemy session。
    """

    def get_pokemon_sprite(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        slot: str,
    ) -> PokemonSpriteContent | None:
        """按规则集、pokemon_id 和槽位读取图片内容；不存在时返回 None。"""


@dataclass(frozen=True)
class GetPokemonSpriteCommand:
    """读取一只宝可梦展示图片的输入命令。

    Args:
        ruleset_id: 前端/API 使用的稳定规则集标识。
        pokemon_id: PokeAPI pokemon_id。
        slot: 图片槽位；第一阶段只公开 front_default。

    Returns:
        dataclass 仅封装输入，不直接执行任何 I/O。
    """

    ruleset_id: str
    pokemon_id: int
    slot: str = "front_default"


class GetPokemonSpriteUseCase:
    """编排项目内 Pokémon sprite 二进制读取。

    该 use case 是 API 与 persistence 之间的边界，方便未来把 BYTEA 存储替换为
    对象存储读取，而不改变 HTTP URL 合同或 Calculator 主流程。
    """

    def __init__(self, repository: PokemonSpriteRepository) -> None:
        """保存图片 repository 端口实现。

        Args:
            repository: 可按规则集和 pokemon_id 返回图片内容的持久化端口。
        """
        self._repository = repository

    def execute(self, command: GetPokemonSpriteCommand) -> PokemonSpriteContent | None:
        """执行图片读取。

        Args:
            command: 包含 ruleset、pokemon_id 与 sprite_slot 的读取命令。

        Returns:
            存在时返回图片内容；不存在时返回 None，由 API 层转换成 404。
        """
        return self._repository.get_pokemon_sprite(
            ruleset_id=command.ruleset_id,
            pokemon_id=command.pokemon_id,
            slot=command.slot,
        )


__all__ = [
    "GetPokemonSpriteCommand",
    "GetPokemonSpriteUseCase",
    "PokemonSpriteContent",
    "PokemonSpriteRepository",
]
