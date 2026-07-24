"""实现 poke_runtime 战斗推演后台任务的 PostgreSQL repository。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any, ContextManager, TypeAlias

from sqlalchemy import and_, func, insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCalculationRevisionMismatch,
    BattleInferenceCaseDefinition,
    BattleInferenceCaseFilter,
    BattleInferenceCaseNotFound,
    BattleInferenceCasePage,
    BattleInferenceCaseResult,
    BattleInferenceCaseSnapshot,
    BattleInferenceCaseStatus,
    BattleInferenceExpectedTurns,
    BattleInferenceExpectedTurnsKind,
    BattleInferenceFailureCode,
    BattleInferenceInvalidTransition,
    BattleInferenceJobAlreadyExists,
    BattleInferenceJobNotFound,
    BattleInferenceJobProgress,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
    BattleInferenceLease,
    BattleInferenceLeaseConflict,
    BattleInferenceProbability,
    BattleInferenceResultConflict,
    CreateBattleInferenceJob,
    validate_lease_request,
)
from pokeop.persistence.battle_inference.job_models import (
    BattleInferenceCaseModel,
    BattleInferenceJobModel,
    BattleInferenceJobProgressModel,
)


TransactionFactory: TypeAlias = Callable[[], ContextManager[Session]]
_TERMINAL_JOB_STATUSES = {
    BattleInferenceJobStatus.SUCCEEDED,
    BattleInferenceJobStatus.COMPLETED_WITH_FAILURES,
    BattleInferenceJobStatus.CANCELLED,
    BattleInferenceJobStatus.FAILED,
}
_JOB_CLAIMABLE_STATUSES = {
    BattleInferenceJobStatus.PENDING,
    BattleInferenceJobStatus.PREPARING,
    BattleInferenceJobStatus.RUNNING,
}


def _db_runtime() -> tuple[Any, Callable[[Any], ContextManager[Session]]]:
    """延迟加载项目公共数据库运行时。

    Returns:
        ``mental1104.db`` 提供的 PostgreSQL 枚举和事务作用域工厂。延迟导入避免
        application 单元测试仅导入 repository Protocol 时初始化数据库连接。
    """
    from mental1104.db import DBKind, tx_scope

    return DBKind, tx_scope


def _default_transaction_factory() -> ContextManager[Session]:
    """创建一次 PostgreSQL 事务作用域。

    Returns:
        成功退出时提交、异常退出时回滚的 SQLAlchemy Session 上下文管理器。
    """
    db_kind, tx_scope = _db_runtime()
    return tx_scope(db_kind.POSTGRES)


class PostgresBattleInferenceJobRepository:
    """使用 PostgreSQL 行锁持久化任务、配置用例、进度和 lease。

    该类位于 persistence 层，负责 SQLAlchemy Session、事务、``FOR UPDATE
    SKIP LOCKED``、幂等结果写入和 projection 映射。application 只依赖对应
    Protocol，不会接触 ORM model、SQL 或锁语义。

    Args:
        transaction_factory: 每次调用返回独立事务上下文的工厂。生产环境省略时使用
            ``mental1104.db.tx_scope``；测试可注入 sessionmaker 包装器。
        insert_batch_size: 创建大任务时每批插入 case 元数据的行数，必须为正整数。
    """

    def __init__(
        self,
        transaction_factory: TransactionFactory | None = None,
        *,
        insert_batch_size: int = 1000,
    ) -> None:
        """保存事务工厂和大批量写入边界。

        Args:
            transaction_factory: 返回 SQLAlchemy Session 事务上下文的可调用对象。
            insert_batch_size: 单次 bulk insert 的最大 case 行数。

        Raises:
            ValueError: ``insert_batch_size`` 不是正整数时抛出。
        """
        if isinstance(insert_batch_size, bool) or insert_batch_size <= 0:
            raise ValueError("insert_batch_size must be a positive integer")
        self._transaction_factory = transaction_factory or _default_transaction_factory
        self._insert_batch_size = insert_batch_size

    def create_job(
        self,
        command: CreateBattleInferenceJob,
        *,
        created_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """在单一事务中创建 job、progress 和全部配置对元数据。

        Args:
            command: 已完成 application 合同校验的任务输入和有序 case 定义。
            created_at: 任务创建时间，必须带时区。

        Returns:
            初始状态为 PENDING、全部 case 仍待执行的任务快照。

        Raises:
            BattleInferenceJobAlreadyExists: job ID 或任务内唯一键已经存在时抛出。
            ValueError: ``created_at`` 无时区时抛出。
        """
        _require_aware_datetime(created_at, "created_at")
        job = BattleInferenceJobModel(
            job_id=command.job_id,
            ruleset_id=command.ruleset_id,
            version_group_id=command.version_group_id,
            calculation_revision=command.calculation_revision,
            status=BattleInferenceJobStatus.PENDING.value,
            attempt_count=0,
            created_at=created_at,
            updated_at=created_at,
        )
        progress = BattleInferenceJobProgressModel(
            job_id=command.job_id,
            total_count=len(command.cases),
            pending_count=len(command.cases),
            running_count=0,
            succeeded_count=0,
            failed_count=0,
            truncated_count=0,
            cancelled_count=0,
            cumulative_node_count=0,
            cumulative_edge_count=0,
            budget_consumed=0,
            updated_at=created_at,
        )

        try:
            with self._transaction_factory() as session:
                session.add(job)
                session.add(progress)
                # 先写入父行，确保 bulk insert 在同一事务中满足外键约束。
                session.flush()
                for rows in _chunked(
                    (
                        _case_insert_values(command.job_id, sequence_no, definition, created_at)
                        for sequence_no, definition in enumerate(command.cases)
                    ),
                    self._insert_batch_size,
                ):
                    session.execute(insert(BattleInferenceCaseModel), rows)
                session.flush()
                return _job_snapshot(job, progress)
        except IntegrityError as exc:
            raise BattleInferenceJobAlreadyExists(
                f"battle inference job {command.job_id!r} already exists"
            ) from exc

    def get_job(
        self,
        job_id: str,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot:
        """读取任务状态、进度和当前 coordinator lease。

        Args:
            job_id: 创建任务时使用的稳定任务 ID。
            calculation_revision: 可选的兼容性要求；不一致时禁止复用任务结果。

        Returns:
            包含当前状态和守恒进度的不可变任务快照。

        Raises:
            BattleInferenceJobNotFound: 任务不存在时抛出。
            BattleInferenceCalculationRevisionMismatch: 计算版本不兼容时抛出。
        """
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id)
            _assert_calculation_revision(job, calculation_revision)
            return _job_snapshot(job, progress)

    def claim_next_job(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot | None:
        """以 ``SKIP LOCKED`` 原子领取一个待准备或 coordinator lease 过期任务。

        Args:
            lease_owner: coordinator 的规范化稳定标识。
            now: 本次领取时间，必须带时区。
            lease_duration: coordinator lease 的正时长。
            calculation_revision: 可选的精确计算版本过滤条件。

        Returns:
            成功领取时返回带新 lease 的任务；当前没有候选任务时返回 None。
        """
        lease_expires_at = validate_lease_request(
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )
        claimable = or_(
            BattleInferenceJobModel.status == BattleInferenceJobStatus.PENDING.value,
            and_(
                BattleInferenceJobModel.status.in_(
                    tuple(
                        status.value
                        for status in _JOB_CLAIMABLE_STATUSES
                        - {BattleInferenceJobStatus.PENDING}
                    )
                ),
                or_(
                    BattleInferenceJobModel.lease_expires_at.is_(None),
                    BattleInferenceJobModel.lease_expires_at <= now,
                ),
            ),
        )
        statement = (
            select(BattleInferenceJobModel)
            .where(claimable)
            .order_by(BattleInferenceJobModel.created_at, BattleInferenceJobModel.job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if calculation_revision is not None:
            statement = statement.where(
                BattleInferenceJobModel.calculation_revision == calculation_revision
            )

        with self._transaction_factory() as session:
            job = session.execute(statement).scalar_one_or_none()
            if job is None:
                return None
            progress = _load_progress(session, job.job_id, for_update=True)
            previous_status = BattleInferenceJobStatus(job.status)
            if previous_status in {
                BattleInferenceJobStatus.PREPARING,
                BattleInferenceJobStatus.RUNNING,
            } and job.lease_owner is not None:
                # 过期 coordinator 可能在事务中途崩溃；记录恢复原因但保留 case 结果。
                job.last_failure_code = BattleInferenceFailureCode.WORKER_CRASH.value
                job.last_failure_diagnostic = (
                    f"coordinator lease owned by {job.lease_owner!r} expired before reclaim"
                )
            if previous_status is BattleInferenceJobStatus.PENDING:
                job.status = BattleInferenceJobStatus.PREPARING.value
            job.attempt_count += 1
            job.lease_owner = lease_owner
            job.heartbeat_at = now
            job.lease_expires_at = lease_expires_at
            job.started_at = job.started_at or now
            job.updated_at = now
            session.flush()
            return _job_snapshot(job, progress)

    def heartbeat_job(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> BattleInferenceJobSnapshot:
        """仅由当前有效 owner 延长 coordinator lease。

        Args:
            job_id: 需要续租的任务 ID。
            lease_owner: 必须与数据库当前 owner 完全一致的标识。
            now: 心跳时间，必须早于旧 lease 过期时间。
            lease_duration: 从 ``now`` 开始计算的新 lease 正时长。

        Returns:
            包含新心跳和过期时间的任务快照。

        Raises:
            BattleInferenceJobNotFound: 任务不存在时抛出。
            BattleInferenceLeaseConflict: owner、状态或有效期不允许续租时抛出。
        """
        lease_expires_at = validate_lease_request(
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            _require_effective_job_lease(job, lease_owner=lease_owner, now=now)
            job.heartbeat_at = now
            job.lease_expires_at = lease_expires_at
            job.updated_at = now
            session.flush()
            return _job_snapshot(job, progress)

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
        """原子领取一批 PENDING 或 worker lease 已过期的配置用例。

        Args:
            job_id: 目标后台任务 ID。
            lease_owner: 执行该批用例的 worker 稳定标识。
            now: 本次领取时间。
            lease_duration: 每个 case 的 worker lease 正时长。
            limit: 本批最多领取数量，范围 1..1000。
            calculation_revision: worker 当前使用的计算语义版本。

        Returns:
            按稳定 ``sequence_no`` 排列的已领取 case 快照；无候选时返回空元组。

        Raises:
            BattleInferenceJobNotFound: 任务不存在时抛出。
            BattleInferenceCalculationRevisionMismatch: worker 版本与任务不兼容时抛出。
            BattleInferenceInvalidTransition: 任务已取消、失败或完成时抛出。
        """
        lease_expires_at = validate_lease_request(
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )
        _require_limit(limit, maximum=1000)
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            _assert_calculation_revision(job, calculation_revision)
            job_status = BattleInferenceJobStatus(job.status)
            if job_status not in {
                BattleInferenceJobStatus.PREPARING,
                BattleInferenceJobStatus.RUNNING,
            }:
                raise BattleInferenceInvalidTransition(
                    f"cannot claim cases while job is {job_status.value}"
                )

            statement = (
                select(BattleInferenceCaseModel)
                .where(
                    BattleInferenceCaseModel.job_id == job_id,
                    or_(
                        BattleInferenceCaseModel.status
                        == BattleInferenceCaseStatus.PENDING.value,
                        and_(
                            BattleInferenceCaseModel.status
                            == BattleInferenceCaseStatus.RUNNING.value,
                            or_(
                                BattleInferenceCaseModel.lease_expires_at.is_(None),
                                BattleInferenceCaseModel.lease_expires_at <= now,
                            ),
                        ),
                    ),
                )
                .order_by(BattleInferenceCaseModel.sequence_no)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            cases = list(session.execute(statement).scalars())
            newly_running = 0
            for case in cases:
                if case.status == BattleInferenceCaseStatus.PENDING.value:
                    newly_running += 1
                else:
                    # RUNNING 桶中的过期用例只转移 owner，不重复修改 progress。
                    case.last_failure_code = BattleInferenceFailureCode.WORKER_CRASH.value
                    case.last_failure_diagnostic = (
                        f"worker lease owned by {case.lease_owner!r} expired before reclaim"
                    )
                case.status = BattleInferenceCaseStatus.RUNNING.value
                case.attempt_count += 1
                case.lease_owner = lease_owner
                case.heartbeat_at = now
                case.lease_expires_at = lease_expires_at
                case.started_at = case.started_at or now
                case.updated_at = now

            if newly_running:
                progress.pending_count -= newly_running
                progress.running_count += newly_running
                progress.updated_at = now
            if cases:
                job.status = BattleInferenceJobStatus.RUNNING.value
                job.started_at = job.started_at or now
                job.updated_at = now
            session.flush()
            return tuple(_case_snapshot(case) for case in cases)

    def heartbeat_cases(
        self,
        job_id: str,
        configuration_pair_ids: tuple[str, ...],
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """延长当前 worker 持有的一批运行中 case lease。

        Args:
            job_id: 目标后台任务 ID。
            configuration_pair_ids: 需要续租的非空、无重复配置对 ID 元组。
            lease_owner: 必须拥有全部目标 case 有效 lease 的 worker 标识。
            now: 心跳时间。
            lease_duration: 从 ``now`` 开始的新 lease 正时长。

        Returns:
            按 ``sequence_no`` 排列的续租后 case 快照。

        Raises:
            BattleInferenceCaseNotFound: 任一配置对不存在时抛出。
            BattleInferenceLeaseConflict: 任一 case 不再由当前 worker 有效持有时抛出。
        """
        lease_expires_at = validate_lease_request(
            lease_owner=lease_owner,
            now=now,
            lease_duration=lease_duration,
        )
        _require_pair_ids(configuration_pair_ids)
        with self._transaction_factory() as session:
            _load_job_and_progress(session, job_id)
            cases = list(
                session.execute(
                    select(BattleInferenceCaseModel)
                    .where(
                        BattleInferenceCaseModel.job_id == job_id,
                        BattleInferenceCaseModel.configuration_pair_id.in_(
                            configuration_pair_ids
                        ),
                    )
                    .order_by(BattleInferenceCaseModel.sequence_no)
                    .with_for_update()
                ).scalars()
            )
            if len(cases) != len(configuration_pair_ids):
                raise BattleInferenceCaseNotFound(
                    "one or more configuration pairs do not exist in the job"
                )
            for case in cases:
                _require_effective_case_lease(case, lease_owner=lease_owner, now=now)
                case.heartbeat_at = now
                case.lease_expires_at = lease_expires_at
                case.updated_at = now
            session.flush()
            return tuple(_case_snapshot(case) for case in cases)

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
        """幂等写入单 case 终态，并在同一事务维护 progress 守恒。

        Args:
            job_id: 目标任务 ID。
            configuration_pair_id: 当前 worker 正在执行的稳定配置对 ID。
            result: 成功、失败、截断或取消的完整最终摘要。
            lease_owner: 提交结果的 worker 标识。
            completed_at: 结果完成时间，必须位于当前有效 lease 内。
            calculation_revision: 产生结果的计算语义版本。

        Returns:
            首次应用该结果返回 True；完全相同的终态重放返回 False。

        Raises:
            BattleInferenceResultConflict: 已存在不同 fingerprint 的终态结果时抛出。
            BattleInferenceLeaseConflict: 当前 worker 没有有效 lease 时抛出。
            BattleInferenceCalculationRevisionMismatch: 结果版本与任务不兼容时抛出。
        """
        _require_identifier(configuration_pair_id, "configuration_pair_id")
        _require_identifier(lease_owner, "lease_owner")
        _require_aware_datetime(completed_at, "completed_at")
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            _assert_calculation_revision(job, calculation_revision)
            case = _load_case(
                session,
                job_id,
                configuration_pair_id,
                for_update=True,
            )
            if BattleInferenceCaseStatus(case.status).is_terminal:
                if case.result_fingerprint == result.fingerprint:
                    # 终态重放不再碰 progress，确保网络重试保持严格幂等。
                    return False
                raise BattleInferenceResultConflict(
                    f"configuration pair {configuration_pair_id!r} already has another result"
                )
            _require_effective_case_lease(
                case,
                lease_owner=lease_owner,
                now=completed_at,
            )

            _apply_case_result(case, result, completed_at=completed_at)
            progress.running_count -= 1
            _increment_terminal_bucket(progress, result.status)
            progress.cumulative_node_count += result.node_count
            progress.cumulative_edge_count += result.edge_count
            progress.budget_consumed += result.budget_consumed
            progress.updated_at = completed_at
            job.updated_at = completed_at
            session.flush()
            return True

    def request_cancel(
        self,
        job_id: str,
        *,
        requested_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录取消请求，同时保留已经完成的 case 摘要。

        Args:
            job_id: 目标任务 ID。
            requested_at: 用户或上层用例请求取消的带时区时间。

        Returns:
            活跃任务迁移为 CANCEL_REQUESTED 后的快照；终态任务保持原状返回。
        """
        _require_aware_datetime(requested_at, "requested_at")
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            status = BattleInferenceJobStatus(job.status)
            if status in _TERMINAL_JOB_STATUSES:
                return _job_snapshot(job, progress)
            if status is not BattleInferenceJobStatus.CANCEL_REQUESTED:
                job.status = BattleInferenceJobStatus.CANCEL_REQUESTED.value
                job.cancel_requested_at = requested_at
                job.updated_at = requested_at
                session.flush()
            return _job_snapshot(job, progress)

    def cancel_unclaimed_cases(
        self,
        job_id: str,
        *,
        cancelled_at: datetime,
    ) -> int:
        """取消 PENDING 和 worker lease 已过期的 RUNNING case。

        Args:
            job_id: 已处于 CANCEL_REQUESTED 的任务 ID。
            cancelled_at: 本次清理的带时区时间。

        Returns:
            本事务首次迁移为 CANCELLED 的 case 数量。仍由有效 worker 持有的 case 不变。

        Raises:
            BattleInferenceInvalidTransition: 任务尚未请求取消时抛出。
        """
        _require_aware_datetime(cancelled_at, "cancelled_at")
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            if (
                BattleInferenceJobStatus(job.status)
                is not BattleInferenceJobStatus.CANCEL_REQUESTED
            ):
                raise BattleInferenceInvalidTransition(
                    "cancel_unclaimed_cases requires CANCEL_REQUESTED job"
                )
            cases = list(
                session.execute(
                    select(BattleInferenceCaseModel)
                    .where(
                        BattleInferenceCaseModel.job_id == job_id,
                        or_(
                            BattleInferenceCaseModel.status
                            == BattleInferenceCaseStatus.PENDING.value,
                            and_(
                                BattleInferenceCaseModel.status
                                == BattleInferenceCaseStatus.RUNNING.value,
                                or_(
                                    BattleInferenceCaseModel.lease_expires_at.is_(None),
                                    BattleInferenceCaseModel.lease_expires_at <= cancelled_at,
                                ),
                            ),
                        ),
                    )
                    .order_by(BattleInferenceCaseModel.sequence_no)
                    .with_for_update(skip_locked=True)
                ).scalars()
            )
            cancelled_result = BattleInferenceCaseResult(
                status=BattleInferenceCaseStatus.CANCELLED,
                failure_code=BattleInferenceFailureCode.CANCELLED,
                diagnostic="job cancellation reached an unclaimed or expired case",
            )
            pending_count = 0
            running_count = 0
            for case in cases:
                if case.status == BattleInferenceCaseStatus.PENDING.value:
                    pending_count += 1
                else:
                    running_count += 1
                    case.last_failure_code = BattleInferenceFailureCode.WORKER_CRASH.value
                    case.last_failure_diagnostic = (
                        f"worker lease owned by {case.lease_owner!r} expired before cancellation"
                    )
                _apply_case_result(case, cancelled_result, completed_at=cancelled_at)
            if cases:
                progress.pending_count -= pending_count
                progress.running_count -= running_count
                progress.cancelled_count += len(cases)
                progress.updated_at = cancelled_at
                job.updated_at = cancelled_at
                session.flush()
            return len(cases)

    def finalize_job(
        self,
        job_id: str,
        *,
        completed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """在所有 case 进入终态后派生并持久化任务最终状态。

        Args:
            job_id: 需要完成收口的任务 ID。
            completed_at: 任务完成时间。

        Returns:
            SUCCEEDED、COMPLETED_WITH_FAILURES 或 CANCELLED 任务快照。

        Raises:
            BattleInferenceInvalidTransition: 仍有 pending/running case 时抛出。
        """
        _require_aware_datetime(completed_at, "completed_at")
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            status = BattleInferenceJobStatus(job.status)
            if status in _TERMINAL_JOB_STATUSES:
                return _job_snapshot(job, progress)
            if progress.pending_count or progress.running_count:
                raise BattleInferenceInvalidTransition(
                    "cannot finalize job while pending or running cases remain"
                )
            if status is BattleInferenceJobStatus.CANCEL_REQUESTED or progress.cancelled_count:
                final_status = BattleInferenceJobStatus.CANCELLED
            elif progress.failed_count or progress.truncated_count:
                final_status = BattleInferenceJobStatus.COMPLETED_WITH_FAILURES
            else:
                final_status = BattleInferenceJobStatus.SUCCEEDED
            job.status = final_status.value
            job.completed_at = completed_at
            job.updated_at = completed_at
            _clear_job_lease(job)
            session.flush()
            return _job_snapshot(job, progress)

    def fail_job(
        self,
        job_id: str,
        *,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录任务级致命失败，但不删除任何已完成 case。

        Args:
            job_id: 目标任务 ID。
            failure_code: coordinator 无法继续执行的稳定错误代码。
            diagnostic: 规范化、非空的诊断文本。
            failed_at: 任务失败时间。

        Returns:
            状态为 FAILED 且保留原进度的任务快照。
        """
        if not isinstance(failure_code, BattleInferenceFailureCode):
            raise ValueError("failure_code must be BattleInferenceFailureCode")
        _require_identifier(diagnostic, "diagnostic")
        _require_aware_datetime(failed_at, "failed_at")
        with self._transaction_factory() as session:
            job, progress = _load_job_and_progress(session, job_id, for_update=True)
            status = BattleInferenceJobStatus(job.status)
            if status in {
                BattleInferenceJobStatus.SUCCEEDED,
                BattleInferenceJobStatus.COMPLETED_WITH_FAILURES,
                BattleInferenceJobStatus.CANCELLED,
            }:
                raise BattleInferenceInvalidTransition(
                    f"cannot fail finalized job in status {status.value}"
                )
            job.status = BattleInferenceJobStatus.FAILED.value
            job.last_failure_code = failure_code.value
            job.last_failure_diagnostic = diagnostic
            job.completed_at = failed_at
            job.updated_at = failed_at
            _clear_job_lease(job)
            session.flush()
            return _job_snapshot(job, progress)

    def list_cases(
        self,
        job_id: str,
        query: BattleInferenceCaseFilter,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceCasePage:
        """按状态、配置 ID 和错误码过滤后稳定分页读取 case。

        Args:
            job_id: 目标任务 ID。
            query: 已完成 application 校验的组合过滤与分页参数。
            calculation_revision: 可选的结果兼容性要求。

        Returns:
            ``sequence_no`` 升序的一页 case 和过滤后的总行数。
        """
        with self._transaction_factory() as session:
            job, _progress = _load_job_and_progress(session, job_id)
            _assert_calculation_revision(job, calculation_revision)
            predicates = [BattleInferenceCaseModel.job_id == job_id]
            if query.statuses:
                predicates.append(
                    BattleInferenceCaseModel.status.in_(
                        tuple(status.value for status in query.statuses)
                    )
                )
            if query.failure_codes:
                predicates.append(
                    BattleInferenceCaseModel.failure_code.in_(
                        tuple(code.value for code in query.failure_codes)
                    )
                )
            if query.configuration_id is not None:
                predicates.append(
                    or_(
                        BattleInferenceCaseModel.configuration_pair_id
                        == query.configuration_id,
                        BattleInferenceCaseModel.attacker_configuration_id
                        == query.configuration_id,
                        BattleInferenceCaseModel.defender_configuration_id
                        == query.configuration_id,
                    )
                )
            total_count = int(
                session.execute(
                    select(func.count(BattleInferenceCaseModel.id)).where(*predicates)
                ).scalar_one()
            )
            cases = tuple(
                _case_snapshot(case)
                for case in session.execute(
                    select(BattleInferenceCaseModel)
                    .where(*predicates)
                    .order_by(BattleInferenceCaseModel.sequence_no)
                    .offset(query.offset)
                    .limit(query.limit)
                ).scalars()
            )
            return BattleInferenceCasePage(
                items=cases,
                total_count=total_count,
                offset=query.offset,
                limit=query.limit,
            )


def _load_job_and_progress(
    session: Session,
    job_id: str,
    *,
    for_update: bool = False,
) -> tuple[BattleInferenceJobModel, BattleInferenceJobProgressModel]:
    """加载同一任务的控制面和进度行。

    Args:
        session: 当前事务持有的 SQLAlchemy Session。
        job_id: 目标任务稳定 ID。
        for_update: 是否同时对两行加排他锁，供状态迁移和计数更新使用。

    Returns:
        依次返回 job model 和 progress model。

    Raises:
        BattleInferenceJobNotFound: 任一必需行不存在时抛出。
    """
    _require_identifier(job_id, "job_id")
    statement = (
        select(BattleInferenceJobModel, BattleInferenceJobProgressModel)
        .join(
            BattleInferenceJobProgressModel,
            BattleInferenceJobProgressModel.job_id == BattleInferenceJobModel.job_id,
        )
        .where(BattleInferenceJobModel.job_id == job_id)
    )
    if for_update:
        statement = statement.with_for_update()
    row = session.execute(statement).one_or_none()
    if row is None:
        raise BattleInferenceJobNotFound(f"battle inference job {job_id!r} was not found")
    return row[0], row[1]


def _load_progress(
    session: Session,
    job_id: str,
    *,
    for_update: bool,
) -> BattleInferenceJobProgressModel:
    """加载指定任务的 progress 行。

    Args:
        session: 当前事务 Session。
        job_id: 目标任务 ID。
        for_update: 是否对进度行加排他锁。

    Returns:
        可在当前事务中读取或修改的 progress model。

    Raises:
        BattleInferenceJobNotFound: progress 行不存在时抛出。
    """
    statement = select(BattleInferenceJobProgressModel).where(
        BattleInferenceJobProgressModel.job_id == job_id
    )
    if for_update:
        statement = statement.with_for_update()
    progress = session.execute(statement).scalar_one_or_none()
    if progress is None:
        raise BattleInferenceJobNotFound(f"battle inference job {job_id!r} was not found")
    return progress


def _load_case(
    session: Session,
    job_id: str,
    configuration_pair_id: str,
    *,
    for_update: bool,
) -> BattleInferenceCaseModel:
    """按任务和稳定配置对 ID 加载一个 case。

    Args:
        session: 当前事务 Session。
        job_id: 父任务 ID。
        configuration_pair_id: 目标配置对 ID。
        for_update: 是否对该 case 行加排他锁。

    Returns:
        当前事务中的 case model。

    Raises:
        BattleInferenceCaseNotFound: 指定组合不存在时抛出。
    """
    statement = select(BattleInferenceCaseModel).where(
        BattleInferenceCaseModel.job_id == job_id,
        BattleInferenceCaseModel.configuration_pair_id == configuration_pair_id,
    )
    if for_update:
        statement = statement.with_for_update()
    case = session.execute(statement).scalar_one_or_none()
    if case is None:
        raise BattleInferenceCaseNotFound(
            f"configuration pair {configuration_pair_id!r} was not found in job {job_id!r}"
        )
    return case


def _assert_calculation_revision(
    job: BattleInferenceJobModel,
    requested_revision: str | None,
) -> None:
    """拒绝读取或写入不兼容 calculation revision 的任务。

    Args:
        job: 已加载的任务 model。
        requested_revision: 调用方要求的版本；None 表示只读取任务元数据。

    Raises:
        BattleInferenceCalculationRevisionMismatch: 版本不相等时抛出。
    """
    if requested_revision is None:
        return
    _require_identifier(requested_revision, "calculation_revision")
    if requested_revision != job.calculation_revision:
        raise BattleInferenceCalculationRevisionMismatch(
            expected=requested_revision,
            actual=job.calculation_revision,
        )


def _require_effective_job_lease(
    job: BattleInferenceJobModel,
    *,
    lease_owner: str,
    now: datetime,
) -> None:
    """校验任务仍由指定 coordinator 有效持有。

    Args:
        job: 已加锁任务 model。
        lease_owner: 调用续租的 coordinator 标识。
        now: 本次操作时间。

    Raises:
        BattleInferenceLeaseConflict: 状态、owner 或有效期不匹配时抛出。
    """
    status = BattleInferenceJobStatus(job.status)
    if status not in {
        BattleInferenceJobStatus.PREPARING,
        BattleInferenceJobStatus.RUNNING,
        BattleInferenceJobStatus.CANCEL_REQUESTED,
    }:
        raise BattleInferenceLeaseConflict(f"job status {status.value} has no active lease")
    if job.lease_owner != lease_owner:
        raise BattleInferenceLeaseConflict("job lease owner does not match")
    if job.lease_expires_at is None or job.lease_expires_at <= now:
        raise BattleInferenceLeaseConflict("job lease has expired")


def _require_effective_case_lease(
    case: BattleInferenceCaseModel,
    *,
    lease_owner: str,
    now: datetime,
) -> None:
    """校验配置用例仍由指定 worker 有效持有。

    Args:
        case: 已加锁 case model。
        lease_owner: 提交 heartbeat 或结果的 worker 标识。
        now: 本次操作时间。

    Raises:
        BattleInferenceLeaseConflict: case 非运行中、owner 不匹配或 lease 已过期时抛出。
    """
    if case.status != BattleInferenceCaseStatus.RUNNING.value:
        raise BattleInferenceLeaseConflict("configuration case is not running")
    if case.lease_owner != lease_owner:
        raise BattleInferenceLeaseConflict("configuration case lease owner does not match")
    if case.lease_expires_at is None or case.lease_expires_at <= now:
        raise BattleInferenceLeaseConflict("configuration case lease has expired")


def _apply_case_result(
    case: BattleInferenceCaseModel,
    result: BattleInferenceCaseResult,
    *,
    completed_at: datetime,
) -> None:
    """把类型化最终结果写入已加锁 case model。

    Args:
        case: 当前事务中持有排他锁的 case model。
        result: application 已校验的最终结果。
        completed_at: 本次结果完成时间。

    Side Effects:
        覆盖最终摘要、诊断和 fingerprint，清空 lease，并将 case 迁移到终态。
    """
    case.status = result.status.value
    _write_probability(case, "attacker_win", result.attacker_win)
    _write_probability(case, "defender_win", result.defender_win)
    _write_probability(case, "draw", result.draw)
    _write_expected_turns(case, result.expected_turns)
    case.node_count = result.node_count
    case.edge_count = result.edge_count
    case.budget_consumed = result.budget_consumed
    case.failure_code = result.failure_code.value if result.failure_code is not None else None
    case.diagnostic = result.diagnostic
    case.result_fingerprint = result.fingerprint
    case.completed_at = completed_at
    case.updated_at = completed_at
    case.lease_owner = None
    case.heartbeat_at = None
    case.lease_expires_at = None


def _write_probability(
    case: BattleInferenceCaseModel,
    prefix: str,
    value: BattleInferenceProbability | None,
) -> None:
    """把任意精度概率分子分母写入 Text 列。

    Args:
        case: 目标 case model。
        prefix: ``attacker_win``、``defender_win`` 或 ``draw`` 字段前缀。
        value: 精确概率；None 时同时清空分子和分母。
    """
    setattr(case, f"{prefix}_numerator", None if value is None else str(value.numerator))
    setattr(case, f"{prefix}_denominator", None if value is None else str(value.denominator))


def _write_expected_turns(
    case: BattleInferenceCaseModel,
    value: BattleInferenceExpectedTurns | None,
) -> None:
    """把期望回合语义写入 case model。

    Args:
        case: 目标 case model。
        value: 有限、无限、不可用或 None 的期望回合值。
    """
    if value is None:
        case.expected_turns_kind = None
        case.expected_turns_numerator = None
        case.expected_turns_denominator = None
        return
    case.expected_turns_kind = value.kind.value
    case.expected_turns_numerator = (
        None if value.numerator is None else str(value.numerator)
    )
    case.expected_turns_denominator = (
        None if value.denominator is None else str(value.denominator)
    )


def _increment_terminal_bucket(
    progress: BattleInferenceJobProgressModel,
    status: BattleInferenceCaseStatus,
) -> None:
    """将一个首次完成的 case 累计到对应 progress 终态桶。

    Args:
        progress: 已加锁任务进度 model。
        status: 首次写入的 case 终态。

    Raises:
        ValueError: 传入非终态时抛出。
    """
    field_by_status = {
        BattleInferenceCaseStatus.SUCCEEDED: "succeeded_count",
        BattleInferenceCaseStatus.FAILED: "failed_count",
        BattleInferenceCaseStatus.TRUNCATED: "truncated_count",
        BattleInferenceCaseStatus.CANCELLED: "cancelled_count",
    }
    field_name = field_by_status.get(status)
    if field_name is None:
        raise ValueError("terminal progress update requires a terminal case status")
    setattr(progress, field_name, getattr(progress, field_name) + 1)


def _job_snapshot(
    job: BattleInferenceJobModel,
    progress: BattleInferenceJobProgressModel,
) -> BattleInferenceJobSnapshot:
    """把 ORM job/progress 映射为 application 快照。

    Args:
        job: 任务控制面 model。
        progress: 同一 job ID 的进度 model。

    Returns:
        不暴露 SQLAlchemy 状态的不可变任务 projection。
    """
    return BattleInferenceJobSnapshot(
        job_id=job.job_id,
        ruleset_id=job.ruleset_id,
        version_group_id=job.version_group_id,
        calculation_revision=job.calculation_revision,
        status=BattleInferenceJobStatus(job.status),
        attempt_count=job.attempt_count,
        progress=BattleInferenceJobProgress(
            total_count=progress.total_count,
            pending_count=progress.pending_count,
            running_count=progress.running_count,
            succeeded_count=progress.succeeded_count,
            failed_count=progress.failed_count,
            truncated_count=progress.truncated_count,
            cancelled_count=progress.cancelled_count,
            cumulative_node_count=progress.cumulative_node_count,
            cumulative_edge_count=progress.cumulative_edge_count,
            budget_consumed=progress.budget_consumed,
        ),
        lease=_lease_from_columns(
            owner=job.lease_owner,
            heartbeat_at=job.heartbeat_at,
            expires_at=job.lease_expires_at,
        ),
        last_failure_code=_failure_code(job.last_failure_code),
        last_failure_diagnostic=job.last_failure_diagnostic,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        cancel_requested_at=job.cancel_requested_at,
    )


def _case_snapshot(case: BattleInferenceCaseModel) -> BattleInferenceCaseSnapshot:
    """把 ORM case 映射为 application 配置结果快照。

    Args:
        case: 已加载的配置用例 model。

    Returns:
        包含稳定身份、lease、结果摘要和恢复诊断的不可变 projection。
    """
    return BattleInferenceCaseSnapshot(
        job_id=case.job_id,
        sequence_no=case.sequence_no,
        definition=BattleInferenceCaseDefinition(
            configuration_pair_id=case.configuration_pair_id,
            attacker_configuration_id=case.attacker_configuration_id,
            defender_configuration_id=case.defender_configuration_id,
            attacker_move_ids=tuple(case.attacker_move_ids),
            defender_move_ids=tuple(case.defender_move_ids),
        ),
        status=BattleInferenceCaseStatus(case.status),
        attempt_count=case.attempt_count,
        lease=_lease_from_columns(
            owner=case.lease_owner,
            heartbeat_at=case.heartbeat_at,
            expires_at=case.lease_expires_at,
        ),
        attacker_win=_probability_from_columns(
            case.attacker_win_numerator,
            case.attacker_win_denominator,
        ),
        defender_win=_probability_from_columns(
            case.defender_win_numerator,
            case.defender_win_denominator,
        ),
        draw=_probability_from_columns(case.draw_numerator, case.draw_denominator),
        expected_turns=_expected_turns_from_columns(
            case.expected_turns_kind,
            case.expected_turns_numerator,
            case.expected_turns_denominator,
        ),
        node_count=case.node_count,
        edge_count=case.edge_count,
        budget_consumed=case.budget_consumed,
        failure_code=_failure_code(case.failure_code),
        diagnostic=case.diagnostic,
        last_failure_code=_failure_code(case.last_failure_code),
        last_failure_diagnostic=case.last_failure_diagnostic,
        created_at=case.created_at,
        updated_at=case.updated_at,
        started_at=case.started_at,
        completed_at=case.completed_at,
    )


def _lease_from_columns(
    *,
    owner: str | None,
    heartbeat_at: datetime | None,
    expires_at: datetime | None,
) -> BattleInferenceLease | None:
    """把三个可空 lease 列恢复成显式 application 对象。

    Args:
        owner: 当前 owner 或 None。
        heartbeat_at: 最近心跳时间或 None。
        expires_at: 过期时间或 None。

    Returns:
        三列全为空时返回 None；三列完整时返回 ``BattleInferenceLease``。

    Raises:
        ValueError: 数据库出现部分为空的损坏 lease 时抛出。
    """
    values = (owner, heartbeat_at, expires_at)
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("lease columns must be all null or all populated")
    assert owner is not None
    assert heartbeat_at is not None
    assert expires_at is not None
    return BattleInferenceLease(
        owner=owner,
        heartbeat_at=heartbeat_at,
        expires_at=expires_at,
    )


def _probability_from_columns(
    numerator: str | None,
    denominator: str | None,
) -> BattleInferenceProbability | None:
    """把 Text 分子分母恢复为任意精度概率。

    Args:
        numerator: 十进制分子文本或 None。
        denominator: 十进制分母文本或 None。

    Returns:
        两列全空返回 None；否则返回精确概率对象。

    Raises:
        ValueError: 只有一列为空或文本不是合法整数时抛出。
    """
    if numerator is None and denominator is None:
        return None
    if numerator is None or denominator is None:
        raise ValueError("probability columns must be both null or both populated")
    return BattleInferenceProbability(int(numerator), int(denominator))


def _expected_turns_from_columns(
    kind: str | None,
    numerator: str | None,
    denominator: str | None,
) -> BattleInferenceExpectedTurns | None:
    """把期望回合数据库列恢复为类型化 application 值。

    Args:
        kind: finite、infinite、unavailable 或 None。
        numerator: 有限值的十进制分子文本。
        denominator: 有限值的十进制分母文本。

    Returns:
        全空返回 None；否则返回与 kind 一致的期望回合对象。
    """
    if kind is None:
        if numerator is not None or denominator is not None:
            raise ValueError("expected turns fraction requires a kind")
        return None
    parsed_kind = BattleInferenceExpectedTurnsKind(kind)
    return BattleInferenceExpectedTurns(
        kind=parsed_kind,
        numerator=None if numerator is None else int(numerator),
        denominator=None if denominator is None else int(denominator),
    )


def _failure_code(value: str | None) -> BattleInferenceFailureCode | None:
    """把可空数据库错误代码恢复为 application 枚举。

    Args:
        value: 稳定错误代码文本或 None。

    Returns:
        对应枚举；空值返回 None。
    """
    return None if value is None else BattleInferenceFailureCode(value)


def _case_insert_values(
    job_id: str,
    sequence_no: int,
    definition: BattleInferenceCaseDefinition,
    created_at: datetime,
) -> dict[str, object]:
    """构造 bulk insert 使用的单 case 列值。

    Args:
        job_id: 父任务 ID。
        sequence_no: command 中的稳定零基序号。
        definition: 配置对身份和双方技能组。
        created_at: 与父任务一致的创建时间。

    Returns:
        不包含完整状态图、可直接传给 SQLAlchemy insert 的列字典。
    """
    return {
        "job_id": job_id,
        "sequence_no": sequence_no,
        "configuration_pair_id": definition.configuration_pair_id,
        "attacker_configuration_id": definition.attacker_configuration_id,
        "defender_configuration_id": definition.defender_configuration_id,
        "attacker_move_ids": list(definition.attacker_move_ids),
        "defender_move_ids": list(definition.defender_move_ids),
        "status": BattleInferenceCaseStatus.PENDING.value,
        "attempt_count": 0,
        "node_count": 0,
        "edge_count": 0,
        "budget_consumed": 0,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _chunked(
    values: Iterable[dict[str, object]],
    size: int,
) -> Iterable[list[dict[str, object]]]:
    """按固定上限流式切分批量 insert 参数。

    Args:
        values: 可一次遍历的 case 行字典。
        size: 每批最大行数，构造 repository 时已经校验为正数。

    Yields:
        一到 ``size`` 行的新列表；空输入不产生批次。
    """
    batch: list[dict[str, object]] = []
    for value in values:
        batch.append(value)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _clear_job_lease(job: BattleInferenceJobModel) -> None:
    """清空任务 coordinator lease 的三个原子字段。

    Args:
        job: 当前事务中已加锁的任务 model。
    """
    job.lease_owner = None
    job.heartbeat_at = None
    job.lease_expires_at = None


def _require_pair_ids(values: Sequence[str]) -> None:
    """校验 heartbeat 批次是非空且无重复的规范化配置 ID。

    Args:
        values: 调用方希望同时续租的配置对 ID 序列。

    Raises:
        ValueError: 序列为空、存在重复或非法标识时抛出。
    """
    if not values:
        raise ValueError("configuration_pair_ids must not be empty")
    for value in values:
        _require_identifier(value, "configuration_pair_id")
    if len(values) != len(set(values)):
        raise ValueError("configuration_pair_ids must be unique")


def _require_limit(value: int, *, maximum: int) -> None:
    """校验批量领取上限。

    Args:
        value: 调用方请求的正整数数量。
        maximum: repository 允许的单批最大值。

    Raises:
        ValueError: value 不是 1..maximum 范围内的整数时抛出。
    """
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


def _require_identifier(value: str, field_name: str) -> None:
    """校验 persistence 边界接收的稳定标识。

    Args:
        value: 待校验字符串。
        field_name: 稳定错误文本中的字段名称。

    Raises:
        ValueError: 值为空、非字符串或首尾有空白时抛出。
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and normalized")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    """校验 persistence 写入时间带有可用时区。

    Args:
        value: 待校验 datetime。
        field_name: 稳定错误文本中的字段名称。

    Raises:
        ValueError: 时间类型非法或缺少时区时抛出。
    """
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


__all__ = ["PostgresBattleInferenceJobRepository", "TransactionFactory"]
