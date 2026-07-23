from __future__ import annotations

import pytest
from fastapi import HTTPException

from pokeop.api.routers import assets
from pokeop.application.use_cases.get_pokemon_sprite import (
    GetPokemonSpriteUseCase,
    PokemonSpriteContent,
)


class FakeSpriteRepository:
    """用于 assets router 测试的内存图片 repository。"""

    def __init__(self, *, found: bool = True) -> None:
        """配置 fake repository 是否返回图片内容。"""
        self._found = found

    def get_pokemon_sprite(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        slot: str,
    ) -> PokemonSpriteContent | None:
        """返回固定 PNG 内容，或模拟资源不存在。"""
        if not self._found:
            return None
        return PokemonSpriteContent(
            asset_id=1,
            pokemon_id=pokemon_id,
            sprite_slot=slot,
            mime_type="image/png",
            sha256="abc123",
            content=b"\x89PNG\r\n",
        )


@pytest.mark.anyio
async def test_assets_api_returns_binary_png_with_etag():
    """图片 API 成功时返回二进制内容、Content-Type、ETag 和缓存头。"""
    response = await assets.get_pokemon_sprite(
        212,
        ruleset_id="pokemon-champion",
        slot="front_default",
        if_none_match=None,
        use_case=GetPokemonSpriteUseCase(FakeSpriteRepository()),
    )

    assert response.status_code == 200
    assert response.body == b"\x89PNG\r\n"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == '"abc123"'
    assert "max-age" in response.headers["cache-control"]


@pytest.mark.anyio
async def test_assets_api_returns_304_for_matching_etag():
    """If-None-Match 与 sha256 匹配时返回 304，避免重复传输 BYTEA。"""
    response = await assets.get_pokemon_sprite(
        212,
        ruleset_id="pokemon-champion",
        slot="front_default",
        if_none_match='"abc123"',
        use_case=GetPokemonSpriteUseCase(FakeSpriteRepository()),
    )

    assert response.status_code == 304
    assert response.body == b""
    assert response.headers["etag"] == '"abc123"'


@pytest.mark.anyio
async def test_assets_api_returns_404_when_sprite_is_missing():
    """资源不存在时返回稳定 404，而不是泄漏 repository 细节。"""
    with pytest.raises(HTTPException) as exc_info:
        await assets.get_pokemon_sprite(
            212,
            ruleset_id="pokemon-champion",
            slot="front_default",
            if_none_match=None,
            use_case=GetPokemonSpriteUseCase(FakeSpriteRepository(found=False)),
        )

    assert exc_info.value.status_code == 404
