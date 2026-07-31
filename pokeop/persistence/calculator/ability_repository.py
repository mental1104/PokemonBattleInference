from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from pokeop.application.use_cases.calculate_catalog_damage_with_abilities import (
    CalculatorAbilityOption,
)
from pokeop.domain.battle.abilities import DamageAbility


def _db_runtime():
    """延迟导入 common DB runtime，避免纯单元测试触发连接初始化。"""
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _row_mapping(row: Any) -> Mapping[str, Any]:
    """把 SQLAlchemy Row 统一成只读 mapping。"""
    return row._mapping


def _ability_option_from_row(row: Mapping[str, Any]) -> CalculatorAbilityOption:
    """把已还原历史语义的特性行转换成 calculator 选择项。"""
    identifier = row["ability_identifier"]
    implemented = DamageAbility.from_identifier(identifier) is not DamageAbility.UNKNOWN
    return CalculatorAbilityOption(
        ability_id=row["ability_id"],
        identifier=identifier,
        display_name=row["ability_name"] or identifier,
        slot=row["slot"],
        is_hidden=row["is_hidden"],
        implemented=implemented,
        effect_identifier=identifier if implemented else None,
    )


class MaterializedViewCalculatorAbilityRepository:
    """从 PokeAPI raw 表读取 calculator 所需的 version-aware 特性列表。"""

    def list_pokemon_ability_options(
        self,
        *,
        ruleset_id: str,
        pokemon_id: int,
    ) -> tuple[CalculatorAbilityOption, ...]:
        """按规则集 generation 还原历史特性，并标注当前 domain 实现状态。"""
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            rows = db.execute(
                text(
                    """
                    WITH context AS (
                        SELECT generation_id, language_id
                        FROM poke_champion.ruleset_context_mv
                        WHERE ruleset_id = :ruleset_id
                        LIMIT 1
                    ),
                    resolved_abilities AS (
                        SELECT pa.slot,
                               pa.is_hidden,
                               CASE
                                   WHEN past_ability.ability_id IS NOT NULL
                                       THEN NULLIF(past_ability.ability_id, 0)
                                   ELSE NULLIF(pa.ability_id, 0)
                               END AS ability_id
                        FROM poke_raw.pokemon_abilities pa
                        CROSS JOIN context rc
                        LEFT JOIN LATERAL (
                            SELECT pap.ability_id
                            FROM poke_raw.pokemon_abilities_past pap
                            WHERE pap.pokemon_id = pa.pokemon_id
                              AND pap.slot = pa.slot
                              AND pap.is_hidden = pa.is_hidden
                              AND pap.generation_id >= rc.generation_id
                            ORDER BY pap.generation_id
                            LIMIT 1
                        ) past_ability ON true
                        WHERE pa.pokemon_id = :pokemon_id
                    )
                    SELECT DISTINCT ON (a.id)
                           a.id AS ability_id,
                           a.identifier AS ability_identifier,
                           ability_name.name AS ability_name,
                           resolved.slot,
                           resolved.is_hidden
                    FROM resolved_abilities resolved
                    CROSS JOIN context rc
                    JOIN poke_raw.abilities a
                      ON a.id = resolved.ability_id
                     AND a.is_main_series IS TRUE
                    LEFT JOIN poke_raw.ability_names ability_name
                      ON ability_name.ability_id = a.id
                     AND ability_name.local_language_id = rc.language_id
                    ORDER BY a.id, resolved.slot, resolved.is_hidden
                    """
                ),
                {"ruleset_id": ruleset_id, "pokemon_id": pokemon_id},
            ).all()
        return tuple(_ability_option_from_row(_row_mapping(row)) for row in rows)


__all__ = ["MaterializedViewCalculatorAbilityRepository"]
