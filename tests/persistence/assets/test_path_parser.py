from __future__ import annotations

from pokeop.persistence.assets.path_parser import parse_sprite_path


def test_parse_default_pokemon_sprite_path():
    """默认 pokemon/<id>.png 应解析成 front_default 和 pokemon_id。"""
    metadata = parse_sprite_path("pokemon/212.png")

    assert metadata.asset_category == "pokemon"
    assert metadata.pokemon_id == 212
    assert metadata.collection == "pokemon"
    assert metadata.sprite_slot == "front_default"
    assert metadata.is_front is True
    assert metadata.is_back is False
    assert metadata.parse_status == "parsed"


def test_parse_other_home_and_official_artwork_paths():
    """other/home 与 other/official-artwork 保留 render style，供 fallback 视图排序。"""
    home = parse_sprite_path("pokemon/other/home/700.png")
    artwork = parse_sprite_path("pokemon/other/official-artwork/700.png")

    assert home.collection == "other"
    assert home.render_style == "home"
    assert home.sprite_slot == "front_default"
    assert artwork.collection == "other"
    assert artwork.render_style == "official-artwork"


def test_parse_version_back_female_shiny_and_animated_path():
    """version 目录中的 generation、game、方向和变体都应被保存。"""
    metadata = parse_sprite_path(
        "pokemon/versions/generation-v/black-white/animated/back/female/shiny/212.gif"
    )

    assert metadata.collection == "versions"
    assert metadata.generation_identifier == "generation-v"
    assert metadata.version_identifier == "black-white"
    assert metadata.render_style == "animated"
    assert metadata.sprite_slot == "back_female_shiny"
    assert metadata.is_back is True
    assert metadata.is_female is True
    assert metadata.is_shiny is True
    assert metadata.is_animated is True


def test_parse_unmapped_assets_are_kept_as_unparsed():
    """items、badges、types 或 egg 等无法映射 Pokémon 的资源不能被丢弃。"""
    item = parse_sprite_path("items/master-ball.png")
    egg = parse_sprite_path("pokemon/egg.png")

    assert item.asset_category == "items"
    assert item.pokemon_id is None
    assert item.parse_status == "unparsed"
    assert egg.asset_category == "pokemon"
    assert egg.pokemon_id is None
    assert egg.parse_status == "unparsed"
