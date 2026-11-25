"""持久化后台推演任务创建时冻结的进程与图预算。"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from pokeop.persistence.base import RuntimeBase


class BattleInferenceJobExecutionSpecModel(RuntimeBase):
    """保存 worker 恢复任务时不可改变的执行规格。

    该表只保存有界标量，不保存完整状态图、任意 JSON 或运行中 Future。配置身份继续由
    ``battle_inference_cases`` 承担；这里仅冻结行动策略、进程并发和单配置图保护。
    """

    __tablename__ = "battle_inference_job_execution_specs"
    __table_args__ = (
        CheckConstraint(
            "process_count BETWEEN 1 AND 8",
            name="battle_inference_job_execution_process_count_ck",
        ),
        CheckConstraint(
            "queue_depth BETWEEN process_count AND 32",
            name="battle_inference_job_execution_queue_depth_ck",
        ),
        CheckConstraint(
            "max_nodes_per_pair BETWEEN 1 AND 2000000",
            name="battle_inference_job_execution_nodes_ck",
        ),
        CheckConstraint(
            "max_edges_per_pair BETWEEN 1 AND 8000000",
            name="battle_inference_job_execution_edges_ck",
        ),
        CheckConstraint(
            "max_turns IS NULL OR max_turns BETWEEN 1 AND 10000",
            name="battle_inference_job_execution_turns_ck",
        ),
    )

    job_id: Mapped[str] = mapped_column(
        ForeignKey("poke_runtime.battle_inference_jobs.job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    weight_assumption: Mapped[str] = mapped_column(String(64), nullable=False)
    attacker_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    defender_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    mechanism_admission: Mapped[str] = mapped_column(String(64), nullable=False)
    process_count: Mapped[int] = mapped_column(Integer, nullable=False)
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False)
    max_nodes_per_pair: Mapped[int] = mapped_column(Integer, nullable=False)
    max_edges_per_pair: Mapped[int] = mapped_column(Integer, nullable=False)
    max_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)


__all__ = ["BattleInferenceJobExecutionSpecModel"]
