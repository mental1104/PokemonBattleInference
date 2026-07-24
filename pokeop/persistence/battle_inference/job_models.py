"""定义 poke_runtime 中的战斗推演后台任务 SQLAlchemy 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.persistence.base import RuntimeBase


class BattleInferenceJobModel(RuntimeBase):
    """保存一个配置空间后台任务的控制面状态。

    任务行绑定 ruleset、version group 和 calculation revision，并保存 coordinator lease、
    取消请求、整体失败诊断和生命周期时间。配置结果和统计分别位于 case/progress 表，
    避免任务行承载无界 JSON 或完整状态图。
    """

    __tablename__ = "battle_inference_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'preparing', 'running', 'succeeded', "
            "'completed_with_failures', 'cancel_requested', 'cancelled', 'failed')",
            name="battle_inference_jobs_status_ck",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="battle_inference_jobs_attempt_count_ck",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "heartbeat_at IS NOT NULL)",
            name="battle_inference_jobs_lease_ck",
        ),
        Index(
            "battle_inference_jobs_claim_idx",
            "status",
            "lease_expires_at",
            "created_at",
        ),
    )

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    ruleset_id: Mapped[str] = mapped_column(Text, nullable=False)
    version_group_id: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_revision: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_failure_diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BattleInferenceJobProgressModel(RuntimeBase):
    """保存一个任务的原子进度、图规模和预算累计值。

    每个任务只有一行。数据库 check constraint 强制所有状态桶之和等于 total_count，
    repository 在 case 终态写入的同一事务中更新本表，从而避免结果与进度分离提交。
    """

    __tablename__ = "battle_inference_job_progress"
    __table_args__ = (
        CheckConstraint(
            "total_count = pending_count + running_count + succeeded_count + "
            "failed_count + truncated_count + cancelled_count",
            name="battle_inference_job_progress_count_ck",
        ),
        CheckConstraint(
            "total_count >= 0 AND pending_count >= 0 AND running_count >= 0 AND "
            "succeeded_count >= 0 AND failed_count >= 0 AND truncated_count >= 0 AND "
            "cancelled_count >= 0 AND cumulative_node_count >= 0 AND "
            "cumulative_edge_count >= 0 AND budget_consumed >= 0",
            name="battle_inference_job_progress_nonnegative_ck",
        ),
    )

    job_id: Mapped[str] = mapped_column(
        ForeignKey("poke_runtime.battle_inference_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cumulative_node_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cumulative_edge_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    budget_consumed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BattleInferenceCaseModel(RuntimeBase):
    """保存一个固定配置对的身份、lease、最终摘要和诊断。

    每行只保存双方稳定配置 ID、规范化技能组、胜负平概率、期望回合和图规模；完整
    状态图不会写入 PostgreSQL。``job_id + configuration_pair_id`` 唯一约束保证重试
    不会创建重复用例，``result_fingerprint`` 用于检测相同终态重放和冲突覆盖。
    """

    __tablename__ = "battle_inference_cases"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "configuration_pair_id",
            name="battle_inference_cases_job_pair_uq",
        ),
        UniqueConstraint(
            "job_id",
            "sequence_no",
            name="battle_inference_cases_job_sequence_uq",
        ),
        CheckConstraint("sequence_no >= 0", name="battle_inference_cases_sequence_ck"),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'truncated', "
            "'cancelled')",
            name="battle_inference_cases_status_ck",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND node_count >= 0 AND edge_count >= 0 AND "
            "budget_consumed >= 0",
            name="battle_inference_cases_nonnegative_ck",
        ),
        CheckConstraint(
            "(lease_owner IS NULL AND lease_expires_at IS NULL AND heartbeat_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "heartbeat_at IS NOT NULL)",
            name="battle_inference_cases_lease_ck",
        ),
        CheckConstraint(
            "expected_turns_kind IS NULL OR expected_turns_kind IN "
            "('finite', 'infinite', 'unavailable')",
            name="battle_inference_cases_expected_turns_kind_ck",
        ),
        CheckConstraint(
            "(status IN ('pending', 'running') AND result_fingerprint IS NULL) OR "
            "(status = 'succeeded' AND attacker_win_numerator IS NOT NULL AND "
            "attacker_win_denominator IS NOT NULL AND defender_win_numerator IS NOT NULL "
            "AND defender_win_denominator IS NOT NULL AND draw_numerator IS NOT NULL "
            "AND draw_denominator IS NOT NULL AND expected_turns_kind IS NOT NULL AND "
            "failure_code IS NULL AND diagnostic IS NULL AND result_fingerprint IS NOT NULL) "
            "OR (status IN ('failed', 'truncated', 'cancelled') AND "
            "attacker_win_numerator IS NULL AND attacker_win_denominator IS NULL AND "
            "defender_win_numerator IS NULL AND defender_win_denominator IS NULL AND "
            "draw_numerator IS NULL AND draw_denominator IS NULL AND "
            "expected_turns_kind IS NULL AND expected_turns_numerator IS NULL AND "
            "expected_turns_denominator IS NULL AND failure_code IS NOT NULL AND "
            "diagnostic IS NOT NULL AND result_fingerprint IS NOT NULL)",
            name="battle_inference_cases_result_shape_ck",
        ),
        Index(
            "battle_inference_cases_claim_idx",
            "job_id",
            "status",
            "lease_expires_at",
            "sequence_no",
        ),
        Index(
            "battle_inference_cases_failure_idx",
            "job_id",
            "failure_code",
            "sequence_no",
        ),
        Index(
            "battle_inference_cases_attacker_config_idx",
            "job_id",
            "attacker_configuration_id",
            "sequence_no",
        ),
        Index(
            "battle_inference_cases_defender_config_idx",
            "job_id",
            "defender_configuration_id",
            "sequence_no",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("poke_runtime.battle_inference_jobs.job_id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_pair_id: Mapped[str] = mapped_column(Text, nullable=False)
    attacker_configuration_id: Mapped[str] = mapped_column(Text, nullable=False)
    defender_configuration_id: Mapped[str] = mapped_column(Text, nullable=False)
    attacker_move_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    defender_move_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    attacker_win_numerator: Mapped[str | None] = mapped_column(Text, nullable=True)
    attacker_win_denominator: Mapped[str | None] = mapped_column(Text, nullable=True)
    defender_win_numerator: Mapped[str | None] = mapped_column(Text, nullable=True)
    defender_win_denominator: Mapped[str | None] = mapped_column(Text, nullable=True)
    draw_numerator: Mapped[str | None] = mapped_column(Text, nullable=True)
    draw_denominator: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_turns_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_turns_numerator: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_turns_denominator: Mapped[str | None] = mapped_column(Text, nullable=True)
    node_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    budget_consumed: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_failure_diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "BattleInferenceCaseModel",
    "BattleInferenceJobModel",
    "BattleInferenceJobProgressModel",
]
