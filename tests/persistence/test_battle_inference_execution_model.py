"""验证冻结执行规格表只保存有界标量。"""

from __future__ import annotations

from pokeop.persistence.battle_inference.execution_models import (
    BattleInferenceJobExecutionSpecModel,
)


def test_execution_spec_table_excludes_graph_and_arbitrary_payload_columns() -> None:
    """运行时规格不得演化为保存完整图或无界 JSON 的旁路。"""
    columns = set(BattleInferenceJobExecutionSpecModel.__table__.columns.keys())

    assert columns == {
        "job_id",
        "contract_version",
        "weight_assumption",
        "attacker_policy",
        "defender_policy",
        "mechanism_admission",
        "process_count",
        "queue_depth",
        "max_nodes_per_pair",
        "max_edges_per_pair",
        "max_turns",
    }
    assert "graph" not in columns
    assert "payload" not in columns
