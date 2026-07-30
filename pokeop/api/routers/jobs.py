"""暴露通用后台推演任务列表、详情和取消入口。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from pokeop.api.routers._configuration_jobs.dependencies import (
    JobStoreDependency,
    raise_job_http_error,
)
from pokeop.api.schemas.inference_jobs import (
    CancelInferenceJobResponse,
    InferenceJobCountsResponse,
    InferenceJobLinksResponse,
    InferenceJobListResponse,
    InferenceJobProgressResponse,
    InferenceJobResourceResponse,
    InferenceJobRunningCaseResponse,
    InferenceJobSummaryResponse,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceCaseSnapshot,
    BattleInferenceCaseStatus,
    BattleInferenceJobRepositoryError,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
)
from pokeop.application.use_cases.battle_inference_jobs import BattleInferenceExecutionSpec
from pokeop.application.use_cases.fixed_battle_jobs import (
    FIXED_ONE_ON_ONE_JOB_ID_PREFIX,
)
from pokeop.persistence.battle_inference.runtime_repository import (
    BattleInferenceExecutionSpecNotFound,
)


ROUTE_PREFIX_OVERRIDE = "/v1/inference"
router = APIRouter()


@router.get(
    "/jobs",
    response_model=InferenceJobListResponse,
    summary="分页查看后台推演任务",
)
def list_inference_jobs(
    store: JobStoreDependency,
    status: list[str] | None = Query(default=None),
    job_type: Literal["fixed-one-on-one", "configuration-space"] | None = None,
    active_only: bool = False,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> InferenceJobListResponse:
    """返回一页任务列表，供固定推演页默认收起任务面板轮询。

    Args:
        store: 后台任务 store。
        status: 可选 repository 状态过滤。
        job_type: 可选任务类型过滤；固定任务用稳定 ID 前缀区分。
        active_only: 是否只返回未进入终态的任务。
        cursor: 下一页偏移量文本；None 表示第一页。
        limit: 本页最多返回数量。

    Returns:
        任务摘要列表和下一页 cursor。
    """
    try:
        offset = _cursor_offset(cursor)
        statuses = _statuses(status or [])
        prefix = (
            FIXED_ONE_ON_ONE_JOB_ID_PREFIX
            if job_type == "fixed-one-on-one"
            else None
        )
        jobs = store.list_jobs(
            statuses=statuses,
            active_only=active_only,
            job_id_prefix=prefix,
            offset=offset,
            limit=limit,
        )
        if job_type == "configuration-space":
            jobs = tuple(
                job for job in jobs if not job.job_id.startswith(FIXED_ONE_ON_ONE_JOB_ID_PREFIX)
            )
        items = [_summary_response(store, job) for job in jobs]
        next_cursor = str(offset + len(items)) if len(items) == limit else None
        return InferenceJobListResponse(items=items, next_cursor=next_cursor)
    except (BattleInferenceJobRepositoryError, ValueError) as error:
        raise_job_http_error(error)


@router.get(
    "/jobs/{job_id}",
    response_model=InferenceJobSummaryResponse,
    summary="查看后台推演任务详情",
)
def get_inference_job(
    job_id: str,
    store: JobStoreDependency,
) -> InferenceJobSummaryResponse:
    """按稳定 job ID 返回任务最新状态和可靠进度。"""
    try:
        return _summary_response(store, store.get_job(job_id))
    except (BattleInferenceJobRepositoryError, BattleInferenceExecutionSpecNotFound) as error:
        raise_job_http_error(error)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=CancelInferenceJobResponse,
    summary="请求取消后台推演任务",
)
def cancel_inference_job(
    job_id: str,
    store: JobStoreDependency,
) -> CancelInferenceJobResponse:
    """幂等请求取消任务；已进入终态的任务保持原状态。"""
    try:
        job = store.request_cancel(job_id, requested_at=datetime.now(timezone.utc))
        return CancelInferenceJobResponse(job=_summary_response(store, job))
    except BattleInferenceJobRepositoryError as error:
        raise_job_http_error(error)


def _summary_response(
    store,
    job: BattleInferenceJobSnapshot,
) -> InferenceJobSummaryResponse:
    """把 repository 快照投影为通用任务 DTO。

    Args:
        store: 用于读取冻结执行规格的任务 store。
        job: 已读取的任务生命周期和进度快照。

    Returns:
        不包含完整状态图或 case 明细的任务摘要。
    """
    spec = store.get_execution_spec(job.job_id)
    progress = job.progress
    completed_count = (
        progress.succeeded_count
        + progress.failed_count
        + progress.truncated_count
        + progress.cancelled_count
    )
    return InferenceJobSummaryResponse(
        job_id=job.job_id,
        job_type=_job_type(job.job_id),
        status=job.status.value,
        phase=_phase(job.status),
        ruleset_id=job.ruleset_id,
        version_group_id=job.version_group_id,
        calculation_revision=job.calculation_revision,
        created_at=job.created_at.isoformat(),
        started_at=job.started_at.isoformat() if job.started_at is not None else None,
        updated_at=job.updated_at.isoformat(),
        finished_at=job.completed_at.isoformat() if job.completed_at is not None else None,
        cancel_requested_at=(
            job.cancel_requested_at.isoformat()
            if job.cancel_requested_at is not None
            else None
        ),
        can_cancel=job.status
        not in {
            BattleInferenceJobStatus.SUCCEEDED,
            BattleInferenceJobStatus.COMPLETED_WITH_FAILURES,
            BattleInferenceJobStatus.CANCELLED,
            BattleInferenceJobStatus.FAILED,
        },
        progress=InferenceJobProgressResponse(
            phase=_phase(job.status),
            counts=InferenceJobCountsResponse(
                total=progress.total_count,
                pending=progress.pending_count,
                running=progress.running_count,
                succeeded=progress.succeeded_count,
                failed=progress.failed_count,
                truncated=progress.truncated_count,
                cancelled=progress.cancelled_count,
                completed=completed_count,
            ),
            state_nodes=InferenceJobResourceResponse(
                used=progress.cumulative_node_count,
                limit=progress.total_count * spec.max_nodes_per_pair,
            ),
            state_edges=InferenceJobResourceResponse(
                used=progress.cumulative_edge_count,
                limit=progress.total_count * spec.max_edges_per_pair,
            ),
            running_case=_running_case_response(store, job, spec),
            elapsed_seconds=_elapsed_seconds(job),
        ),
        error_code=job.last_failure_code.value if job.last_failure_code is not None else None,
        error_message=job.last_failure_diagnostic,
        links=InferenceJobLinksResponse(
            self=f"/v1/inference/jobs/{job.job_id}",
            cancel=f"/v1/inference/jobs/{job.job_id}/cancel",
        ),
    )


def _running_case_response(
    store,
    job: BattleInferenceJobSnapshot,
    spec: BattleInferenceExecutionSpec,
) -> InferenceJobRunningCaseResponse | None:
    """读取当前任务的第一个 running case 并转换为进度 DTO。

    Args:
        store: 后台任务 store。
        job: 当前任务快照。
        spec: 创建任务时冻结的单 case 预算。

    Returns:
        有 running case 时返回最新观测进度；没有 running case 时返回 None。
    """
    if job.progress.running_count == 0:
        return None
    page = store.list_cases(
        job.job_id,
        BattleInferenceCaseFilter(
            statuses=(BattleInferenceCaseStatus.RUNNING,),
            limit=1,
        ),
        calculation_revision=job.calculation_revision,
    )
    if not page.items:
        return None
    return _case_progress_response(page.items[0], spec)


def _case_progress_response(
    case: BattleInferenceCaseSnapshot,
    spec: BattleInferenceExecutionSpec,
) -> InferenceJobRunningCaseResponse:
    """把 running case 快照转换为前端可绘制百分比的 DTO。

    Args:
        case: repository 返回的运行中配置对。
        spec: 单 case 节点和边上限。

    Returns:
        包含阶段、百分比、节点、边和队列长度的运行进度。
    """
    node_ratio = _resource_ratio(case.observed_node_count, spec.max_nodes_per_pair)
    edge_ratio = _resource_ratio(case.observed_edge_count, spec.max_edges_per_pair)
    return InferenceJobRunningCaseResponse(
        configuration_id=case.definition.configuration_pair_id,
        phase=case.progress_phase or _phase_from_case(case),
        percent=round(min(100.0, max(node_ratio, edge_ratio) * 100.0), 2),
        observed_nodes=case.observed_node_count,
        observed_edges=case.observed_edge_count,
        node_limit=spec.max_nodes_per_pair,
        edge_limit=spec.max_edges_per_pair,
        expanded_nodes=case.expanded_node_count,
        frontier_nodes=case.frontier_count,
        action_pairs_completed=case.action_pair_completed_count,
        action_pairs_total=case.action_pair_total_count,
        updated_at=case.updated_at.isoformat(),
    )


def _resource_ratio(used: int, limit: int) -> float:
    """计算资源使用比例；非正上限按 0 处理。"""
    if limit <= 0:
        return 0.0
    return used / limit


def _phase_from_case(case: BattleInferenceCaseSnapshot) -> str:
    """为尚未收到 observer 事件的运行中 case 提供稳定阶段名。"""
    if case.status is BattleInferenceCaseStatus.RUNNING:
        return "running"
    return case.status.value


def _job_type(job_id: str) -> Literal["fixed-one-on-one", "configuration-space"]:
    """根据稳定 job ID 前缀返回任务类型。"""
    if job_id.startswith(FIXED_ONE_ON_ONE_JOB_ID_PREFIX):
        return "fixed-one-on-one"
    return "configuration-space"


def _phase(status: BattleInferenceJobStatus) -> str:
    """从现有生命周期状态推导不会伪造百分比的粗粒度阶段。"""
    if status is BattleInferenceJobStatus.PENDING:
        return "queued"
    if status is BattleInferenceJobStatus.PREPARING:
        return "preparing_battle"
    if status is BattleInferenceJobStatus.RUNNING:
        return "solving_probabilities"
    if status is BattleInferenceJobStatus.CANCEL_REQUESTED:
        return "cancel_requested"
    if status in {
        BattleInferenceJobStatus.SUCCEEDED,
        BattleInferenceJobStatus.COMPLETED_WITH_FAILURES,
    }:
        return "completed"
    if status is BattleInferenceJobStatus.CANCELLED:
        return "cancelled"
    return "failed"


def _elapsed_seconds(job: BattleInferenceJobSnapshot) -> float | None:
    """根据 started/completed/updated 时间返回运行时长秒数。"""
    if job.started_at is None:
        return None
    end = job.completed_at or job.updated_at
    return max(0.0, (end - job.started_at).total_seconds())


def _cursor_offset(cursor: str | None) -> int:
    """解析稳定 offset cursor。"""
    if cursor is None:
        return 0
    try:
        value = int(cursor)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_cursor", "message": "cursor must be an offset"},
        ) from error
    if value < 0:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_cursor", "message": "cursor must be non-negative"},
        )
    return value


def _statuses(values: list[str]) -> tuple[BattleInferenceJobStatus, ...]:
    """把查询参数状态字符串转换为 repository 枚举。"""
    try:
        return tuple(BattleInferenceJobStatus(value) for value in values)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_status", "message": "unknown job status"},
        ) from error


__all__ = ["router"]
