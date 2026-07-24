"""验证 persistence 候选招式读取保留 version group 与严格机制分类语义。"""

from __future__ import annotations

from pathlib import Path

from pokeop.application.repositories.battle_inference import MechanismSupportStatus
from pokeop.domain.battle.context import MoveCategory
from pokeop.persistence.battle_inference.repository import (
    _move_capability,
    _move_profile_from_row,
)


def _effective_move_row(
    *,
    type_id: int,
    type_identifier: str,
    type_name: str,
    power: int | None,
    accuracy: int | None,
    priority: int,
    damage_class_identifier: str = "physical",
    effect_id: int | None = 1,
    effect_chance: int | None = None,
) -> dict[str, object]:
    """构造物化视图已经完成历史还原后的招式查询行。

    Args:
        type_id: 当前 version group 下的有效属性 ID。
        type_identifier: 当前 version group 下的有效属性 identifier。
        type_name: 当前语言属性名称。
        power: 当前 version group 下的有效固定威力。
        accuracy: 当前 version group 下的有效命中率。
        priority: 当前 version group 下的有效优先级。
        damage_class_identifier: 当前 version group 下的伤害分类。
        effect_id: 当前 version group 下的 PokeAPI move effect ID。
        effect_chance: 当前 version group 下的附加效果概率。

    Returns:
        可直接交给 persistence row mapper 的只读字段字典。
    """
    return {
        "move_id": 2,
        "move_identifier": "karate-chop",
        "move_name": "空手劈",
        "type_id": type_id,
        "type_identifier": type_identifier,
        "type_name": type_name,
        "power": power,
        "pp": 25,
        "accuracy": accuracy,
        "priority": priority,
        "target_id": 10,
        "target_identifier": "selected-pokemon",
        "damage_class_identifier": damage_class_identifier,
        "effect_id": effect_id,
        "effect_chance": effect_chance,
    }


def test_move_row_mapper_preserves_effective_historical_values_from_each_version_group() -> None:
    """
    本场景模拟 ``move_profile_mv`` 为同一空手劈 move_id 在不同 version group 返回的有效历史行：
    第一世代行为使用一般属性，后续版本使用格斗属性，并分别携带已经由 move_changelog 还原的
    威力、命中率、优先级和伤害分类。persistence mapper 必须只做显式 projection 转换，不得
    使用当前 moves 表值再次覆盖这些字段，也不得把两个版本归并成同一个最新快照。该测试保护
    application 最终看到的候选资料确实保持物化视图输出的 version-aware 历史语义。
    """
    red_blue = _move_profile_from_row(
        _effective_move_row(
            type_id=1,
            type_identifier="normal",
            type_name="一般",
            power=50,
            accuracy=100,
            priority=0,
        )
    )
    gold_silver = _move_profile_from_row(
        _effective_move_row(
            type_id=2,
            type_identifier="fighting",
            type_name="格斗",
            power=50,
            accuracy=100,
            priority=0,
        )
    )

    assert red_blue.move_id == gold_silver.move_id == 2
    assert red_blue.type.identifier == "normal"
    assert gold_silver.type.identifier == "fighting"
    assert red_blue.power == gold_silver.power == 50
    assert red_blue.accuracy == gold_silver.accuracy == 100
    assert red_blue.priority == gold_silver.priority == 0
    assert red_blue.category is gold_silver.category is MoveCategory.PHYSICAL


def test_persistence_classifies_mechanisms_conservatively() -> None:
    """
    本场景直接验证 persistence 对合法招式机制的保守分类边界：纯基础伤害可以标记为 supported；
    固定威力但带独立追加效果的攻击招式只能标记为 partial；变化招式和缺少固定威力解析器的
    攻击招式必须标记为 unsupported。该层不能因为基础伤害字段齐全就宣称追加效果完整，也不能
    用任意正数代替变化威力。此测试保护后续候选池能够完整展示合法项，同时让 application 的
    严格准入可靠地拒绝不完整机制。
    """
    _, base_damage = _move_capability(
        identifier="karate-chop",
        category=MoveCategory.PHYSICAL,
        power=50,
        effect_id=1,
    )
    _, additional_effect = _move_capability(
        identifier="ice-punch",
        category=MoveCategory.PHYSICAL,
        power=75,
        effect_id=2,
    )
    _, status_move = _move_capability(
        identifier="swords-dance",
        category=MoveCategory.STATUS,
        power=None,
        effect_id=51,
    )
    _, variable_power = _move_capability(
        identifier="return",
        category=MoveCategory.PHYSICAL,
        power=None,
        effect_id=1,
    )

    assert base_damage.status is MechanismSupportStatus.SUPPORTED
    assert additional_effect.status is MechanismSupportStatus.PARTIAL
    assert status_move.status is MechanismSupportStatus.UNSUPPORTED
    assert variable_power.status is MechanismSupportStatus.UNSUPPORTED


def test_materialized_view_sql_keeps_version_group_and_changelog_contract() -> None:
    """
    本场景把两份物化视图 SQL 当作 persistence 读取合同进行回归检查。learnset 视图必须使用
    ``pokemon_moves.version_group_id`` 与规则上下文精确相等，不能只按 generation 扩大候选；
    move profile 视图必须针对每个可变字段选择 order 大于目标版本的最近 changelog 旧值，
    并保留按 move_id 去重所需的稳定读取轴。该测试不替代 PostgreSQL 集成测试，但能在纯单元
    测试阶段阻止关键 version-aware SQL 约束被无意删除或改成最新值直读。
    """
    repository_root = Path(__file__).resolve().parents[3]
    learnset_sql = (
        repository_root
        / "pokeop/persistence/views/sql/poke_champion/pokemon_learnset.sql"
    ).read_text(encoding="utf-8")
    move_profile_sql = (
        repository_root
        / "pokeop/persistence/views/sql/poke_champion/move_profile.sql"
    ).read_text(encoding="utf-8")

    assert "pm.version_group_id = rc.version_group_id" in learnset_sql
    assert "JOIN poke_champion.move_profile_mv mp" in learnset_sql
    assert "changed_vg.\"order\" > rc.version_group_order" in move_profile_sql
    assert move_profile_sql.count('ORDER BY changed_vg."order"') >= 8
    assert "COALESCE(old_type.type_id, m.type_id)" in move_profile_sql
    assert "COALESCE(old_power.power, m.power)" in move_profile_sql
    assert "COALESCE(old_accuracy.accuracy, m.accuracy)" in move_profile_sql
    assert "COALESCE(old_priority.priority" in move_profile_sql
