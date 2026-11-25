"""暴露技能组合预览和单个固定配置精确概率推演。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from pokeop.api.routers._configuration_jobs.dependencies import (
    JobStoreDependency,
    create_use_case as create_configuration_job_use_case,
)
from pokeop.api.schemas.battle_exploration import (
    BattleGraphExplorationResponse,
    StoredBattleInferenceJourneyResponse,
    battle_graph_exploration_response,
    stored_battle_inference_journey_response,
)
from pokeop.api.schemas.fixed_battle import (
    CreateFixedBattleJobResponse,
    FixedBattleSnapshotStepRequest,
    FixedBattleSummaryRequest,
    FixedBattleJobLinksResponse,
    MoveSetCombinationsRequest,
    MoveSetCombinationsResponse,
    fixed_battle_summary_response,
    move_set_combinations_response,
)
from pokeop.api.schemas.inference import BattleInferenceSummaryResponse
from pokeop.application.battle_graph_store import (
    BattleGraphCapacityExceeded,
    BattleGraphIdentifierCollision,
    BattleGraphStore,
    BattleGraphStoreError,
)
from pokeop.application.battle_candidate_pool.admission import (
    StrictMechanismAdmissionRejected,
    ValidateFixedMechanismSelectionCommand,
    ValidateFixedMechanismSelectionUseCase,
)
from pokeop.application.battle_candidate_pool.listing import (
    BattleCandidatePoolNotFound,
    ListBattleCandidatePoolUseCase,
)
from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceJobRepositoryError,
)
from pokeop.application.use_cases.admitted_fixed_battle import (
    RunAdmittedFixedBattleSummaryUseCase,
)
from pokeop.application.use_cases.fixed_battle_workflow import (
    EnumerateMoveSetCombinationsCommand,
    EnumerateMoveSetCombinationsUseCase,
    InferFixedBattleSummaryUseCase,
    build_fixed_inference_command,
)
from pokeop.application.use_cases.fixed_battle_jobs import (
    CreateFixedBattleInferenceJobUseCase,
    SubmitFixedBattleJobCommand,
)
from pokeop.application.use_cases.fixed_battle_snapshot import (
    SNAPSHOT_GRAPH_ID,
    ExpandFixedBattleSnapshotUseCase,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    BattleInferenceExecutionError,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
)
from pokeop.application.use_cases.store_battle_graph import (
    StoreBackedInferOneOnOneBattleUseCase,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)


ROUTE_PREFIX_OVERRIDE = "/v1/inference"
router = APIRouter()


def inference_use_case() -> InferOneOnOneBattleUseCase:
    """创建候选准入和固定摘要共享的 repository/effect composition。

    Returns:
        使用 version-aware 物化视图 repository 和透明中性 effect factory 的用例。
    """
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=MaterializedViewBattleInferenceRepository(),
        effect_factory=effect_factory,
    )
    return InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )


def combination_use_case() -> EnumerateMoveSetCombinationsUseCase:
    """创建只枚举技能组合的 application 查询用例。

    Returns:
        复用正式候选池 repository 和 effect factory 的无状态组合用例。
    """
    inference = inference_use_case()
    return EnumerateMoveSetCombinationsUseCase(
        ListBattleCandidatePoolUseCase(
            repository=inference.repository,
            effect_factory=inference.effect_factory,
        )
    )


def summary_use_case() -> RunAdmittedFixedBattleSummaryUseCase:
    """创建包含严格准入和轻量精确求解的 application 用例。

    Returns:
        API 无需理解候选池机制判断的固定配置业务编排对象。
    """
    inference = inference_use_case()
    return RunAdmittedFixedBattleSummaryUseCase(
        admission_use_case=ValidateFixedMechanismSelectionUseCase(
            inference.repository,
            inference.effect_factory,
        ),
        summary_use_case=InferFixedBattleSummaryUseCase(inference),
    )


CombinationUseCaseDependency = Annotated[
    EnumerateMoveSetCombinationsUseCase,
    Depends(combination_use_case),
]
SummaryUseCaseDependency = Annotated[
    RunAdmittedFixedBattleSummaryUseCase,
    Depends(summary_use_case),
]
InferenceUseCaseDependency = Annotated[
    InferOneOnOneBattleUseCase,
    Depends(inference_use_case),
]


def _graph_store(request: Request) -> BattleGraphStore:
    """从应用生命周期 state 读取固定配置图探索使用的共享 store。

    Args:
        request: 当前 FastAPI 请求，用于访问 lifespan 初始化的 application state。

    Returns:
        可保存完整固定推演图并供后续探索接口读取的 store。

    Raises:
        HTTPException: 应用未初始化 graph store 时返回 503。
    """
    graph_store = getattr(request.app.state, "battle_graph_store", None)
    if not isinstance(graph_store, BattleGraphStore):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "battle_graph_store_unavailable",
                "message": "battle graph store is not available",
            },
        )
    return graph_store


GraphStoreDependency = Annotated[BattleGraphStore, Depends(_graph_store)]


def _rules(
    *,
    ruleset_id: str,
    version_group_id: int,
    level: int,
    max_turns: int,
) -> BattleInferenceRules:
    """构造双方共享的首版 1v1 规则对象。

    Args:
        ruleset_id: 当前固定推演规则集稳定标识。
        version_group_id: 招式学习和历史机制使用的 PokeAPI version group。
        level: 双方共享的战斗等级。
        max_turns: 本次固定配置允许完整执行的最大回合号。

    Returns:
        禁止换人和特殊形态变化的正式领域规则对象。
    """
    return BattleInferenceRules(
        ruleset_id=ruleset_id,
        version_group_id=version_group_id,
        level=level,
        max_turns=max_turns,
    )


def _policy(value: str) -> BattleActionPolicyKind:
    """把 HTTP 稳定字符串映射为 application 行动策略枚举。

    Args:
        value: ``uniform-random`` 或仅供开发调试的 ``first-legal``。

    Returns:
        固定推演命令使用的显式策略枚举。

    Raises:
        ValueError: value 不是当前固定推演支持的策略时抛出。
    """
    if value == "uniform-random":
        return BattleActionPolicyKind.UNIFORM_RANDOM
    if value == "first-legal":
        return BattleActionPolicyKind.FIRST_LEGAL
    raise ValueError(f"unsupported battle action policy: {value!r}")


def _raise_http_error(error: Exception) -> NoReturn:
    """把候选池、准入和固定求解异常转换为稳定 HTTP 语义。

    Args:
        error: application 或 persistence 边界抛出的稳定异常。

    Raises:
        HTTPException: 候选不存在返回 404；输入、准入和资源截断返回 422。
    """
    if isinstance(error, BattleCandidatePoolNotFound):
        status_code = 404
        code = "fixed_battle_candidate_pool_not_found"
    elif isinstance(error, StrictMechanismAdmissionRejected):
        status_code = 422
        code = "fixed_battle_mechanism_rejected"
    elif isinstance(error, BattleInferenceExecutionError):
        status_code = 422
        code = "fixed_battle_not_completely_solved"
    else:
        status_code = 422
        code = "fixed_battle_invalid_request"
    detail: dict[str, object] = {"code": code, "message": str(error)}
    if isinstance(error, StrictMechanismAdmissionRejected):
        detail["failures"] = [
            {
                "requested_identifier": failure.requested_identifier,
                "status": failure.status.value,
                "reason": failure.reason,
                "missing_mechanism_identifiers": list(
                    failure.missing_mechanism_identifiers
                ),
            }
            for failure in error.failures
        ]
    raise HTTPException(status_code=status_code, detail=detail) from error


def _raise_fixed_job_http_error(error: Exception) -> NoReturn:
    """把固定任务创建错误转换为稳定 HTTP 错误。

    Args:
        error: application 或 repository 抛出的任务提交异常。

    Raises:
        HTTPException: 输入非法返回 422；幂等键冲突返回 409。
    """
    status_code = 422 if isinstance(error, ValueError) else 409
    code = (
        "fixed_battle_job_invalid_request"
        if status_code == 422
        else "fixed_battle_job_idempotency_conflict"
    )
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(error)},
    ) from error


def _raise_graph_store_http_error(error: BattleGraphStoreError) -> NoReturn:
    """把完整图保存失败转换为稳定 HTTP 服务错误。

    Args:
        error: graph store 在保存完整状态图时抛出的稳定异常。

    Raises:
        HTTPException: 容量或 ID 冲突等 store 错误统一返回 503。
    """
    if isinstance(error, BattleGraphCapacityExceeded):
        code = "battle_graph_store_capacity_exceeded"
    elif isinstance(error, BattleGraphIdentifierCollision):
        code = "battle_graph_identifier_collision"
    else:
        code = "battle_graph_store_error"
    raise HTTPException(
        status_code=503,
        detail={"code": code, "message": str(error)},
    ) from error


def _command_from_request(
    request: FixedBattleSummaryRequest,
) -> InferFixedOneOnOneBattleCommand:
    """把固定配置 HTTP 请求转换为 application 推演命令。

    Args:
        request: 双方固定配置、行动策略和图预算均已由 Pydantic 初步校验的请求。

    Returns:
        可交给摘要求解或完整图求解的统一 command。

    Raises:
        ValueError: 双方等级不一致或 action policy 不受支持时抛出。
    """
    if request.attacker.level != request.defender.level:
        raise ValueError("both sides must use the same level in v1")
    rules = _rules(
        ruleset_id=request.ruleset_id,
        version_group_id=request.version_group_id,
        level=request.attacker.level,
        max_turns=request.limits.max_turns,
    )
    return build_fixed_inference_command(
        rules=rules,
        attacker=request.attacker.to_application(),
        attacker_move_ids=tuple(request.attacker.move_ids),
        defender=request.defender.to_application(),
        defender_move_ids=tuple(request.defender.move_ids),
        attacker_policy=_policy(request.attacker_policy),
        defender_policy=_policy(request.defender_policy),
        graph_limits=StateGraphLimits(
            max_nodes=request.limits.max_nodes,
            max_edges=request.limits.max_edges,
            max_turns=request.limits.max_turns,
        ),
    )


def _fixed_job_command_from_request(
    request: FixedBattleSummaryRequest,
    *,
    idempotency_key: str,
) -> SubmitFixedBattleJobCommand:
    """把固定配置 HTTP 请求转换为后台任务提交命令。

    Args:
        request: 双方固定配置、已选技能组、行动策略和预算。
        idempotency_key: 当前 HTTP 请求提供的幂等键。

    Returns:
        不执行 solver、只描述单 case 异步任务的 application 命令。
    """
    if request.attacker.level != request.defender.level:
        raise ValueError("both sides must use the same level in v1")
    return SubmitFixedBattleJobCommand(
        ruleset_id=request.ruleset_id,
        version_group_id=request.version_group_id,
        attacker=request.attacker.to_application(),
        attacker_move_ids=tuple(request.attacker.move_ids),
        defender=request.defender.to_application(),
        defender_move_ids=tuple(request.defender.move_ids),
        attacker_policy=_policy(request.attacker_policy),
        defender_policy=_policy(request.defender_policy),
        max_nodes=request.limits.max_nodes,
        max_edges=request.limits.max_edges,
        max_turns=request.limits.max_turns,
        idempotency_key=idempotency_key,
    )


def _validate_fixed_mechanisms(
    inference: InferOneOnOneBattleUseCase,
    command: InferFixedOneOnOneBattleCommand,
) -> None:
    """复用候选池严格准入，避免完整图入口绕过页面禁用状态。

    Args:
        inference: 与随后求解共享 repository 和 effect factory 的 application 用例。
        command: 已构造好的双方固定推演命令。

    Raises:
        StrictMechanismAdmissionRejected: 任一招式、特性或道具不可进入精确推演时抛出。
    """
    admission = ValidateFixedMechanismSelectionUseCase(
        inference.repository,
        inference.effect_factory,
    )
    for selection in (command.attacker, command.defender):
        admission.execute(
            ValidateFixedMechanismSelectionCommand(
                rules=command.rules,
                pokemon_id=selection.pokemon_id,
                move_ids=selection.move_ids,
                ability_identifier=selection.ability_identifier,
                item_identifier=selection.item_identifier,
            )
        )


@router.post(
    "/move-set-combinations",
    response_model=MoveSetCombinationsResponse,
    summary="枚举双方候选池产生的规范化技能组",
)
def enumerate_move_set_combinations(
    request: MoveSetCombinationsRequest,
    use_case: CombinationUseCaseDependency,
) -> MoveSetCombinationsResponse:
    """严格校验候选后返回左右技能组，不启动 worker 或状态图。

    Args:
        request: 双方固定配置、候选技能池和精确规则轴。
        use_case: 可被测试 dependency override 替换的组合枚举用例。

    Returns:
        每侧最多 210 个技能组以及理论配置对数量。

    Raises:
        HTTPException: 候选池不存在或输入没有通过严格组合校验时抛出。
    """
    try:
        if request.attacker.level != request.defender.level:
            raise ValueError("both sides must use the same level in v1")
        rules = _rules(
            ruleset_id=request.ruleset_id,
            version_group_id=request.version_group_id,
            level=request.attacker.level,
            max_turns=20,
        )
        result = use_case.execute(
            EnumerateMoveSetCombinationsCommand(
                rules=rules,
                calculation_revision=request.calculation_revision,
                attacker=request.attacker.to_application(),
                attacker_candidate_move_ids=tuple(
                    request.attacker.candidate_move_ids
                ),
                defender=request.defender.to_application(),
                defender_candidate_move_ids=tuple(
                    request.defender.candidate_move_ids
                ),
            )
        )
        return move_set_combinations_response(result)
    except (BattleCandidatePoolNotFound, ValueError) as error:
        _raise_http_error(error)


@router.post(
    "/fixed-one-on-one-jobs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateFixedBattleJobResponse,
    summary="提交一个固定配置精确推演后台任务",
)
def create_fixed_one_on_one_job(
    request: FixedBattleSummaryRequest,
    store: JobStoreDependency,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> CreateFixedBattleJobResponse:
    """创建单固定配置后台任务并立即返回 job ID。

    Args:
        request: 与旧同步 fixed-one-on-one 兼容的固定配置请求体。
        store: 现有 battle inference job store。
        idempotency_key: 防止前端重复点击或网络重试创建多个任务的稳定键。

    Returns:
        HTTP 202 响应；不包含任何完整求解结果或状态图。

    Raises:
        HTTPException: 严格准入、输入非法或幂等键冲突时返回稳定错误。
    """
    try:
        submitted = CreateFixedBattleInferenceJobUseCase(
            store=store,
            create_job_use_case=create_configuration_job_use_case(store),
        ).execute(
            _fixed_job_command_from_request(
                request,
                idempotency_key=idempotency_key,
            ),
            created_at=datetime.now(timezone.utc),
        )
    except (BattleCandidatePoolNotFound, StrictMechanismAdmissionRejected) as error:
        _raise_http_error(error)
    except (BattleInferenceJobRepositoryError, ValueError) as error:
        _raise_fixed_job_http_error(error)
    job = submitted.job
    return CreateFixedBattleJobResponse(
        job_id=job.job_id,
        status=job.status.value,
        created_at=job.created_at.isoformat(),
        submitted_configuration_pairs=submitted.submitted_configuration_pairs,
        links=FixedBattleJobLinksResponse(
            self=f"/v1/inference/jobs/{job.job_id}",
            cancel=f"/v1/inference/jobs/{job.job_id}/cancel",
        ),
    )


@router.post(
    "/fixed-one-on-one",
    response_model=BattleInferenceSummaryResponse,
    summary="精确求解一个双方固定配置快照",
)
def infer_fixed_one_on_one(
    request: FixedBattleSummaryRequest,
    use_case: SummaryUseCaseDependency,
) -> BattleInferenceSummaryResponse:
    """对用户选中的一个技能组配置计算精确胜、负、平和期望回合。

    Args:
        request: 双方固定配置、已选技能组、行动策略和单配置图预算。
        use_case: 负责严格准入和轻量精确求解的 application 用例。

    Returns:
        明确绑定行动策略假设的精确概率摘要；不包含 graph ID 和代表路径。

    Raises:
        HTTPException: 机制未通过准入、图被截断或输入不符合首版边界时抛出。
    """
    try:
        command = _command_from_request(request)
        return fixed_battle_summary_response(use_case.execute(command))
    except (
        BattleCandidatePoolNotFound,
        StrictMechanismAdmissionRejected,
        BattleInferenceExecutionError,
        ValueError,
    ) as error:
        _raise_http_error(error)


@router.post(
    "/fixed-one-on-one/step",
    response_model=BattleGraphExplorationResponse,
    summary="按固定配置当前路径快照单步展开树状可能性",
)
def expand_fixed_one_on_one_snapshot(
    request: FixedBattleSnapshotStepRequest,
    inference: InferenceUseCaseDependency,
) -> BattleGraphExplorationResponse:
    """不等待异步全局任务完成，按 cursor 当前快照展开一层分支。

    Args:
        request: 固定配置、行动策略、运行保护和从起点开始的局部 edge cursor。
        inference: 共享正式 repository 与 effect factory 的配置准备用例。

    Returns:
        与完整图探索相同形状的当前节点、分支组和战报响应。

    Raises:
        HTTPException: 准入失败、cursor 不可重放或输入不符合首版边界时抛出。
    """
    try:
        command = _command_from_request(request)
        _validate_fixed_mechanisms(inference, command)
        result = ExpandFixedBattleSnapshotUseCase(inference).execute(
            command,
            request.cursor.to_application(
                graph_id=SNAPSHOT_GRAPH_ID,
                root_node_id=0,
            ),
        )
        return battle_graph_exploration_response(result.groups, result.report)
    except (
        BattleCandidatePoolNotFound,
        StrictMechanismAdmissionRejected,
        BattleInferenceExecutionError,
        ValueError,
    ) as error:
        _raise_http_error(error)


@router.post(
    "/fixed-one-on-one/graph",
    response_model=StoredBattleInferenceJourneyResponse,
    summary="精确求解固定配置并保存可探索完整图",
)
def infer_fixed_one_on_one_graph(
    request: FixedBattleSummaryRequest,
    inference: InferenceUseCaseDependency,
    graph_store: GraphStoreDependency,
) -> StoredBattleInferenceJourneyResponse:
    """对单个固定配置求解并返回后续树状探索所需的 graph handle。

    Args:
        request: 与 summary-only 入口相同的固定配置请求。
        inference: 共享正式 repository 与 effect factory 的完整图推演用例。
        graph_store: 当前 backend 进程生命周期内保存完整图的 store。

    Returns:
        同时包含全局胜负平 summary 和可跨请求探索的 graph handle。

    Raises:
        HTTPException: 准入、求解或 graph store 保存失败时返回稳定 HTTP 错误。
    """
    try:
        command = _command_from_request(request)
        _validate_fixed_mechanisms(inference, command)
        stored = StoreBackedInferOneOnOneBattleUseCase(
            inference_use_case=inference,
            graph_store=graph_store,
        ).execute_fixed_with_handle(command)
        return stored_battle_inference_journey_response(stored)
    except (
        BattleCandidatePoolNotFound,
        StrictMechanismAdmissionRejected,
        BattleInferenceExecutionError,
        ValueError,
    ) as error:
        _raise_http_error(error)
    except BattleGraphStoreError as error:
        _raise_graph_store_http_error(error)


__all__ = ["router"]
