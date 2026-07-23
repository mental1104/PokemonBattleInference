from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from pokeop.application.use_cases.calculate_catalog_damage import DEFAULT_RULESET_ID
from pokeop.application.use_cases.get_pokemon_sprite import (
    GetPokemonSpriteCommand,
    GetPokemonSpriteUseCase,
    PokemonSpriteRepository,
)
from pokeop.persistence.assets import MaterializedViewSpriteRepository

router = APIRouter()


def get_sprite_repository() -> PokemonSpriteRepository:
    """创建图片资产 repository 依赖。

    Returns:
        基于 PostgreSQL raw 表和 poke_champion 物化视图的 repository 实例。
    """
    return MaterializedViewSpriteRepository()


def get_sprite_use_case(
    repository: PokemonSpriteRepository = Depends(get_sprite_repository),
) -> GetPokemonSpriteUseCase:
    """创建图片读取 use case，供 FastAPI dependency override 替换。"""
    return GetPokemonSpriteUseCase(repository)


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


@router.get("/pokemon/{pokemon_id}/sprite")
async def get_pokemon_sprite(
    pokemon_id: int,
    ruleset_id: str = Query(default=DEFAULT_RULESET_ID, description="当前规则集。"),
    slot: str = Query(default="front_default", description="图片槽位。"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    use_case: GetPokemonSpriteUseCase = Depends(get_sprite_use_case),
) -> Response:
    """返回一只宝可梦在当前规则集下的项目内 sprite 二进制内容。"""
    asset = use_case.execute(
        GetPokemonSpriteCommand(
            ruleset_id=ruleset_id,
            pokemon_id=pokemon_id,
            slot=slot,
        )
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="pokemon sprite not found")

    etag = f'"{asset.sha256}"'
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=86400",
    }
    if _normalize_etag(if_none_match) == asset.sha256:
        return Response(status_code=304, headers=headers)

    return Response(
        content=asset.content,
        media_type=asset.mime_type,
        headers=headers,
    )


__all__ = [
    "get_pokemon_sprite",
    "get_sprite_repository",
    "get_sprite_use_case",
    "router",
]
