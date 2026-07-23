from __future__ import annotations

from pathlib import Path


SQL_DIR = Path(__file__).resolve().parents[3] / "pokeop" / "persistence" / "views" / "sql" / "poke_champion"


def test_sprite_materialized_views_do_not_select_bytea_content():
    """sprite 业务视图只能保存 asset_id 和元数据，不能复制 raw BYTEA 内容。"""
    for name in ("pokemon_sprite_candidates.sql", "pokemon_sprite_by_version_group.sql"):
        sql = (SQL_DIR / name).read_text(encoding="utf-8").lower()

        assert ".content" not in sql
        assert " bytea" not in sql


def test_scarlet_violet_front_default_priority_is_explicit():
    """朱紫 front_default 选择顺序必须通过显式映射维护，而不是字符串猜测。"""
    sql = (SQL_DIR / "pokemon_sprite_candidates.sql").read_text(encoding="utf-8").lower()

    assert "25::integer as version_group_id" in sql
    assert "'generation-ix'::text as generation_identifier" in sql
    assert "'scarlet-violet'::text as version_identifier" in sql
    assert "'home'::text as render_style" in sql
    assert "'official-artwork'" in sql
    assert "asset.relative_path = ('pokemon/' || asset.pokemon_id::text || '.png')" in sql
