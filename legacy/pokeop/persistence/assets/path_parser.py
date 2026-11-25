from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


_POKEMON_ID_RE = re.compile(r"^(?P<pokemon_id>\d+)(?:[-_.].*)?$")


@dataclass(frozen=True)
class SpritePathMetadata:
    """从 sprites 相对路径解析出的稳定元数据。

    Args:
        relative_path: 以 POSIX 分隔符表示、相对于 `sprites/` 根目录的文件路径。
        asset_category: 顶层目录分类，例如 pokemon、items、badges 或 types。
        pokemon_id: 文件名可可靠识别时的 PokeAPI pokemon_id；非宝可梦资源为 None。
        generation_identifier: version 目录中的 generation-* 段。
        version_identifier: version 目录中的具体游戏或 version group 段。
        collection: pokemon、other 或 versions 等业务集合。
        render_style: home、official-artwork、showdown 等渲染风格。
        sprite_slot: 当前可供业务查询的槽位；第一阶段主要使用 front_default。
        is_front: 文件是否表示正面图；非宝可梦资源为 None。
        is_back: 文件是否表示背面图；非宝可梦资源为 None。
        is_female: 文件是否表示 female 变体；非宝可梦资源为 None。
        is_shiny: 文件是否表示 shiny 变体；非宝可梦资源为 None。
        is_animated: 文件是否表示 animated/gif 变体；非宝可梦资源为 None。
        parse_status: parsed 表示成功识别主要语义，unparsed 表示已保留但不能映射。

    Returns:
        dataclass 实例本身不可变，用于 importer 填充 raw asset 行。
    """

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
    parse_status: str


def _pokemon_id_from_name(filename: str) -> int | None:
    """从文件名数字前缀提取 pokemon_id，无法识别时返回 None。

    Args:
        filename: 不含扩展名的 sprite 文件名，例如 `212` 或 `869-matcha-cream`。

    Returns:
        识别出的整数 ID；egg、substitute 等非数字文件返回 None。
    """
    match = _POKEMON_ID_RE.match(filename)
    if match is None:
        return None
    return int(match.group("pokemon_id"))


def _slot(*, is_back: bool, is_female: bool, is_shiny: bool) -> str:
    """把方向和变体标志合成稳定 sprite_slot。

    Args:
        is_back: True 表示背面图，False 表示正面图。
        is_female: True 表示 female 变体。
        is_shiny: True 表示 shiny 变体。

    Returns:
        形如 `front_default`、`back_shiny` 或 `front_female_shiny` 的槽位。
    """
    parts = ["back" if is_back else "front"]
    if is_female:
        parts.append("female")
    if is_shiny:
        parts.append("shiny")
    if len(parts) == 1:
        parts.append("default")
    return "_".join(parts)


def parse_sprite_path(relative_path: str) -> SpritePathMetadata:
    """解析 PokeAPI sprites 仓库内相对 `sprites/` 的文件路径。

    Args:
        relative_path: 由 importer 规范化后的 POSIX 相对路径，不能是用户输入路径。

    Returns:
        可写入 raw asset 表的元数据；解析失败也会返回 `parse_status=unparsed`，
        调用方仍应保存原始二进制资产。
    """
    path = PurePosixPath(relative_path)
    parts = path.parts
    category = parts[0] if parts else "unknown"
    if category != "pokemon" or path.suffix == "":
        return SpritePathMetadata(
            relative_path=relative_path,
            asset_category=category,
            pokemon_id=None,
            generation_identifier=None,
            version_identifier=None,
            collection=None,
            render_style=None,
            sprite_slot=None,
            is_front=None,
            is_back=None,
            is_female=None,
            is_shiny=None,
            is_animated=None,
            parse_status="unparsed",
        )

    pokemon_id = _pokemon_id_from_name(path.stem)
    is_back = "back" in parts
    is_female = "female" in parts
    is_shiny = "shiny" in parts
    is_animated = "animated" in parts or path.suffix.lower() == ".gif"
    generation_identifier: str | None = None
    version_identifier: str | None = None
    collection = "pokemon"
    render_style: str | None = None

    if len(parts) >= 4 and parts[1] == "other":
        collection = "other"
        render_style = parts[2]
    elif len(parts) >= 5 and parts[1] == "versions":
        collection = "versions"
        generation_identifier = parts[2]
        version_identifier = parts[3]
        render_style = parts[4] if parts[4] in {"animated"} else None

    return SpritePathMetadata(
        relative_path=relative_path,
        asset_category=category,
        pokemon_id=pokemon_id,
        generation_identifier=generation_identifier,
        version_identifier=version_identifier,
        collection=collection,
        render_style=render_style,
        sprite_slot=_slot(is_back=is_back, is_female=is_female, is_shiny=is_shiny)
        if pokemon_id is not None
        else None,
        is_front=(not is_back) if pokemon_id is not None else None,
        is_back=is_back if pokemon_id is not None else None,
        is_female=is_female if pokemon_id is not None else None,
        is_shiny=is_shiny if pokemon_id is not None else None,
        is_animated=is_animated if pokemon_id is not None else None,
        parse_status="parsed" if pokemon_id is not None else "unparsed",
    )


__all__ = ["SpritePathMetadata", "parse_sprite_path"]
