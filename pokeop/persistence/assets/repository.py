from __future__ import annotations

from sqlalchemy import text

from pokeop.application.use_cases.get_pokemon_sprite import PokemonSpriteContent
from pokeop.application.use_cases.get_type_sprite import TypeSpriteContent


_TYPE_SPRITE_PREFIX = "types/generation-viii/sword-shield/"


def _db_runtime():
    """延迟导入 common DB runtime，避免纯单元测试加载时连接数据库。

    Returns:
        ``DBKind`` 枚举与事务上下文工厂；真实数据库访问只在 repository 方法执行时初始化。
    """
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


class MaterializedViewSpriteRepository:
    """基于 poke_champion sprite 物化视图读取 Pokémon 图片资产。

    该 repository 先用 ``ruleset_id + pokemon_id + slot`` 在业务视图中解析 asset_id，
    再单独从 ``poke_raw.sprite_assets`` 读取 BYTEA，保持映射视图不复制二进制内容。
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


class RawTypeSpriteRepository:
    """从 ``poke_raw`` 读取固定 Sword/Shield 属性图片。

    属性 identifier 先由 ``poke_raw.types`` 解析成 PokeAPI type ID，再与固定目录前缀
    拼成 importer 已保存的相对路径。调用方不能传入任意文件路径，因此该 repository
    不会退化为通用 raw 资产下载入口。
    """

    def get_type_sprite(self, *, type_identifier: str) -> TypeSpriteContent | None:
        """读取一个属性对应的 Sword/Shield 图片。

        Args:
            type_identifier: PokeAPI 稳定属性 identifier，例如 ``electric``。

        Returns:
            找到有效 PNG 时返回 BYTEA 内容；属性不存在或图片未导入时返回 None。
        """
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT
                        raw.id AS asset_id,
                        type_row.identifier AS type_identifier,
                        raw.mime_type,
                        raw.sha256,
                        raw.content
                    FROM poke_raw.types type_row
                    JOIN poke_raw.sprite_assets raw
                      ON raw.relative_path = (
                            :path_prefix || type_row.id::text || '.png'
                         )
                     AND raw.asset_category = 'types'
                     AND raw.is_active IS TRUE
                    WHERE type_row.identifier = :type_identifier
                    LIMIT 1
                    """
                ),
                {
                    "path_prefix": _TYPE_SPRITE_PREFIX,
                    "type_identifier": type_identifier,
                },
            ).first()

        if row is None:
            return None
        data = row._mapping
        return TypeSpriteContent(
            asset_id=data["asset_id"],
            type_identifier=data["type_identifier"],
            mime_type=data["mime_type"],
            sha256=data["sha256"],
            content=bytes(data["content"]),
        )


__all__ = ["MaterializedViewSpriteRepository", "RawTypeSpriteRepository"]
