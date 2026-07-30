from __future__ import annotations

from pathlib import Path


SQL_DIR = Path(__file__).resolve().parents[3] / "pokeop" / "persistence" / "views" / "sql" / "poke_champion"


def test_sprite_materialized_views_do_not_select_bytea_content():
    """sprite 业务视图只能保存 asset_id 和元数据，不能复制 raw BYTEA 内容。"""
    for name in ("pokemon_sprite_candidates.sql", "pokemon_sprite_by_version_group.sql"):
        sql = (SQL_DIR / name).read_text(encoding="utf-8").lower()

        assert ".content" not in sql
        assert " bytea" not in sql


def test_battle_sprite_priority_prefers_root_front_and_back_pair():
    """战斗动画需要正面图和背面图来自同一根目录画风。候选视图必须把 pokemon/<id>.png 与 pokemon/back/<id>.png 作为最高优先级 fallback，并且该优先级要高于 version、home 和 official-artwork 候选。这样双快龙镜像战斗不会出现己方使用像素背面图、对手却使用 Home 高清正面图的画风不一致问题。"""
    sql = (SQL_DIR / "pokemon_sprite_candidates.sql").read_text(encoding="utf-8").lower()

    assert "25::integer as version_group_id" in sql
    assert "'generation-ix'::text as generation_identifier" in sql
    assert "'scarlet-violet'::text as version_identifier" in sql
    assert "select 5::integer as priority, 'pokemon'::text as collection" in sql
    assert "union all select 20, 'other', 'home'" in sql
    assert "'official-artwork'" in sql
    assert "asset.relative_path = ('pokemon/' || asset.pokemon_id::text || '.png')" in sql
    assert "asset.relative_path = ('pokemon/back/' || asset.pokemon_id::text || '.png')" in sql


def test_pokemon_sprite_candidates_include_back_default_slot():
    """宝可梦战斗动画需要双方站位图，物化视图候选必须同时纳入 front_default 与 back_default。该场景直接锁住 SQL 合同：候选槽位来自显式 desired_slots，根目录 fallback 需要分别匹配 pokemon/<id>.png 和 pokemon/back/<id>.png。这样可以保护所有已导入 Pokémon 背面图都能被统一查询到，避免前端动画请求背面图时只能得到 404 或被迫复用正面图。"""
    sql = (SQL_DIR / "pokemon_sprite_candidates.sql").read_text(encoding="utf-8").lower()

    assert "select 'front_default'::text as sprite_slot" in sql
    assert "union all select 'back_default'::text" in sql
    assert "asset.sprite_slot = desired.sprite_slot" in sql
    assert "asset.is_front" in sql
    assert "asset.is_back" in sql
    assert "asset.relative_path = ('pokemon/back/' || asset.pokemon_id::text || '.png')" in sql


def test_selected_pokemon_sprite_view_exposes_orientation_flags():
    """选中后的 Pokémon sprite 物化视图也必须保留图片朝向字段。API 读取二进制内容时仍以 sprite_slot 查询，但调试、后续动画和质量检查需要能直接看到 selected 结果是否来自 back_default，不能只依赖 relative_path 字符串推断。该测试保护 by-version-group 视图继续透传 is_front 与 is_back。"""
    sql = (SQL_DIR / "pokemon_sprite_by_version_group.sql").read_text(encoding="utf-8").lower()

    assert "is_front" in sql
    assert "is_back" in sql
