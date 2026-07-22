from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculatorMoveProfile,
    CalculatorMoveSearchResult,
    CalculatorPokemonProfile,
    CalculatorPokemonSearchResult,
    CalculatorRulesetContext,
)
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


def _db_runtime():
    """延迟导入 common DB runtime，避免纯单元测试导入 repository 时触发连接初始化。"""
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _row_mapping(row: Any) -> Mapping[str, Any]:
    """把 SQLAlchemy Row 统一成只读 mapping，集中隔离底层返回类型。"""
    return row._mapping


def _type_from_identifier(identifier: str | None) -> Type | None:
    """把物化视图里的 type identifier 转成 domain Type；空槽位返回 None。"""
    if identifier is None:
        return None
    return Type.from_string(identifier)


def _move_category_from_identifier(identifier: str) -> MoveCategory:
    """把 PokeAPI damage class identifier 转成 domain MoveCategory。"""
    if identifier == "physical":
        return MoveCategory.PHYSICAL
    if identifier == "special":
        return MoveCategory.SPECIAL
    if identifier == "status":
        return MoveCategory.STATUS
    raise ValueError(f"unsupported move damage class identifier: {identifier}")


def _pokemon_profile_from_row(row: Mapping[str, Any]) -> CalculatorPokemonProfile:
    """把 pokemon_profile_mv 行转换成 application 宝可梦读取模型。"""
    type_values = tuple(
        value
        for value in (
            _type_from_identifier(row["type_1_identifier"]),
            _type_from_identifier(row["type_2_identifier"]),
        )
        if value is not None
    )
    type_names = tuple(
        value
        for value in (row["type_1_name"], row["type_2_name"])
        if value is not None
    )
    return CalculatorPokemonProfile(
        pokemon_id=row["pokemon_id"],
        identifier=row["pokemon_identifier"],
        display_name=row["pokemon_name"] or row["pokemon_identifier"],
        form_identifier=row["form_identifier"],
        types=type_values,
        type_names=type_names,
        base_stats=StatValues(
            hp=row["hp"],
            attack=row["attack"],
            defense=row["defense"],
            special_attack=row["special_attack"],
            special_defense=row["special_defense"],
            speed=row["speed"],
        ),
    )


def _pokemon_search_from_row(row: Mapping[str, Any]) -> CalculatorPokemonSearchResult:
    """把 pokemon_profile_mv 行转换成前端搜索轻量结果。"""
    types = tuple(
        value
        for value in (row["type_1_identifier"], row["type_2_identifier"])
        if value is not None
    )
    type_names = tuple(
        value
        for value in (row["type_1_name"], row["type_2_name"])
        if value is not None
    )
    return CalculatorPokemonSearchResult(
        pokemon_id=row["pokemon_id"],
        identifier=row["pokemon_identifier"],
        display_name=row["pokemon_name"] or row["pokemon_identifier"],
        form_identifier=row["form_identifier"],
        types=types,
        type_names=type_names,
    )


def _move_profile_from_row(row: Mapping[str, Any]) -> CalculatorMoveProfile:
    """把 move_profile_mv 行转换成 application 招式读取模型。"""
    return CalculatorMoveProfile(
        move_id=row["move_id"],
        identifier=row["move_identifier"],
        display_name=row["move_name"] or row["move_identifier"],
        type=Type.from_string(row["type_identifier"]),
        type_name=row["type_name"] or row["type_identifier"],
        category=_move_category_from_identifier(row["damage_class_identifier"]),
        power=row["power"],
    )


def _move_search_from_row(row: Mapping[str, Any]) -> CalculatorMoveSearchResult:
    """把 pokemon_learnset_mv 行转换成前端招式选择轻量结果。"""
    return CalculatorMoveSearchResult(
        move_id=row["move_id"],
        identifier=row["move_identifier"],
        display_name=row["move_name"] or row["move_identifier"],
        type=row["type_identifier"],
        type_name=row["type_name"] or row["type_identifier"],
        category=_move_category_from_identifier(row["damage_class_identifier"]),
        power=row["power"],
    )


