"""组合 #85 任务 repository 与冻结执行规格的 PostgreSQL 实现。"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any, Callable, ContextManager, TypeAlias

from sqlalchemy.orm import Session

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceCasePage,
    BattleInferenceCaseProgress,
    BattleInferenceCaseResult,
    BattleInferenceCaseSnapshot,
    BattleInferenceFailureCode,
    BattleInferenceJobNotFound,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    BattleInferenceRuntimeSnapshot,
)
from pokeop.persistence.battle_inference.execution_models import (
    BattleInferenceJobExecutionSpecModel,
)
from pokeop.persistence.battle_inference.job_models import BattleInferenceJobModel
from pokeop.persistence.battle_inference.job_repository import (
    PostgresBattleInferenceJobRepository,
)


TransactionFactory: TypeAlias = Callable[[], ContextManager[Session]]


class BattleInferenceExecutionSpecNotFound(LookupError):
    """表示任务存在但缺少 #87 冻结执行规格。"""


def _db_runtime() -> tuple[Any, Callable[[Any], ContextManager[Session]]]:
    """延迟读取共享 PostgreSQL 事务运行时。"""
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _default_transaction_factory() -> ContextManager[Session]:
    """返回生产环境默认 PostgreSQL 事务作用域。"""
    db_kind, tx_scope = _db_runtime()
    return tx_scope(db_kind.POSTGRES)


