from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculatorBattleItemOption,
)
from pokeop.domain.battle.items import DamageItem
from pokeop.persistence.calculator.repository import (
    MaterializedViewCalculatorRepository as BaseMaterializedViewCalculatorRepository,
)


def _db_runtime():
    """延迟导入 common DB runtime，避免纯单元测试导入时触发连接初始化。

    Returns:
        ``DBKind`` 枚举与 ``tx_scope`` 事务上下文工厂。
    """
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _row_mapping(row: Any) -> Mapping[str, Any]:
    """把 SQLAlchemy Row 转换成只读 mapping。

    Args:
        row: SQLAlchemy 查询返回的行对象。

    Returns:
        包含查询列名和值的只读映射。
    """
    return row._mapping


def _supported_item_identifiers() -> frozenset[str]:
    """读取当前伤害 domain 已实现的 PokeAPI 道具 identifier。

    Returns:
        kebab-case identifier 集合；``UNKNOWN`` 不属于可实现效果。
    """
    return frozenset(
        item.value.replace("_", "-")
        for item in DamageItem
        if item is not DamageItem.UNKNOWN
    )


def _item_option_from_row(
    row: Mapping[str, Any],
    *,
    supported_identifiers: frozenset[str],
) -> CalculatorBattleItemOption:
    """把 PokeAPI item 行转换成带实现状态的 application 读取模型。

    Args:
        row: 必须包含 ``item_id``、``item_identifier`` 和 ``item_name`` 的查询行。
        supported_identifiers: 当前伤害 domain 已实现的 identifier 集合。

    Returns:
        一项道具选择数据；未实现道具的 ``effect_identifier`` 为 ``None``。
    """
    identifier = str(row["item_identifier"])
    return CalculatorBattleItemOption(
        item_id=int(row["item_id"]),
        identifier=identifier,
        display_name=str(row["item_name"] or identifier),
        effect_identifier=identifier if identifier in supported_identifiers else None,
    )


class MaterializedViewCalculatorRepository(BaseMaterializedViewCalculatorRepository):
    """为基础 calculator repository 补充完整战斗持有道具目录。

    Pokémon、招式和规则集查询继续复用原 repository；本类只覆盖道具目录读取，
    将当前规则集可出现的全部战斗持有道具返回给 UI，并通过 ``effect_identifier``
    区分已实现和仅展示的选项。
    """

    def list_battle_item_options(
        self,
        *,
        ruleset_id: str,
    ) -> tuple[CalculatorBattleItemOption, ...]:
        """读取当前规则集全部战斗持有道具，并标记 domain 是否已实现。

        Args:
            ruleset_id: 当前规则集稳定标识，用于确定本地化语言和世代上限。

        Returns:
            首项固定为“不携带道具”；其后已实现道具优先，未实现道具保留名称和
            identifier，但 ``effect_identifier`` 为 ``None``，供前端禁用选择。
        """
        supported_identifiers = _supported_item_identifiers()
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
                    battle_item_flags AS (
                        SELECT map.item_id,
                               bool_or(flag.identifier = 'holdable') AS holdable,
                               bool_or(
                                   flag.identifier IN ('holdable-active', 'holdable-passive')
                               ) AS battle_holdable
                        FROM poke_raw.item_flag_map map
                        JOIN poke_raw.item_flags flag
                          ON flag.id = map.item_flag_id
                        GROUP BY map.item_id
                    )
                    SELECT item.id AS item_id,
                           item.identifier AS item_identifier,
                           item_name.name AS item_name
                    FROM poke_raw.items item
                    JOIN poke_raw.item_categories category
                      ON category.id = item.category_id
                    CROSS JOIN context rc
                    LEFT JOIN battle_item_flags flags
                      ON flags.item_id = item.id
                    LEFT JOIN poke_raw.item_names item_name
                      ON item_name.item_id = item.id
                     AND item_name.local_language_id = rc.language_id
                    WHERE (
                          (flags.holdable IS TRUE AND flags.battle_holdable IS TRUE)
                          OR category.identifier IN (
                              'held-items',
                              'choice',
                              'type-enhancement',
                              'bad-held-items',
                              'plates'
                          )
                      )
                      AND EXISTS (
                          SELECT 1
                          FROM poke_raw.item_game_indices item_generation
                          WHERE item_generation.item_id = item.id
                            AND item_generation.generation_id <= rc.generation_id
                      )
                    ORDER BY item.id
                    """
                ),
                {"ruleset_id": ruleset_id},
            ).all()

        item_options = tuple(
            _item_option_from_row(
                _row_mapping(row),
                supported_identifiers=supported_identifiers,
            )
            for row in rows
        )
        # 让可用项集中在列表前部，同时保留每组内部的数据库 item_id 顺序。
        implemented_options = tuple(
            item for item in item_options if item.effect_identifier is not None
        )
        unimplemented_options = tuple(
            item for item in item_options if item.effect_identifier is None
        )
        return (
            CalculatorBattleItemOption(
                item_id=None,
                identifier="none",
                display_name="不携带道具",
                effect_identifier=None,
            ),
        ) + implemented_options + unimplemented_options


__all__ = ["MaterializedViewCalculatorRepository"]
