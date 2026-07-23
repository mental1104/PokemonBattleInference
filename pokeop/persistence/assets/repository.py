from __future__ import annotations

from sqlalchemy import text

from pokeop.application.use_cases.get_pokemon_sprite import PokemonSpriteContent


def _db_runtime():
    """延迟导入 common DB runtime，避免纯单元测试加载时连接数据库。"""
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


class MaterializedViewSpriteRepository:
    """基于 poke_champion sprite 物化视图读取图片资产。

    该 repository 先用 `ruleset_id + pokemon_id + slot` 在业务视图中解析 asset_id，
    再单独从 poke_raw.sprite_assets 读取 BYTEA，保持映射视图不复制二进制内容。
    """

    def get_pokemon_sprite(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        slot: str,
    ) -> PokemonSpriteContent | None:
        """读取一只宝可梦在当前规则集下的图片内容。

        Args:
            ruleset_id: 前端/API 使用的稳定规则集标识。
            pokemon_id: PokeAPI pokemon_id。
            slot: 图片槽位，第一阶段公开支持 front_default。

        Returns:
            找到时返回二进制内容记录；没有匹配视图行或 raw 资产已失效时返回 None。
        """
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT
                        selected.asset_id,
                        selected.pokemon_id,
                        selected.sprite_slot,
                        raw.mime_type,
                        raw.sha256,
                        raw.content
                    FROM poke_champion.pokemon_sprite_by_version_group_mv selected
                    JOIN poke_raw.sprite_assets raw
                        ON raw.id = selected.asset_id
                       AND raw.is_active IS TRUE
                    WHERE selected.ruleset_id = :ruleset_id
                      AND selected.pokemon_id = :pokemon_id
                      AND selected.sprite_slot = :slot
                    LIMIT 1
                    """
                ),
                {"ruleset_id": ruleset_id, "pokemon_id": pokemon_id, "slot": slot},
            ).first()

        if row is None:
            return None
        data = row._mapping
        return PokemonSpriteContent(
            asset_id=data["asset_id"],
            pokemon_id=data["pokemon_id"],
            sprite_slot=data["sprite_slot"],
            mime_type=data["mime_type"],
            sha256=data["sha256"],
            content=bytes(data["content"]),
        )


__all__ = ["MaterializedViewSpriteRepository"]
