"""暴露配置结果、失败诊断和按需完整图入口。"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from pokeop.api.routers._configuration_jobs.dependencies import (
    GraphStoreDependency,
    JobStoreDependency,
    inference_use_case,
    raise_job_http_error,
)
from pokeop.api.routers._configuration_jobs.presenters import case_page_response
from pokeop.api.schemas.battle_exploration import (
    StoredBattleInferenceJourneyResponse,
    stored_battle_inference_journey_response,
)
from pokeop.api.schemas.configuration_jobs import BattleInferenceCasePageResponse
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceCaseStatus,
    BattleInferenceFailureCode,
    BattleInferenceJobRepositoryError,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.battle_inference_jobs import (
    decode_one_on_one_configuration_id,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    InferFixedOneOnOneBattleCommand,
    PokemonInferenceSelection,
)
from pokeop.application.use_cases.run_battle_inference_worker import (
    battle_action_policy_kind,
)
from pokeop.application.use_cases.store_battle_graph import (
    StoreBackedInferOneOnOneBattleUseCase,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.persistence.battle_inference.runtime_repository import (
    BattleInferenceExecutionSpecNotFound,
)

router = APIRouter()


@router.get(
    "/configuration-jobs/{job_id}/results",
    response_model=BattleInferenceCasePageResponse,
    summary="分页读取全部配置执行摘要",
)
def list_configuration_job_results(
    job_id: str,
    store: JobStoreDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    case_status: Annotated[str | None, Query(alias="status")] = None,
) -> BattleInferenceCasePageResponse:
    """按稳定 sequence 分页读取任意状态的轻量结果。"""
    statuses = ()
    if case_status is not None:
        try:
            statuses = (BattleInferenceCaseStatus(case_status),)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    return case_page_response(
        store,
        job_id,
        BattleInferenceCaseFilter(statuses=statuses, offset=offset, limit=limit),
    )


@router.get(
    "/configuration-jobs/{job_id}/issues",
    response_model=BattleInferenceCasePageResponse,
    summary="分页读取失败与截断配置诊断",
)
def list_configuration_job_issues(
    job_id: str,
    store: JobStoreDependency,
    issue_status: Annotated[
        Literal["failed", "truncated"] | None,
        Query(alias="status"),
    ] = None,
    error_code: str | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> BattleInferenceCasePageResponse:
    """使用轻量 offset cursor 返回失败或截断详情。"""
    statuses = (
        (BattleInferenceCaseStatus(issue_status),)
        if issue_status is not None
        else (
            BattleInferenceCaseStatus.FAILED,
            BattleInferenceCaseStatus.TRUNCATED,
        )
    )
    failure_codes = ()
    if error_code is not None:
        try:
            failure_codes = (BattleInferenceFailureCode(error_code),)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        offset = int(cursor) if cursor is not None else 0
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="cursor must be an integer offset",
        ) from error
    return case_page_response(
        store,
        job_id,
        BattleInferenceCaseFilter(
            statuses=statuses,
            failure_codes=failure_codes,
            offset=offset,
            limit=limit,
        ),
    )


@router.post(
    "/configuration-jobs/{job_id}/configurations/{configuration_id}/graph",
    response_model=StoredBattleInferenceJourneyResponse,
    summary="为已完成配置按需重算并保存完整状态图",
)
def create_configuration_graph(
    job_id: str,
    configuration_id: str,
    store: JobStoreDependency,
    graph_store: GraphStoreDependency,
) -> StoredBattleInferenceJourneyResponse:
    """只为用户明确查看的单配置生成短生命周期完整图。"""
    try:
        job = store.get_job(job_id)
        execution_spec = store.get_execution_spec(job_id)
        page = store.list_cases(
            job_id,
            BattleInferenceCaseFilter(configuration_id=configuration_id, limit=3),
            calculation_revision=job.calculation_revision,
        )
    except (BattleInferenceJobRepositoryError, BattleInferenceExecutionSpecNotFound) as error:
        raise_job_http_error(error)
    case = next(
        (
            item
            for item in page.items
            if item.definition.configuration_pair_id == configuration_id
        ),
        None,
    )
    if case is None:
        raise HTTPException(status_code=404, detail="configuration does not exist in job")
    if case.status is not BattleInferenceCaseStatus.SUCCEEDED:
        raise HTTPException(
            status_code=409,
            detail="only a succeeded configuration can generate a full graph",
        )
    normalized = decode_one_on_one_configuration_id(configuration_id)
    rules = BattleInferenceRules(
        ruleset_id=job.ruleset_id,
        version_group_id=job.version_group_id,
        level=normalized.attacker.level,
        max_turns=execution_spec.max_turns,
    )
    command = InferFixedOneOnOneBattleCommand(
        rules=rules,
        attacker=_fixed_selection(normalized.attacker, normalized.attacker_move_ids),
        defender=_fixed_selection(normalized.defender, normalized.defender_move_ids),
        attacker_policy=battle_action_policy_kind(execution_spec.attacker_policy),
        defender_policy=battle_action_policy_kind(execution_spec.defender_policy),
        graph_limits=StateGraphLimits(
            max_nodes=execution_spec.max_nodes_per_pair,
            max_edges=execution_spec.max_edges_per_pair,
            max_turns=execution_spec.max_turns,
        ),
    )
    try:
        stored = StoreBackedInferOneOnOneBattleUseCase(
            inference_use_case=inference_use_case(),
            graph_store=graph_store,
        ).execute_fixed_with_handle(command)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return stored_battle_inference_journey_response(stored)


def _fixed_selection(fixed, move_ids: tuple[int, ...]) -> PokemonInferenceSelection:
    """把 canonical 固定配置转换为现有单配置推演选择。"""
    if fixed.form_id is not None:
        raise HTTPException(
            status_code=422,
            detail="explicit form_id is not supported yet",
        )
    return PokemonInferenceSelection(
        pokemon_id=fixed.pokemon_id,
        move_ids=move_ids,
        ability_identifier=fixed.ability_identifier,
        item_identifier=fixed.item_identifier,
        stat_preset_key=fixed.stat_profile_id,
    )
