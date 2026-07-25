"""把后台任务与配置快照投影为稳定 HTTP DTO。"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pokeop.api.schemas.configuration_jobs import (
    BattleInferenceCasePageResponse,
    BattleInferenceCaseResponse,
    BattleInferenceJobCountsResponse,
    BattleInferenceJobStatusResponse,
    BattleInferenceResourceProgressResponse,
    ExactProbabilityResponse,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceCaseSnapshot,
    BattleInferenceJobRepositoryError,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
    BattleInferenceProbability,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    decode_one_on_one_configuration_id,
)
from pokeop.persistence.battle_inference.runtime_repository import (
    PostgresBattleInferenceJobStore,
)
from pokeop.api.routers._configuration_jobs.dependencies import raise_job_http_error


def job_status_response(
    job: BattleInferenceJobSnapshot,
    execution_spec: BattleInferenceExecutionSpec,
) -> BattleInferenceJobStatusResponse:
    """返回任务计数、累计图规模和冻结策略。"""
    progress = job.progress
    return BattleInferenceJobStatusResponse(
        job_id=job.job_id,
        status=public_job_status(job.status),
        cancellation_requested=job.status is BattleInferenceJobStatus.CANCEL_REQUESTED,
        counts=BattleInferenceJobCountsResponse(
            total=progress.total_count,
            completed=(
                progress.succeeded_count
                + progress.failed_count
                + progress.truncated_count
                + progress.cancelled_count
            ),
            succeeded=progress.succeeded_count,
            failed=progress.failed_count,
            truncated=progress.truncated_count,
            running=progress.running_count,
            pending=progress.pending_count,
            cancelled=progress.cancelled_count,
        ),
        state_nodes=BattleInferenceResourceProgressResponse(
            used=progress.cumulative_node_count,
            limit=progress.total_count * execution_spec.max_nodes_per_pair,
        ),
        state_edges=BattleInferenceResourceProgressResponse(
            used=progress.cumulative_edge_count,
            limit=progress.total_count * execution_spec.max_edges_per_pair,
        ),
        ruleset_id=job.ruleset_id,
        version_group_id=job.version_group_id,
        calculation_revision=job.calculation_revision,
        weight_assumption=execution_spec.weight_assumption,
        attacker_policy=execution_spec.attacker_policy,
        defender_policy=execution_spec.defender_policy,
        last_failure_code=(
            job.last_failure_code.value if job.last_failure_code is not None else None
        ),
        last_failure_diagnostic=job.last_failure_diagnostic,
        created_at=job.created_at.isoformat(),
        updated_at=job.updated_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at is not None else None,
    )


def case_page_response(
    store: PostgresBattleInferenceJobStore,
    job_id: str,
    query: BattleInferenceCaseFilter,
) -> BattleInferenceCasePageResponse:
    """执行 repository 分页并转换为 HTTP DTO。"""
    try:
        page = store.list_cases(job_id, query)
    except BattleInferenceJobRepositoryError as error:
        raise_job_http_error(error)
    next_offset = page.offset + len(page.items)
    return BattleInferenceCasePageResponse(
        job_id=job_id,
        offset=page.offset,
        limit=page.limit,
        total=page.total_count,
        next_cursor=str(next_offset) if next_offset < page.total_count else None,
        items=[case_response(item) for item in page.items],
    )


def case_response(case: BattleInferenceCaseSnapshot) -> BattleInferenceCaseResponse:
    """把持久化 case 快照转换为前端可展示摘要。"""
    normalized = decode_one_on_one_configuration_id(
        case.definition.configuration_pair_id
    )
    return BattleInferenceCaseResponse(
        configuration_id=case.definition.configuration_pair_id,
        sequence_no=case.sequence_no,
        status=case.status.value,
        attacker_pokemon_id=normalized.attacker.pokemon_id,
        defender_pokemon_id=normalized.defender.pokemon_id,
        attacker_move_ids=list(case.definition.attacker_move_ids),
        defender_move_ids=list(case.definition.defender_move_ids),
        attacker_win_probability=_probability_response(case.attacker_win),
        defender_win_probability=_probability_response(case.defender_win),
        draw_probability=_probability_response(case.draw),
        expected_turns_kind=(
            case.expected_turns.kind.value if case.expected_turns is not None else None
        ),
        expected_turns=_expected_turns_text(case),
        node_count=case.node_count,
        edge_count=case.edge_count,
        failure_code=case.failure_code.value if case.failure_code is not None else None,
        diagnostic=case.diagnostic,
        attempt_count=case.attempt_count,
    )


def public_job_status(
    status_value: BattleInferenceJobStatus,
) -> Literal["queued", "running", "completed", "partial", "cancelled", "failed"]:
    """把 repository 细粒度状态压缩为轮询页面生命周期。"""
    if status_value in {
        BattleInferenceJobStatus.PENDING,
        BattleInferenceJobStatus.PREPARING,
    }:
        return "queued"
    if status_value in {
        BattleInferenceJobStatus.RUNNING,
        BattleInferenceJobStatus.CANCEL_REQUESTED,
    }:
        return "running"
    if status_value is BattleInferenceJobStatus.SUCCEEDED:
        return "completed"
    if status_value is BattleInferenceJobStatus.COMPLETED_WITH_FAILURES:
        return "partial"
    if status_value is BattleInferenceJobStatus.CANCELLED:
        return "cancelled"
    return "failed"


def _probability_response(
    probability: BattleInferenceProbability | None,
) -> ExactProbabilityResponse | None:
    """保留数据库中的任意精度分子分母并提供展示小数。"""
    if probability is None:
        return None
    value = Fraction(probability.numerator, probability.denominator)
    return ExactProbabilityResponse(
        numerator=str(value.numerator),
        denominator=str(value.denominator),
        decimal=float(value),
    )


def _expected_turns_text(case: BattleInferenceCaseSnapshot) -> str | None:
    """返回有限分数或 infinite/unavailable 文本。"""
    expected = case.expected_turns
    if expected is None:
        return None
    if expected.numerator is None or expected.denominator is None:
        return expected.kind.value
    return f"{expected.numerator}/{expected.denominator}"