class MaterializedViewCalculatorRepository:
    """基于 poke_champion 物化视图的 calculator repository。

    该类负责所有 SQL 和 SQLAlchemy session 细节；调用方只接收 application 层的
    dataclass 读取模型，避免 raw model 或 Row 泄漏到上层。
    """

    def get_ruleset_context(self, ruleset_id: str) -> CalculatorRulesetContext | None:
        """按 ruleset_id 读取规则集上下文，不存在时返回 None。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT ruleset_id, ruleset_name, generation_id, version_group_id,
                           version_group_identifier
                    FROM poke_champion.ruleset_context_mv
                    WHERE ruleset_id = :ruleset_id
                    LIMIT 1
                    """
                ),
                {"ruleset_id": ruleset_id},
            ).first()
        if row is None:
            return None
        data = _row_mapping(row)
        return CalculatorRulesetContext(
            ruleset_id=data["ruleset_id"],
            ruleset_name=data["ruleset_name"],
            generation_id=data["generation_id"],
            version_group_id=data["version_group_id"],
            version_group_identifier=data["version_group_identifier"],
        )

    def search_pokemon(
        self,
        *,
        ruleset_id: str,
        query: str,
        limit: int,
    ) -> tuple[CalculatorPokemonSearchResult, ...]:
        """按中文名或 identifier 搜索当前规则集可用宝可梦。"""
        pattern = f"%{query.strip()}%"
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            rows = db.execute(
                text(
                    """
                    SELECT pokemon_id, pokemon_identifier, pokemon_name, form_identifier,
                           type_1_identifier, type_1_name, type_2_identifier, type_2_name
                    FROM poke_champion.pokemon_profile_mv
                    WHERE ruleset_id = :ruleset_id
                      AND (:query = ''
                           OR pokemon_identifier ILIKE :pattern
                           OR pokemon_name ILIKE :pattern)
                    ORDER BY pokemon_identifier
                    LIMIT :limit
                    """
                ),
                {"ruleset_id": ruleset_id, "query": query.strip(), "pattern": pattern, "limit": limit},
            ).all()
        return tuple(_pokemon_search_from_row(_row_mapping(row)) for row in rows)

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> CalculatorPokemonProfile | None:
        """读取一只宝可梦的基础战斗资料。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT pokemon_id, pokemon_identifier, pokemon_name, form_identifier,
                           type_1_identifier, type_1_name, type_2_identifier, type_2_name,
                           hp, attack, defense, special_attack, special_defense, speed
                    FROM poke_champion.pokemon_profile_mv
                    WHERE ruleset_id = :ruleset_id AND pokemon_id = :pokemon_id
                    LIMIT 1
                    """
                ),
                {"ruleset_id": ruleset_id, "pokemon_id": pokemon_id},
            ).first()
        if row is None:
            return None
        return _pokemon_profile_from_row(_row_mapping(row))

    def list_calculable_moves(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        query: str,
        limit: int,
    ) -> tuple[CalculatorMoveSearchResult, ...]:
        """列出固定正威力的物理/特殊可学招式，并按 move_id 去重。"""
        pattern = f"%{query.strip()}%"
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT ON (move_id)
                           move_id, move_identifier, move_name,
                           type_identifier, type_name,
                           damage_class_identifier, power
                    FROM poke_champion.pokemon_learnset_mv
                    WHERE ruleset_id = :ruleset_id
                      AND pokemon_id = :pokemon_id
                      AND damage_class_identifier IN ('physical', 'special')
                      AND power IS NOT NULL
                      AND power > 0
                      AND (:query = ''
                           OR move_identifier ILIKE :pattern
                           OR move_name ILIKE :pattern)
                    ORDER BY move_id, move_identifier
                    LIMIT :limit
                    """
                ),
                {
                    "ruleset_id": ruleset_id,
                    "pokemon_id": pokemon_id,
                    "query": query.strip(),
                    "pattern": pattern,
                    "limit": limit,
                },
            ).all()
        return tuple(_move_search_from_row(_row_mapping(row)) for row in rows)

    def get_move_profile(
        self,
        *,
        ruleset_id: str,
        move_id: int,
    ) -> CalculatorMoveProfile | None:
        """读取一个招式的 version-aware 战斗资料。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT move_id, move_identifier, move_name,
                           type_identifier, type_name,
                           damage_class_identifier, power
                    FROM poke_champion.move_profile_mv
                    WHERE ruleset_id = :ruleset_id AND move_id = :move_id
                    LIMIT 1
                    """
                ),
                {"ruleset_id": ruleset_id, "move_id": move_id},
            ).first()
        if row is None:
            return None
        return _move_profile_from_row(_row_mapping(row))

    def pokemon_can_use_move(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        move_id: int,
    ) -> bool:
        """检查攻击方和招式是否属于当前 ruleset learnset 组合。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT 1
                    FROM poke_champion.pokemon_learnset_mv
                    WHERE ruleset_id = :ruleset_id
                      AND pokemon_id = :pokemon_id
                      AND move_id = :move_id
                      AND damage_class_identifier IN ('physical', 'special')
                      AND power IS NOT NULL
                      AND power > 0
                    LIMIT 1
                    """
                ),
                {
                    "ruleset_id": ruleset_id,
                    "pokemon_id": pokemon_id,
                    "move_id": move_id,
                },
            ).first()
        return row is not None


__all__ = ["MaterializedViewCalculatorRepository"]
