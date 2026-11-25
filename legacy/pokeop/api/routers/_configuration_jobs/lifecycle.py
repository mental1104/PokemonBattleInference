"""暴露后台任务创建、状态轮询和取消入口。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from pokeop.api.routers._configuration_jobs.dependencies import (
    JobStoreDependency,
    create_use_case,
    raise_job_http_error,
)
from pokeop.api.routers._configuration_jobs.presenters import (
    job_status_response,
    public_job_status,
)
from pokeop.api.schemas.configuration_jobs import (
    BattleInferenceJobStatusResponse,
    CancelBattleInferenceJobResponse,
    CreateBattleInferenceJobRequest,
    CreateBattleInferenceJobResponse,
)
from pokeop.application.battle_candidate_pool.admission import (
    StrictMechanismAdmissionRejected,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceJobRepositoryError,
    BattleInferenceJobStatus,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    SubmitBattleInferenceJobCommand,
)
from pokeop.persistence.battle_inference.runtime_repository import (
    BattleInferenceExecutionSpecNotFound,
)

router = APIRouter()


@router.post(
    "/configuration-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateBattleInferenceJobResponse,
    summary="创建通用 1v1 技能池后台推演任务",
)
def create_configuration_job(
    request: CreateBattleInferenceJobRequest,
    store: JobStoreDependency,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> CreateBattleInferenceJobResponse:
    """完成服务端重校验和预算冻结后立即返回 job ID。"""
    try:
        move_pool, execution_spec = request.to_application()
        submitted = create_use_case(store).execute(
            SubmitBattleInferenceJobCommand(
                move_pool=move_pool,
                execution_spec=execution_spec,
                idempotency_key=idempotency_key,
            ),
            created_at=datetime.now(timezone.utc),
        )
    except StrictMechanismAdmissionRejected as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "strict_mechanism_admission_rejected",
                "message": str(error),
                "failures": [
                    {
                        "source_kind": failure.key.source_kind.value,
                        "requested_identifier": failure.requested_identifier,
                        "status": failure.status.value,
                        "reason": failure.reason,
                        "missing_mechanism_identifiers": list(
                            failure.missing_mechanism_identifiers
                        ),
                    }
                    for failure in error.failures
                ],
            },
        ) from error
    except (BattleInferenceJobRepositoryError, ValueError) as error:
        raise_job_http_error(error)
    return CreateBattleInferenceJobResponse(
        job_id=submitted.job_id,
        submitted_configuration_pairs=submitted.submitted_configuration_pairs,
        created_at=submitted.created_at.isoformat(),
    )


@router.get(
    "/configuration-jobs/{job_id}",
    response_model=BattleInferenceJobStatusResponse,
    summary="轮询战斗推演后台任务状态与进度",
)
def get_configuration_job(
    job_id: str,
    store: JobStoreDependency,
) -> BattleInferenceJobStatusResponse:
    """返回任务计数、累计图规模和冻结策略。"""
    try:
        job = store.get_job(job_id)
        execution_spec = store.get_execution_spec(job_id)
    except (BattleInferenceJobRepositoryError, BattleInferenceExecutionSpecNotFound) as error:
        raise_job_http_error(error)
    return job_status_response(job, execution_spec)


@router.post(
    "/configuration-jobs/{job_id}/cancel",
    response_model=CancelBattleInferenceJobResponse,
    summary="请求取消后台推演任务",
)
def cancel_configuration_job(
    job_id: str,
    store: JobStoreDependency,
) -> CancelBattleInferenceJobResponse:
    """持久化取消请求，由 worker 停止领取并在宽限期后终止运行配置。"""
    try:
        job = store.request_cancel(
            job_id,
            requested_at=datetime.now(timezone.utc),
        )
    except BattleInferenceJobRepositoryError as error:
        raise_job_http_error(error)
    return CancelBattleInferenceJobResponse(
        job_id=job.job_id,
        cancellation_requested=(
            job.status is BattleInferenceJobStatus.CANCEL_REQUESTED
            or job.status is BattleInferenceJobStatus.CANCELLED
        ),
        status=public_job_status(job.status),
    )
