from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response

from pokeop.application.use_cases.calculate_catalog_damage import DEFAULT_RULESET_ID
from pokeop.application.use_cases.get_pokemon_sprite import (
    GetPokemonSpriteCommand,
    GetPokemonSpriteUseCase,
    PokemonSpriteRepository,
)
from pokeop.application.use_cases.get_type_sprite import (
    GetTypeSpriteCommand,
    GetTypeSpriteUseCase,
    TypeSpriteRepository,
)
from pokeop.persistence.assets import (
    MaterializedViewSpriteRepository,
    RawTypeSpriteRepository,
)

router = APIRouter()


def get_sprite_repository() -> PokemonSpriteRepository:
    """创建 Pokémon 图片资产 repository 依赖。

    Returns:
        基于 PostgreSQL raw 表和 poke_champion 物化视图的 repository 实例。
    """
    return MaterializedViewSpriteRepository()


def get_sprite_use_case(
    repository: PokemonSpriteRepository = Depends(get_sprite_repository),
) -> GetPokemonSpriteUseCase:
    """创建 Pokémon 图片读取 use case，供 FastAPI dependency override 替换。

    Args:
        repository: 按规则集和 Pokémon ID 读取图片的 persistence 端口。

    Returns:
        已注入 repository 的 Pokémon 图片读取 use case。
    """
    return GetPokemonSpriteUseCase(repository)


def get_type_sprite_repository() -> TypeSpriteRepository:
    """创建属性图片资产 repository 依赖。

    Returns:
        从 ``poke_raw`` 固定 Sword/Shield 目录读取属性图片的 repository 实例。
    """
    return RawTypeSpriteRepository()


def get_type_sprite_use_case(
    repository: TypeSpriteRepository = Depends(get_type_sprite_repository),
) -> GetTypeSpriteUseCase:
    """创建属性图片读取 use case，供 FastAPI dependency override 替换。

    Args:
        repository: 按属性 identifier 读取图片的 persistence 端口。

    Returns:
        已注入 repository 的属性图片读取 use case。
    """
    return GetTypeSpriteUseCase(repository)


def _normalize_etag(value: str | None) -> str | None:
    """规范化 If-None-Match 头，兼容弱 ETag 和引号。

    Args:
        value: 浏览器发送的 If-None-Match 原始头值，可能包含多个逗号分隔 ETag。

    Returns:
        第一个可比较的 sha256 字符串；没有头时返回 None。
    """
    if value is None:
        return None
    first = value.split(",", 1)[0].strip()
    if first.startswith("W/"):
        first = first[2:].strip()
    return first.strip('"')


def _binary_asset_response(
    *,
    content: bytes,
    mime_type: str,
    sha256: str,
    if_none_match: str | None,
) -> Response:
    """把数据库二进制资产转换成带缓存协商的 HTTP 响应。

    Args:
        content: PostgreSQL BYTEA 中读取出的原始字节。
        mime_type: 图片资源的 Content-Type。
        sha256: 稳定内容摘要，用作强 ETag。
        if_none_match: 浏览器当前持有的 ETag 请求头。

    Returns:
        ETag 命中时返回空 body 的 304；否则返回完整二进制内容和缓存头。
    """
    etag = f'"{sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=86400",
    }
    if _normalize_etag(if_none_match) == sha256:
        return Response(status_code=304, headers=headers)
    return Response(
        content=content,
        media_type=mime_type,
        headers=headers,
    )


@router.get("/pokemon/{pokemon_id}/sprite")
async def get_pokemon_sprite(
    pokemon_id: int,
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    slot: str = Query(default="front_default", description="图片槽位。"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    use_case: GetPokemonSpriteUseCase = Depends(get_sprite_use_case),
) -> Response:
    """返回一只宝可梦在当前规则集下的项目内 sprite 二进制内容。

    Args:
        pokemon_id: PokeAPI Pokémon ID。
        ruleset_id: 当前规则集稳定标识。
        slot: 需要读取的图片槽位。
        if_none_match: 浏览器缓存协商头。
        use_case: 图片读取 application use case。

    Returns:
        PNG/GIF 等原始图片响应；ETag 命中时返回 304。

    Raises:
        HTTPException: 当前规则集下没有有效图片时返回 404。
    """
    asset = use_case.execute(
        GetPokemonSpriteCommand(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
            slot=slot,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="pokemon sprite not found")
    return _binary_asset_response(
        content=asset.content,
        mime_type=asset.mime_type,
        sha256=asset.sha256,
        if_none_match=if_none_match,
    )


@router.get("/types/{type_identifier}/sprite")
async def get_type_sprite(
    type_identifier: str = Path(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9-]+$",
        description="PokeAPI 属性 identifier。",
    ),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    use_case: GetTypeSpriteUseCase = Depends(get_type_sprite_use_case),
) -> Response:
    """返回 Sword/Shield 风格的属性图片。

    Args:
        type_identifier: PokeAPI 稳定属性 identifier，例如 ``electric``。
        if_none_match: 浏览器缓存协商头。
        use_case: 属性图片读取 application use case。

    Returns:
        从 PostgreSQL BYTEA 读取的 PNG 响应；ETag 命中时返回 304。

    Raises:
        HTTPException: 属性不存在或对应图片尚未导入时返回 404。
    """
    asset = use_case.execute(
        GetTypeSpriteCommand(type_identifier=type_identifier),
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="type sprite not found")
    return _binary_asset_response(
        content=asset.content,
        mime_type=asset.mime_type,
        sha256=asset.sha256,
        if_none_match=if_none_match,
    )


__all__ = [
    "get_pokemon_sprite",
    "get_sprite_repository",
    "get_sprite_use_case",
    "get_type_sprite",
    "get_type_sprite_repository",
    "get_type_sprite_use_case",
    "router",
]