class PostgresBattleInferenceJobStore:
    """在 #85 repository 之上原子保存任务和执行规格。

    Args:
        transaction_factory: 每次调用返回独立事务的工厂；测试可注入 sessionmaker。
        insert_batch_size: 创建大量配置元数据时的批量插入大小。
    """

    def __init__(
        self,
        transaction_factory: TransactionFactory | None = None,
        *,
        insert_batch_size: int = 1000,
    ) -> None:
        """创建共享同一事务工厂的基础 repository 与规格存储。"""
        self._transaction_factory = transaction_factory or _default_transaction_factory
        self._insert_batch_size = insert_batch_size
        self._jobs = PostgresBattleInferenceJobRepository(
            transaction_factory=self._transaction_factory,
            insert_batch_size=insert_batch_size,
        )

    def create_job_with_execution_spec(
        self,
        command: CreateBattleInferenceJob,
        execution_spec: BattleInferenceExecutionSpec,
        *,
        created_at: datetime,
    ) -> BattleInferenceRuntimeSnapshot:
        """在同一事务中创建 job、progress、cases 和执行规格。

        Args:
            command: #85 已验证任务输入和全部 case 元数据。
            execution_spec: #87 冻结进程、策略和图预算。
            created_at: 带时区创建时间。

        Returns:
            初始任务快照与原样执行规格。
        """
        with self._transaction_factory() as session:
            borrowed = PostgresBattleInferenceJobRepository(
                transaction_factory=lambda: nullcontext(session),
                insert_batch_size=self._insert_batch_size,
            )
            job = borrowed.create_job(command, created_at=created_at)
            session.add(_execution_model(command.job_id, execution_spec))
            session.flush()
            return BattleInferenceRuntimeSnapshot(job=job, execution_spec=execution_spec)

    def get_execution_spec(self, job_id: str) -> BattleInferenceExecutionSpec:
        """读取任务创建时冻结的执行规格。

        Args:
            job_id: 已创建任务的稳定 ID。

        Returns:
            可直接交给 coordinator 的不可变执行规格。

        Raises:
            BattleInferenceExecutionSpecNotFound: 任务缺少对应规格行时抛出。
        """
        with self._transaction_factory() as session:
            model = session.get(BattleInferenceJobExecutionSpecModel, job_id)
            if model is None:
                raise BattleInferenceExecutionSpecNotFound(
                    f"battle inference execution spec for {job_id!r} does not exist"
                )
            return _execution_spec(model)

    def fail_job_if_owned(
        self,
        job_id: str,
        *,
        lease_owner: str,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot | None:
        """仅在当前 coordinator lease 仍有效时原子记录任务级失败。

        Args:
            job_id: 目标任务稳定 ID。
            lease_owner: 发生异常的 coordinator 标识。
            failure_code: 任务级稳定错误代码。
            diagnostic: 规范化诊断文本。
            failed_at: 带时区失败时间。

        Returns:
            成功写入时返回 FAILED 快照；lease 已转移、过期或任务不可失败时返回 None。

        Raises:
            BattleInferenceJobNotFound: 目标任务不存在时抛出。
        """
        with self._transaction_factory() as session:
            job = session.get(
                BattleInferenceJobModel,
                job_id,
                with_for_update=True,
            )
            if job is None:
                raise BattleInferenceJobNotFound(
                    f"battle inference job {job_id!r} does not exist"
                )
            status = BattleInferenceJobStatus(job.status)
            if (
                status
                not in {
                    BattleInferenceJobStatus.PREPARING,
                    BattleInferenceJobStatus.RUNNING,
                }
                or job.lease_owner != lease_owner
                or job.lease_expires_at is None
                or job.lease_expires_at <= failed_at
            ):
                return None
            borrowed = PostgresBattleInferenceJobRepository(
                transaction_factory=lambda: nullcontext(session),
                insert_batch_size=self._insert_batch_size,
            )
            return borrowed.fail_job(
                job_id,
                failure_code=failure_code,
                diagnostic=diagnostic,
                failed_at=failed_at,
            )

    def create_job(
        self,
        command: CreateBattleInferenceJob,
        *,
        created_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """保留 #85 原始创建入口，供兼容测试或低层调用使用。"""
        return self._jobs.create_job(command, created_at=created_at)

    def get_job(
        self,
        job_id: str,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot:
        """读取任务生命周期和进度快照。"""
        return self._jobs.get_job(
            job_id,
            calculation_revision=calculation_revision,
        )

    def list_jobs(
        self,
        *,
        statuses: tuple[BattleInferenceJobStatus, ...] = (),
        active_only: bool = False,
        job_id_prefix: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[BattleInferenceJobSnapshot, ...]:
        """分页读取任务列表，供通用 `/v1/inference/jobs` 轮询面板使用。

        Args:
            statuses: 可选 repository 状态过滤。
            active_only: 是否只返回未进入终态的任务。
            job_id_prefix: 可选 ID 前缀过滤，用于固定任务轻量分类。
            offset: 零基偏移。
            limit: 返回上限。

        Returns:
            按创建时间倒序排列的任务快照元组。
        """
        return self._jobs.list_jobs(
            statuses=statuses,
            active_only=active_only,
            job_id_prefix=job_id_prefix,
            offset=offset,
            limit=limit,
        )

    def claim_next_job(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot | None:
        """原子领取一个待执行或 coordinator lease 已过期任务。"""
        return self._jobs.claim_next_job(
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
            calculation_revision=calculation_revision,
        )

    def heartbeat_job(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> BattleInferenceJobSnapshot:
        """延长当前 coordinator job lease。"""
        return self._jobs.heartbeat_job(
            job_id,
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )

    def claim_cases(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        limit: int,
        calculation_revision: str,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """原子领取一批待执行或 worker lease 已过期配置。"""
        return self._jobs.claim_cases(
            job_id,
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
            limit=limit,
            calculation_revision=calculation_revision,
        )

    def heartbeat_cases(
        self,
        job_id: str,
        configuration_pair_ids: tuple[str, ...],
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """延长一批由当前 worker 持有的 case lease。"""
        return self._jobs.heartbeat_cases(
            job_id,
            configuration_pair_ids,
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )

    def record_case_result(
        self,
        job_id: str,
        configuration_pair_id: str,
        result: BattleInferenceCaseResult,
        *,
        lease_owner: str,
        completed_at: datetime,
        calculation_revision: str,
    ) -> bool:
        """幂等保存一个配置终态并维护进度守恒。"""
        return self._jobs.record_case_result(
            job_id,
            configuration_pair_id,
            result,
            lease_owner=lease_owner,
            completed_at=completed_at,
            calculation_revision=calculation_revision,
        )

    def record_case_progress(
        self,
        job_id: str,
        configuration_pair_id: str,
        progress: BattleInferenceCaseProgress,
        *,
        lease_owner: str,
        observed_at: datetime,
        calculation_revision: str,
    ) -> bool:
        """幂等保存运行中 case 的最新观测进度。"""
        return self._jobs.record_case_progress(
            job_id,
            configuration_pair_id,
            progress,
            lease_owner=lease_owner,
            observed_at=observed_at,
            calculation_revision=calculation_revision,
        )

    def request_cancel(
        self,
        job_id: str,
        *,
        requested_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录任务取消请求并保留已完成结果。"""
        return self._jobs.request_cancel(job_id, requested_at=requested_at)

    def cancel_unclaimed_cases(
        self,
        job_id: str,
        *,
        cancelled_at: datetime,
    ) -> int:
        """取消未领取或 lease 已过期配置。"""
        return self._jobs.cancel_unclaimed_cases(job_id, cancelled_at=cancelled_at)

    def finalize_job(
        self,
        job_id: str,
        *,
        completed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """根据全部 case 终态派生任务最终状态。"""
        return self._jobs.finalize_job(job_id, completed_at=completed_at)

    def fail_job(
        self,
        job_id: str,
        *,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录任务级致命失败，同时保留已完成配置。"""
        return self._jobs.fail_job(
            job_id,
            failure_code=failure_code,
            diagnostic=diagnostic,
            failed_at=failed_at,
        )

    def list_cases(
        self,
        job_id: str,
        query: BattleInferenceCaseFilter,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceCasePage:
        """按稳定 sequence 和过滤条件分页读取轻量配置结果。"""
        return self._jobs.list_cases(
            job_id,
            query,
            calculation_revision=calculation_revision,
        )


def _execution_model(
    job_id: str,
    spec: BattleInferenceExecutionSpec,
) -> BattleInferenceJobExecutionSpecModel:
    """把 application 执行规格映射为 SQLAlchemy model。"""
    return BattleInferenceJobExecutionSpecModel(
        job_id=job_id,
        contract_version=spec.contract_version,
        weight_assumption=spec.weight_assumption,
        attacker_policy=spec.attacker_policy,
        defender_policy=spec.defender_policy,
        mechanism_admission=spec.mechanism_admission,
        process_count=spec.process_count,
        queue_depth=spec.queue_depth,
        max_nodes_per_pair=spec.max_nodes_per_pair,
        max_edges_per_pair=spec.max_edges_per_pair,
        max_turns=spec.max_turns,
    )


def _execution_spec(
    model: BattleInferenceJobExecutionSpecModel,
) -> BattleInferenceExecutionSpec:
    """把 ORM 行转换为不泄漏 persistence 类型的 application DTO。"""
    return BattleInferenceExecutionSpec(
        contract_version=model.contract_version,
        weight_assumption=model.weight_assumption,
        attacker_policy=model.attacker_policy,
        defender_policy=model.defender_policy,
        mechanism_admission=model.mechanism_admission,
        process_count=model.process_count,
        queue_depth=model.queue_depth,
        max_nodes_per_pair=model.max_nodes_per_pair,
        max_edges_per_pair=model.max_edges_per_pair,
        max_turns=model.max_turns,
    )


__all__ = [
    "BattleInferenceExecutionSpecNotFound",
    "PostgresBattleInferenceJobStore",
]
