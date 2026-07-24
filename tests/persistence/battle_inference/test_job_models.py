"""验证 poke_runtime 后台任务 ORM 模型的 schema 和不变量。"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, UniqueConstraint

from pokeop.persistence.battle_inference.job_models import (
    BattleInferenceCaseModel,
    BattleInferenceJobModel,
    BattleInferenceJobProgressModel,
)
from pokeop.persistence.schema.db_schema import DBSchema


def test_runtime_models_use_dedicated_schema_and_do_not_store_complete_graphs() -> None:
    """任务资产与 raw/read-model schema 隔离，case 表不含图节点或边载荷列。"""
    assert DBSchema.POKE_RUNTIME.value == "poke_runtime"
    assert BattleInferenceJobModel.__table__.schema == "poke_runtime"
    assert BattleInferenceJobProgressModel.__table__.schema == "poke_runtime"
    assert BattleInferenceCaseModel.__table__.schema == "poke_runtime"

    case_columns = set(BattleInferenceCaseModel.__table__.columns.keys())
    assert {"configuration_pair_id", "attacker_move_ids", "defender_move_ids"} <= case_columns
    assert {"node_count", "edge_count", "diagnostic", "result_fingerprint"} <= case_columns
    assert not {"graph", "nodes", "edges", "representative_paths"} & case_columns


def test_models_enforce_job_case_idempotency_and_progress_conservation() -> None:
    """数据库约束覆盖 job+pair 幂等键、稳定序号和进度状态桶守恒。"""
    case_constraints = BattleInferenceCaseModel.__table__.constraints
    unique_names = {
        constraint.name
        for constraint in case_constraints
        if isinstance(constraint, UniqueConstraint)
    }
    progress_checks = {
        constraint.name
        for constraint in BattleInferenceJobProgressModel.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "battle_inference_cases_job_pair_uq" in unique_names
    assert "battle_inference_cases_job_sequence_uq" in unique_names
    assert "battle_inference_job_progress_count_ck" in progress_checks
    assert "battle_inference_job_progress_nonnegative_ck" in progress_checks


def test_claim_and_filter_indexes_cover_status_lease_and_error_queries() -> None:
    """索引支持 SKIP LOCKED 领取以及失败/配置过滤的稳定分页主线。"""
    job_indexes = {index.name for index in BattleInferenceJobModel.__table__.indexes}
    case_indexes = {index.name for index in BattleInferenceCaseModel.__table__.indexes}

    assert "battle_inference_jobs_claim_idx" in job_indexes
    assert "battle_inference_cases_claim_idx" in case_indexes
    assert "battle_inference_cases_failure_idx" in case_indexes
    assert "battle_inference_cases_attacker_config_idx" in case_indexes
    assert "battle_inference_cases_defender_config_idx" in case_indexes
