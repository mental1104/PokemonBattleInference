"""协调任务领取、进程池执行、租约续期、取消和最终收口。"""

from __future__ import annotations

import os
import time
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from multiprocessing import Manager
from queue import Empty
from typing import Any, Callable

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCalculationRevisionMismatch,
    BattleInferenceCaseResult,
    BattleInferenceCaseProgress,
    BattleInferenceCaseSnapshot,
    BattleInferenceCaseStatus,
    BattleInferenceFailureCode,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
    BattleInferenceLeaseConflict,
)
from pokeop.application.use_cases._battle_inference_worker.contracts import (
    BattleInferenceCasePreparer,
)
from pokeop.application.use_cases._battle_inference_worker.execution import (
    execute_prepared_battle_inference_case,
    failure_result,
    persistent_result,
)
from pokeop.application.use_cases._battle_inference_worker.pool import (
    TerminableProcessPool,
    WorkerExecutor,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    BattleInferenceJobStore,
)
from pokeop.application.use_cases.stream_configuration_pairs import (
    ConfigurationPairExecutionResult,
)

ExecutorFactory = Callable[[int], WorkerExecutor]
Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


@dataclass(slots=True)
class RunBattleInferenceWorkerUseCase:
    """领取一个持久化任务并用有界进程池执行到终态。"""

    store: BattleInferenceJobStore
    preparer: BattleInferenceCasePreparer
    worker_id: str
    executor_factory: ExecutorFactory = TerminableProcessPool
    clock: Clock = lambda: datetime.now(timezone.utc)
    sleep: Sleep = time.sleep
    lease_duration: timedelta = timedelta(minutes=2)
    heartbeat_interval: timedelta = timedelta(seconds=20)
    poll_interval_seconds: float = 0.1
    cancellation_grace: timedelta = timedelta(seconds=5)

    def __post_init__(self) -> None:
        """校验 worker 标识和时间参数满足 lease 安全关系。"""
        if not self.worker_id or self.worker_id != self.worker_id.strip():
            raise ValueError("worker_id must be non-empty and normalized")
        if self.lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if not timedelta(0) < self.heartbeat_interval < self.lease_duration:
            raise ValueError("heartbeat_interval must be positive and shorter than lease")
        if self.poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be non-negative")
        if self.cancellation_grace < timedelta(0):
            raise ValueError("cancellation_grace must be non-negative")
        if self.heartbeat_interval + self.cancellation_grace >= self.lease_duration:
            raise ValueError(
                "heartbeat_interval plus cancellation_grace must be shorter than lease"
            )

    def run_once(self) -> bool:
        """领取并处理一个任务；当前无任务时返回 False。"""
        now = self.clock()
        job = self.store.claim_next_job(
            lease_owner=self.worker_id,
            now=now,
            lease_duration=self.lease_duration,
        )
        if job is None:
            return False
        try:
            execution_spec = self.store.get_execution_spec(job.job_id)
        except Exception as error:
            self._fail_owned_job(job.job_id, error)
            raise
        self._run_claimed_job(job, execution_spec)
        return True

    def run_forever(self, *, idle_sleep_seconds: float = 1.0) -> None:
        """持续轮询任务，空闲时按固定间隔休眠。"""
        if idle_sleep_seconds < 0:
            raise ValueError("idle_sleep_seconds must be non-negative")
        while True:
            if not self.run_once():
                self.sleep(idle_sleep_seconds)

    def _run_claimed_job(
        self,
        initial_job: BattleInferenceJobSnapshot,
        execution_spec: BattleInferenceExecutionSpec,
    ) -> None:
        """维护一个任务的队列、heartbeat、取消与最终收口。"""
        executor = self.executor_factory(execution_spec.process_count)
        progress_manager = Manager()
        progress_queue = progress_manager.Queue()
        in_flight: dict[Future[object], BattleInferenceCaseSnapshot] = {}
        last_heartbeat = self.clock()
        cancellation_started_at: datetime | None = None
        try:
            while True:
                now = self.clock()
                snapshot = self.store.get_job(
                    initial_job.job_id,
                    calculation_revision=initial_job.calculation_revision,
                )
                cancelling = snapshot.status is BattleInferenceJobStatus.CANCEL_REQUESTED
                if cancelling and cancellation_started_at is None:
                    cancellation_started_at = now
                if cancelling:
                    self.store.cancel_unclaimed_cases(snapshot.job_id, cancelled_at=now)
                else:
                    self._fill_queue(
                        snapshot,
                        execution_spec,
                        executor,
                        in_flight,
                        progress_queue,
                    )
                self._drain_progress_queue(snapshot, in_flight, progress_queue)
                self._record_completed(snapshot, in_flight)
                if not cancelling and now - last_heartbeat >= self.heartbeat_interval:
                    self.store.heartbeat_job(
                        snapshot.job_id,
                        lease_owner=self.worker_id,
                        now=now,
                        lease_duration=self.lease_duration,
                    )
                    if in_flight:
                        self.store.heartbeat_cases(
                            snapshot.job_id,
                            tuple(
                                case.definition.configuration_pair_id
                                for case in in_flight.values()
                            ),
                            lease_owner=self.worker_id,
                            now=now,
                            lease_duration=self.lease_duration,
                        )
                    last_heartbeat = now
                if (
                    cancelling
                    and cancellation_started_at is not None
                    and now - cancellation_started_at >= self.cancellation_grace
                    and in_flight
                ):
                    executor.terminate()
                    self._cancel_active_cases(snapshot, in_flight, now=now)
                latest = self.store.get_job(snapshot.job_id)
                if (
                    not in_flight
                    and latest.progress.pending_count == 0
                    and latest.progress.running_count == 0
                ):
                    self.store.finalize_job(latest.job_id, completed_at=self.clock())
                    return
                self.sleep(self.poll_interval_seconds)
        except Exception as error:
            self._fail_owned_job(initial_job.job_id, error)
            raise
        finally:
            executor.shutdown()
            progress_manager.shutdown()

    def _fail_owned_job(self, job_id: str, error: Exception) -> None:
        """尽力记录仍由当前 coordinator 持有的任务级失败。"""
        try:
            self.store.fail_job_if_owned(
                job_id,
                lease_owner=self.worker_id,
                failure_code=BattleInferenceFailureCode.WORKER_CRASH,
                diagnostic=f"{type(error).__name__}: {error}",
                failed_at=self.clock(),
            )
        except Exception:  # noqa: BLE001 - 清理失败必须保留原异常。
            return

    def _fill_queue(
        self,
        job: BattleInferenceJobSnapshot,
        execution_spec: BattleInferenceExecutionSpec,
        executor: WorkerExecutor,
        in_flight: dict[Future[object], BattleInferenceCaseSnapshot],
        progress_queue: Any,
    ) -> None:
        """在 queue depth 范围内领取、准备并提交新的配置。"""
        available = execution_spec.queue_depth - len(in_flight)
        if (
            available <= 0
            or (job.progress.pending_count <= 0 and job.progress.running_count <= 0)
        ):
            return
        claimed = self.store.claim_cases(
            job.job_id,
            lease_owner=self.worker_id,
            now=self.clock(),
            lease_duration=self.lease_duration,
            limit=min(available, execution_spec.process_count),
            calculation_revision=job.calculation_revision,
        )
        for case in claimed:
            try:
                prepared = self.preparer.prepare(job, case, execution_spec)
            except Exception as error:
                self._record_case_result(
                    job,
                    case,
                    failure_result(
                        BattleInferenceFailureCode.INVALID_CONFIGURATION,
                        error,
                    ),
                )
                continue
            future = executor.submit(
                execute_prepared_battle_inference_case,
                prepared,
                progress_queue,
            )
            in_flight[future] = case

    def _drain_progress_queue(
        self,
        job: BattleInferenceJobSnapshot,
        in_flight: dict[Future[object], BattleInferenceCaseSnapshot],
        progress_queue: Any,
    ) -> None:
        """把子进程积压的运行进度写入当前仍在执行的 case。

        Args:
            job: 当前 coordinator 正在维护的任务快照。
            in_flight: 尚未返回终态结果的 Future 到 case 映射。
            progress_queue: 子进程共享写入、父进程轮询读取的队列代理。
        """
        active_pair_ids = {
            case.definition.configuration_pair_id for case in in_flight.values()
        }
        while True:
            try:
                event = progress_queue.get_nowait()
            except Empty:
                return
            if not isinstance(event, dict):
                continue
            pair_id = event.get("configuration_pair_id")
            if not isinstance(pair_id, str) or pair_id not in active_pair_ids:
                continue
            try:
                progress = BattleInferenceCaseProgress(
                    phase=str(event.get("phase") or "building_graph"),
                    observed_node_count=int(event.get("node_count") or 0),
                    observed_edge_count=int(event.get("edge_count") or 0),
                    expanded_node_count=int(event.get("expanded_node_count") or 0),
                    frontier_count=int(event.get("frontier_count") or 0),
                    action_pair_completed_count=int(
                        event.get("action_pair_completed_count") or 0
                    ),
                    action_pair_total_count=int(
                        event.get("action_pair_total_count") or 0
                    ),
                )
                self.store.record_case_progress(
                    job.job_id,
                    pair_id,
                    progress,
                    lease_owner=self.worker_id,
                    observed_at=self.clock(),
                    calculation_revision=job.calculation_revision,
                )
            except (
                BattleInferenceCalculationRevisionMismatch,
                BattleInferenceLeaseConflict,
                ValueError,
            ):
                # 取消、lease 恢复或旧事件乱序时，终态结果/取消收口优先，进度可丢弃。
                continue

    def _record_completed(
        self,
        job: BattleInferenceJobSnapshot,
        in_flight: dict[Future[object], BattleInferenceCaseSnapshot],
    ) -> None:
        """把已完成 Future 转换为 #85 终态并由父进程写入 PostgreSQL。"""
        completed = tuple(future for future in in_flight if future.done())
        for future in completed:
            case = in_flight.pop(future)
            try:
                execution_result = future.result()
                if not isinstance(execution_result, ConfigurationPairExecutionResult):
                    raise TypeError("worker returned an unexpected result type")
                result = persistent_result(execution_result)
            except Exception as error:
                result = failure_result(BattleInferenceFailureCode.WORKER_CRASH, error)
            self._record_case_result(job, case, result)

    def _record_case_result(
        self,
        job: BattleInferenceJobSnapshot,
        case: BattleInferenceCaseSnapshot,
        result: BattleInferenceCaseResult,
    ) -> None:
        """使用当前有效 case lease 幂等保存一个终态结果。"""
        self.store.record_case_result(
            job.job_id,
            case.definition.configuration_pair_id,
            result,
            lease_owner=self.worker_id,
            completed_at=self.clock(),
            calculation_revision=job.calculation_revision,
        )

    def _cancel_active_cases(
        self,
        job: BattleInferenceJobSnapshot,
        in_flight: dict[Future[object], BattleInferenceCaseSnapshot],
        *,
        now: datetime,
    ) -> None:
        """宽限期结束后把仍运行的配置原子记录为取消。"""
        cancelled = BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.CANCELLED,
            failure_code=BattleInferenceFailureCode.CANCELLED,
            diagnostic="job cancellation grace period expired",
        )
        for future, case in tuple(in_flight.items()):
            future.cancel()
            self.store.record_case_result(
                job.job_id,
                case.definition.configuration_pair_id,
                cancelled,
                lease_owner=self.worker_id,
                completed_at=now,
                calculation_revision=job.calculation_revision,
            )
            del in_flight[future]


def default_worker_id() -> str:
    """返回适合日志和 lease owner 的默认进程标识。"""
    return f"battle-worker-{os.getpid()}"
