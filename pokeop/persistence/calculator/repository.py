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
from pokeop.application.use_cases.list_calculable_moves import (
    CalculatorMoveFilterCategory,
    CalculatorMoveTypeOption,
    ListCalculatorMovesQuery,
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
    """把 move_profile_mv 行转换成 application 招式战斗读取模型。"""
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


def _move_type_option_from_row(row: Mapping[str, Any]) -> CalculatorMoveTypeOption:
    """把 type_efficacy_mv 的攻击属性行转换成筛选元数据。"""
    return CalculatorMoveTypeOption(
        identifier=row["damage_type_identifier"],
        display_name=row["damage_type_name"] or row["damage_type_identifier"],
    )


def _filtered_moves_cte_sql() -> str:
    """返回可复用于总数和分页查询的去重过滤 CTE。

    DISTINCT ON 先按 move_id 收口 learnset 的多个学习方式记录；外层查询再按威力、
    属性和 move_id 做稳定排序，避免 PostgreSQL 对 DISTINCT ON 首排序键的限制泄漏到 UI。
    """
    return """
        filtered_moves AS (
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
              AND (:category = 'all' OR damage_class_identifier = :category)
              AND (
                    :type_count = 0
                    OR type_identifier = ANY(CAST(:type_identifiers AS TEXT[]))
                  )
              AND (
                    :query = ''
                    OR move_identifier ILIKE :pattern
                    OR move_name ILIKE :pattern
                  )
            ORDER BY move_id ASC, move_identifier ASC
        )
    """


def _move_filter_params(request: ListCalculatorMovesQuery) -> dict[str, object]:
    """把 application 查询对象转换成 SQL 绑定参数。

    Args:
        request: 已由 use case 完成范围校验和属性去重的查询对象。

    Returns:
        可同时传给总数和分页 SQL 的参数字典；属性集合保持为 PostgreSQL text[] 输入。
    """
    return {
        "ruleset_id": request.ruleset_id,
        "pokemon_id": request.pokemon_id,
        "query": request.query,
        "pattern": f"%{request.query}%",
        "category": request.category.value,
        "type_identifiers": list(request.type_identifiers),
        "type_count": len(request.type_identifiers),
        "limit": request.limit,
        "offset": request.offset,
    }


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
        """按中文名或 identifier 搜索，并按 Pokémon ID 与形态标识稳定排序。"""
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
                    ORDER BY pokemon_id ASC,
                             form_identifier ASC NULLS FIRST,
                             pokemon_identifier ASC
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

    def list_move_filter_types(
        self,
        *,
        ruleset_id: str,
    ) -> tuple[CalculatorMoveTypeOption, ...]:
        """读取当前规则集支持的完整攻击属性元数据。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            rows = db.execute(
                text(
                    """
                    SELECT DISTINCT damage_type_id,
                           damage_type_identifier,
                           damage_type_name
                    FROM poke_champion.type_efficacy_mv
                    WHERE ruleset_id = :ruleset_id
                    ORDER BY damage_type_id ASC
                    """
                ),
                {"ruleset_id": ruleset_id},
            ).all()
        return tuple(_move_type_option_from_row(_row_mapping(row)) for row in rows)

    def search_calculable_moves(
        self,
        *,
        request: ListCalculatorMovesQuery,
    ) -> tuple[tuple[CalculatorMoveSearchResult, ...], int]:
        """按复合筛选查询可计算招式，并返回稳定分页结果和去重后总数。"""
        cte_sql = _filtered_moves_cte_sql()
        params = _move_filter_params(request)
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            total = int(
                db.execute(
                    text(
                        f"""
                        WITH {cte_sql}
                        SELECT COUNT(*)
                        FROM filtered_moves
                        """
                    ),
                    params,
                ).scalar_one()
            )
            rows = db.execute(
                text(
                    f"""
                    WITH {cte_sql}
                    SELECT move_id, move_identifier, move_name,
                           type_identifier, type_name,
                           damage_class_identifier, power
                    FROM filtered_moves
                    ORDER BY power DESC,
                             type_identifier DESC,
                             move_id ASC,
                             move_identifier ASC
                    LIMIT :limit
                    OFFSET :offset
                    """
                ),
                params,
            ).all()
        return (
            tuple(_move_search_from_row(_row_mapping(row)) for row in rows),
            total,
        )

    def list_calculable_moves(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
        query: str,
        limit: int,
    ) -> tuple[CalculatorMoveSearchResult, ...]:
        """兼容旧调用方的无分页招式列表入口；新 API 应使用 search_calculable_moves。"""
        items, _ = self.search_calculable_moves(
            request=ListCalculatorMovesQuery(
                ruleset_id=ruleset_id,
                pokemon_id=pokemon_id,
                query=query.strip(),
                category=CalculatorMoveFilterCategory.ALL,
                type_identifiers=(),
                limit=min(limit, 50),
                offset=0,
            )
        )
        return items

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
