"""从 poke_champion 视图读取 version-aware 战斗推演 projection。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import text

from pokeop.application.repositories.battle_inference import (
    BattleInferenceAbilityProfile,
    BattleInferenceItemProfile,
    BattleInferenceMoveProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRulesetContext,
    BattleInferenceTypeProfile,
    MechanismCapability,
    MechanismSupportStatus,
)
from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


_CONTROLLED_ITEM_IDENTIFIERS = tuple(
    item.value.replace("_", "-")
    for item in DamageItem
    if item is not DamageItem.UNKNOWN
)


def _db_runtime():
    """延迟导入 common DB runtime，避免纯 application 测试触发连接初始化。

    Returns:
        ``mental1104.db`` 提供的 DBKind 枚举和事务作用域工厂。
    """
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _row_mapping(row: Any) -> Mapping[str, Any]:
    """把 SQLAlchemy Row 统一转换为只读 mapping。

    Args:
        row: SQLAlchemy ``Row`` 或测试中提供的等价对象，必须暴露 ``_mapping``。

    Returns:
        供显式 projection 映射函数读取的只读字段映射。
    """
    return row._mapping


def _move_category_from_identifier(identifier: str) -> MoveCategory:
    """把 PokeAPI damage class identifier 转成 domain ``MoveCategory``。

    Args:
        identifier: ``physical``、``special`` 或 ``status``。

    Returns:
        与 identifier 对应的显式招式分类枚举。

    Raises:
        ValueError: 数据库返回未知 damage class identifier 时抛出。
    """
    if identifier == "physical":
        return MoveCategory.PHYSICAL
    if identifier == "special":
        return MoveCategory.SPECIAL
    if identifier == "status":
        return MoveCategory.STATUS
    raise ValueError(f"unsupported move damage class identifier: {identifier}")


def _optional_positive_int(value: Any) -> int | None:
    """把 raw import 使用的零哨兵还原为业务层 None。

    Args:
        value: SQL 查询返回的整数、None 或可转换为整数的值。

    Returns:
        正整数原值；None、零或负值返回 None。
    """
    if value is None:
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


def _type_profile(
    *,
    type_id: int,
    identifier: str,
    display_name: str | None,
) -> BattleInferenceTypeProfile:
    """把视图中的属性字段转换为 application 属性 projection。

    Args:
        type_id: PokeAPI 属性整数 ID。
        identifier: PokeAPI 属性 identifier。
        display_name: 当前语言展示名称；允许为空并回退到 identifier。

    Returns:
        同时保存数据库标识和 domain ``Type`` 的不可变读取模型。
    """
    return BattleInferenceTypeProfile(
        type_id=type_id,
        identifier=identifier,
        display_name=display_name or identifier,
        domain_type=Type.from_string(identifier),
    )


def _ability_capability(identifier: str) -> MechanismCapability:
    """根据当前 domain enum 判断合法特性是否已有实现边界。

    Args:
        identifier: PokeAPI 中的合法特性 identifier。

    Returns:
        已实现特性标记为 supported；尚未进入 domain enum 的合法特性标记为 unsupported。
    """
    ability = DamageAbility.from_identifier(identifier)
    if ability is not DamageAbility.UNKNOWN:
        return MechanismCapability(
            source_kind=EffectSourceKind.ABILITY,
            identifier=identifier,
            status=MechanismSupportStatus.SUPPORTED,
            reason="当前 domain 已注册该特性的战斗 effect。",
        )
    return MechanismCapability(
        source_kind=EffectSourceKind.ABILITY,
        identifier=identifier,
        status=MechanismSupportStatus.UNSUPPORTED,
        reason="该特性在当前 version group 合法，但 domain 尚未实现对应 effect。",
    )


def _item_capability(identifier: str) -> MechanismCapability:
    """根据当前 domain enum 判断受控道具候选是否已有实现边界。

    Args:
        identifier: PokeAPI 中的受控道具 identifier。

    Returns:
        已实现道具标记为 supported；未知候选标记为 unsupported。
    """
    item = DamageItem.from_identifier(identifier)
    if item is not DamageItem.UNKNOWN:
        return MechanismCapability(
            source_kind=EffectSourceKind.ITEM,
            identifier=identifier,
            status=MechanismSupportStatus.SUPPORTED,
            reason="当前 domain 已注册该道具的战斗 effect。",
        )
    return MechanismCapability(
        source_kind=EffectSourceKind.ITEM,
        identifier=identifier,
        status=MechanismSupportStatus.UNSUPPORTED,
        reason="该道具属于受控候选，但 domain 尚未实现对应 effect。",
    )


def _move_capability(
    *,
    identifier: str,
    category: MoveCategory,
    power: int | None,
    effect_id: int | None,
) -> tuple[str | None, MechanismCapability]:
    """区分基础伤害、部分支持和暂不支持的合法招式。

    Args:
        identifier: PokeAPI 中的招式稳定 identifier。
        category: 当前 version group 下的招式伤害分类。
        power: 当前 version group 下还原后的基础威力。
        effect_id: PokeAPI move effect ID；仅用于识别是否为纯基础伤害。

    Returns:
        依次返回可交给 domain factory 的 effect identifier，以及显式机制覆盖结论。
    """
    if category is MoveCategory.STATUS:
        return (
            identifier,
            MechanismCapability(
                source_kind=EffectSourceKind.MOVE,
                identifier=identifier,
                status=MechanismSupportStatus.UNSUPPORTED,
                reason="变化招式合法但当前通用回合执行器尚未实现其具体 effect。",
            ),
        )
    if power is None:
        return (
            identifier,
            MechanismCapability(
                source_kind=EffectSourceKind.MOVE,
                identifier=identifier,
                status=MechanismSupportStatus.UNSUPPORTED,
                reason="该攻击招式使用变化威力，当前 domain 尚无对应威力解析器。",
            ),
        )
    if effect_id in (None, 1):
        return (
            None,
            MechanismCapability(
                source_kind=EffectSourceKind.MOVE,
                identifier="base-damage",
                status=MechanismSupportStatus.SUPPORTED,
                reason="该招式只需要当前已支持的基础命中、PP 与伤害语义。",
            ),
        )
    return (
        identifier,
        MechanismCapability(
            source_kind=EffectSourceKind.MOVE,
            identifier=identifier,
            status=MechanismSupportStatus.PARTIAL,
            reason="基础命中、PP 与伤害可执行，但 PokeAPI 附加 effect 尚未完整实现。",
        ),
    )


def _ruleset_context_from_row(
    row: Mapping[str, Any],
) -> BattleInferenceRulesetContext:
    """把 ruleset_context_mv 行转换为 application 规则集 projection。

    Args:
        row: 包含 ruleset、generation 和 version group 字段的只读映射。

    Returns:
        可用于校验后续所有读取结果主轴的规则集上下文。
    """
    return BattleInferenceRulesetContext(
        ruleset_id=row["ruleset_id"],
        ruleset_name=row["ruleset_name"],
        generation_id=row["generation_id"],
        version_group_id=row["version_group_id"],
        version_group_identifier=row["version_group_identifier"],
    )


def _ability_profile_from_row(
    row: Mapping[str, Any],
) -> BattleInferenceAbilityProfile:
    """把已还原历史语义的特性查询行转换为 application projection。

    Args:
        row: 包含特性 ID、identifier、名称、槽位和隐藏标记的只读映射。

    Returns:
        保留合法性与当前 domain 覆盖状态的特性读取模型。
    """
    identifier = row["ability_identifier"]
    return BattleInferenceAbilityProfile(
        ability_id=row["ability_id"],
        identifier=identifier,
        display_name=row["ability_name"] or identifier,
        slot=row["slot"],
        is_hidden=row["is_hidden"],
        effect_identifier=identifier,
        capability=_ability_capability(identifier),
    )


def _move_profile_from_row(row: Mapping[str, Any]) -> BattleInferenceMoveProfile:
    """把 version-aware 招式视图行转换为完整 application projection。

    Args:
        row: pokemon_learnset_mv 与 move_profile_mv 联合查询返回的只读字段映射。

    Returns:
        包含 PP、命中率、优先级、目标和 effect 追踪字段的合法招式读取模型。
    """
    category = _move_category_from_identifier(row["damage_class_identifier"])
    power = _optional_positive_int(row["power"])
    effect_id = _optional_positive_int(row["effect_id"])
    effect_identifier, capability = _move_capability(
        identifier=row["move_identifier"],
        category=category,
        power=power,
        effect_id=effect_id,
    )
    return BattleInferenceMoveProfile(
        move_id=row["move_id"],
        identifier=row["move_identifier"],
        display_name=row["move_name"] or row["move_identifier"],
        type=_type_profile(
            type_id=row["type_id"],
            identifier=row["type_identifier"],
            display_name=row["type_name"],
        ),
        category=category,
        power=power,
        pp=row["pp"],
        accuracy=_optional_positive_int(row["accuracy"]),
        priority=row["priority"],
        target_id=row["target_id"],
        target_identifier=row["target_identifier"],
        effect_id=effect_id,
        effect_chance=_optional_positive_int(row["effect_chance"]),
        effect_identifier=effect_identifier,
        capability=capability,
    )


def _item_profile_from_row(row: Mapping[str, Any]) -> BattleInferenceItemProfile:
    """把受控道具查询行转换为 application 道具候选。

    Args:
        row: 包含道具 ID、identifier 和当前语言名称的只读映射。

    Returns:
        可交给配置生成器枚举，并可继续传给 domain factory 的道具 projection。
    """
    identifier = row["item_identifier"]
    return BattleInferenceItemProfile(
        item_id=row["item_id"],
        identifier=identifier,
        display_name=row["item_name"] or identifier,
        effect_identifier=identifier,
        capability=_item_capability(identifier),
    )


def _no_item_candidate() -> BattleInferenceItemProfile:
    """创建显式不携带道具候选，避免用空集合或 UNKNOWN 表达无道具。

    Returns:
        item_id 和 effect_identifier 均为空、覆盖状态为 no-effect 的合成候选。
    """
    return BattleInferenceItemProfile(
        item_id=None,
        identifier="none",
        display_name="不携带道具",
        effect_identifier=None,
        capability=MechanismCapability(
            source_kind=EffectSourceKind.ITEM,
            identifier="none",
            status=MechanismSupportStatus.NO_EFFECT,
            reason="该配置明确表示不携带道具。",
        ),
    )


class MaterializedViewBattleInferenceRepository:
    """基于 poke_champion 物化视图的 version-aware 战斗推演 repository。

    该实现只负责 SQL、事务、PokeAPI 历史语义和 projection 映射。它不会执行伤害公式、
    回合推进或创建 effect 对象，也不会把 SQLAlchemy Row 暴露给 application。
    """

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """按 ruleset 和 version group 精确读取规则集上下文。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 不允许退化为 generation 猜测的 version group 主轴。

        Returns:
            精确组合存在时返回上下文；不存在时返回 None。
        """
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            row = db.execute(
                text(
                    """
                    SELECT ruleset_id, ruleset_name, generation_id, version_group_id,
                           version_group_identifier
                    FROM poke_champion.ruleset_context_mv
                    WHERE ruleset_id = :ruleset_id
                      AND version_group_id = :version_group_id
                    LIMIT 1
                    """
                ),
                {
                    "ruleset_id": ruleset_id,
                    "version_group_id": version_group_id,
                },
            ).first()
        if row is None:
            return None
        return _ruleset_context_from_row(_row_mapping(row))

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """读取一只 Pokémon 的完整 version-aware 推演 profile。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 属性、特性和 learnset 必须共同匹配的 version group 主轴。
            pokemon_id: 需要读取的 Pokémon 稳定整数 ID。

        Returns:
            找到时返回完整 profile；规则轴或 Pokémon 不存在时返回 None。
        """
        params = {
            "ruleset_id": ruleset_id,
            "version_group_id": version_group_id,
            "pokemon_id": pokemon_id,
        }
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            pokemon_row = db.execute(
                text(
                    """
                    SELECT pp.pokemon_id, pp.pokemon_identifier, pp.pokemon_name,
                           pp.species_id, pp.species_identifier, pp.form_identifier,
                           pp.is_default_form, pp.is_battle_only_form, pp.is_mega_form,
                           pp.type_1_id, pp.type_1_identifier, pp.type_1_name,
                           pp.type_2_id, pp.type_2_identifier, pp.type_2_name,
                           pp.hp, pp.attack, pp.defense,
                           pp.special_attack, pp.special_defense, pp.speed,
                           EXISTS (
                               SELECT 1
                               FROM poke_raw.pokemon_species child_species
                               WHERE child_species.evolves_from_species_id = pp.species_id
                                 AND child_species.generation_id <= pp.generation_id
                           ) AS can_evolve
                    FROM poke_champion.pokemon_profile_mv pp
                    WHERE pp.ruleset_id = :ruleset_id
                      AND pp.version_group_id = :version_group_id
                      AND pp.pokemon_id = :pokemon_id
                    LIMIT 1
                    """
                ),
                params,
            ).first()
            if pokemon_row is None:
                # 规则轴或 Pokémon 不存在时不再执行后续大结果集查询。
                return None

            ability_rows = db.execute(
                text(
                    """
                    WITH context AS (
                        SELECT generation_id, language_id
                        FROM poke_champion.ruleset_context_mv
                        WHERE ruleset_id = :ruleset_id
                          AND version_group_id = :version_group_id
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
                           ra.slot,
                           ra.is_hidden
                    FROM resolved_abilities ra
                    CROSS JOIN context rc
                    JOIN poke_raw.abilities a
                      ON a.id = ra.ability_id
                     AND a.is_main_series IS TRUE
                    LEFT JOIN poke_raw.ability_names ability_name
                      ON ability_name.ability_id = a.id
                     AND ability_name.local_language_id = rc.language_id
                    ORDER BY a.id, ra.slot, ra.is_hidden
                    """
                ),
                params,
            ).all()

            move_rows = db.execute(
                text(
                    """
                    SELECT DISTINCT
                           mp.move_id, mp.move_identifier, mp.move_name,
                           mp.type_id, mp.type_identifier, mp.type_name,
                           NULLIF(mp.power, 0) AS power,
                           mp.pp,
                           NULLIF(mp.accuracy, 0) AS accuracy,
                           mp.priority,
                           mp.target_id,
                           mp.target_identifier,
                           mp.damage_class_identifier,
                           NULLIF(mp.effect_id, 0) AS effect_id,
                           NULLIF(mp.effect_chance, 0) AS effect_chance
                    FROM poke_champion.pokemon_learnset_mv learnset
                    JOIN poke_champion.move_profile_mv mp
                      ON mp.ruleset_id = learnset.ruleset_id
                     AND mp.version_group_id = learnset.version_group_id
                     AND mp.move_id = learnset.move_id
                    WHERE learnset.ruleset_id = :ruleset_id
                      AND learnset.version_group_id = :version_group_id
                      AND learnset.pokemon_id = :pokemon_id
                    ORDER BY mp.move_id
                    """
                ),
                params,
            ).all()

        pokemon = _row_mapping(pokemon_row)
        types = tuple(
            _type_profile(
                type_id=pokemon[type_id_key],
                identifier=pokemon[identifier_key],
                display_name=pokemon[name_key],
            )
            for type_id_key, identifier_key, name_key in (
                ("type_1_id", "type_1_identifier", "type_1_name"),
                ("type_2_id", "type_2_identifier", "type_2_name"),
            )
            if pokemon[type_id_key] is not None
            and pokemon[identifier_key] is not None
        )
        return BattleInferencePokemonProfile(
            pokemon_id=pokemon["pokemon_id"],
            identifier=pokemon["pokemon_identifier"],
            display_name=pokemon["pokemon_name"] or pokemon["pokemon_identifier"],
            species_id=pokemon["species_id"],
            species_identifier=pokemon["species_identifier"],
            form_identifier=pokemon["form_identifier"],
            is_default_form=pokemon["is_default_form"],
            is_battle_only_form=pokemon["is_battle_only_form"],
            is_mega_form=pokemon["is_mega_form"],
            types=types,
            base_stats=StatValues(
                hp=pokemon["hp"],
                attack=pokemon["attack"],
                defense=pokemon["defense"],
                special_attack=pokemon["special_attack"],
                special_defense=pokemon["special_defense"],
                speed=pokemon["speed"],
            ),
            can_evolve=pokemon["can_evolve"],
            abilities=tuple(
                _ability_profile_from_row(_row_mapping(row)) for row in ability_rows
            ),
            moves=tuple(_move_profile_from_row(_row_mapping(row)) for row in move_rows),
        )

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """读取当前 generation 已存在的受控道具候选。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 用于解析 generation 和语言的 version group 主轴。

        Returns:
            规则轴存在时返回以不携带道具开头的稳定候选元组；不存在时返回空元组。
        """
        DBKind, tx_scope = _db_runtime()
        with tx_scope(DBKind.POSTGRES) as db:
            context_exists = db.execute(
                text(
                    """
                    SELECT 1
                    FROM poke_champion.ruleset_context_mv
                    WHERE ruleset_id = :ruleset_id
                      AND version_group_id = :version_group_id
                    LIMIT 1
                    """
                ),
                {
                    "ruleset_id": ruleset_id,
                    "version_group_id": version_group_id,
                },
            ).first()
            if context_exists is None:
                return ()

            rows = db.execute(
                text(
                    """
                    WITH context AS (
                        SELECT generation_id, language_id
                        FROM poke_champion.ruleset_context_mv
                        WHERE ruleset_id = :ruleset_id
                          AND version_group_id = :version_group_id
                    )
                    SELECT item.id AS item_id,
                           item.identifier AS item_identifier,
                           item_name.name AS item_name
                    FROM poke_raw.items item
                    CROSS JOIN context rc
                    LEFT JOIN poke_raw.item_names item_name
                      ON item_name.item_id = item.id
                     AND item_name.local_language_id = rc.language_id
                    WHERE item.identifier = ANY(CAST(:item_identifiers AS TEXT[]))
                      AND EXISTS (
                          SELECT 1
                          FROM poke_raw.item_game_indices item_generation
                          WHERE item_generation.item_id = item.id
                            AND item_generation.generation_id <= rc.generation_id
                      )
                    ORDER BY item.id
                    """
                ),
                {
                    "ruleset_id": ruleset_id,
                    "version_group_id": version_group_id,
                    "item_identifiers": list(_CONTROLLED_ITEM_IDENTIFIERS),
                },
            ).all()

        return (_no_item_candidate(),) + tuple(
            _item_profile_from_row(_row_mapping(row)) for row in rows
        )


__all__ = ["MaterializedViewBattleInferenceRepository"]
