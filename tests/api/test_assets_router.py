from __future__ import annotations

import pytest
from fastapi import HTTPException

from pokeop.api.routers import assets
from pokeop.application.use_cases.get_pokemon_sprite import (
    GetPokemonSpriteUseCase,
    PokemonSpriteContent,
)
from pokeop.application.use_cases.get_type_sprite import (
    GetTypeSpriteUseCase,
    TypeSpriteContent,
)


class FakeSpriteRepository:
    """用于 assets router 测试的内存 Pokémon 图片 repository。"""

    def __init__(self, *, found: bool = True) -> None:
        """配置 fake repository 是否返回图片内容。

        Args:
            found: False 时模拟 PostgreSQL 中不存在有效图片。
        """
        self._found = found

    def get_pokemon_sprite(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        slot: str,
    ) -> PokemonSpriteContent | None:
        """返回固定 PNG 内容，或模拟资源不存在。

        Args:
            ruleset_id: 当前规则集标识，本 fake 不改变返回内容。
            pokemon_id: 返回记录携带的 Pokémon ID。
            slot: 返回记录携带的图片槽位。

        Returns:
            found 为真时返回固定内容，否则返回 None。
        """
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


class FakeTypeSpriteRepository:
    """用于属性图片 router 测试的内存 repository。"""

    def __init__(self, *, found: bool = True) -> None:
        """配置 fake repository 是否返回 Sword/Shield 属性图片。

        Args:
            found: False 时模拟属性不存在或对应 BYTEA 尚未导入。
        """
        self._found = found

    def get_type_sprite(self, *, type_identifier: str) -> TypeSpriteContent | None:
        """返回固定属性 PNG 内容，或模拟资源不存在。

        Args:
            type_identifier: 返回记录携带的 PokeAPI 属性 identifier。

        Returns:
            found 为真时返回固定内容，否则返回 None。
        """
        if not self._found:
            return None
        return TypeSpriteContent(
            asset_id=2,
            type_identifier=type_identifier,
            mime_type="image/png",
            sha256="type456",
            content=b"\x89PNGtype",
        )


@pytest.mark.anyio
async def test_assets_api_returns_binary_png_with_etag() -> None:
    """Pokémon 图片 API 成功时返回二进制内容、Content-Type、ETag 和缓存头。"""
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
async def test_assets_api_returns_304_for_matching_etag() -> None:
    """Pokémon 图片 If-None-Match 与 sha256 匹配时返回 304，避免重复传输 BYTEA。"""
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
async def test_assets_api_returns_404_when_sprite_is_missing() -> None:
    """Pokémon 资源不存在时返回稳定 404，而不是泄漏 repository 细节。"""
    with pytest.raises(HTTPException) as exc_info:
        await assets.get_pokemon_sprite(
            212,
            ruleset_id="pokemon-champion",
            slot="front_default",
            if_none_match=None,
            use_case=GetPokemonSpriteUseCase(FakeSpriteRepository(found=False)),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_type_assets_api_returns_postgres_png_with_etag() -> None:
    """属性图片 API 返回 repository 提供的 PNG、ETag 和公共缓存头。"""
    response = await assets.get_type_sprite(
        type_identifier="electric",
        if_none_match=None,
        use_case=GetTypeSpriteUseCase(FakeTypeSpriteRepository()),
    )

    assert response.status_code == 200
    assert response.body == b"\x89PNGtype"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["etag"] == '"type456"'
    assert "max-age" in response.headers["cache-control"]


@pytest.mark.anyio
async def test_type_assets_api_returns_304_for_matching_etag() -> None:
    """属性图片 ETag 命中时复用统一缓存协商路径并返回空 body。"""
    response = await assets.get_type_sprite(
        type_identifier="electric",
        if_none_match='W/"type456"',
        use_case=GetTypeSpriteUseCase(FakeTypeSpriteRepository()),
    )

    assert response.status_code == 304
    assert response.body == b""
    assert response.headers["etag"] == '"type456"'


@pytest.mark.anyio
async def test_type_assets_api_returns_404_when_sprite_is_missing() -> None:
    """未知属性或未导入的 Sword/Shield 图片返回稳定 404。"""
    with pytest.raises(HTTPException) as exc_info:
        await assets.get_type_sprite(
            type_identifier="shadow",
            if_none_match=None,
            use_case=GetTypeSpriteUseCase(FakeTypeSpriteRepository(found=False)),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "type sprite not found"
