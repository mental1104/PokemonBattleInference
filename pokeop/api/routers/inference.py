"""暴露独立于基础伤害计算器的 1v1 推演与状态图渐进探索旅程。"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request

from pokeop.api.schemas.battle_exploration import (
    AdvanceBattleExplorationRequest,
    BacktrackBattleExplorationRequest,
    BattleGraphExplorationResponse,
    BattleTransitionGroupOutcomesResponse,
    ExploreBattleGraphRequest,
    ExplorationCursorRequest,
    StoredBattleInferenceJourneyResponse,
    battle_graph_exploration_response,
    battle_transition_group_outcomes_response,
    stored_battle_inference_journey_response,
)
from pokeop.api.schemas.inference import DragoniteWeavileJourneyRequest
from pokeop.application.battle_graph_store import (
    BattleGraphCapacityExceeded,
    BattleGraphExpired,
    BattleGraphIdentifierCollision,
    BattleGraphNotFound,
    BattleGraphStore,
    BattleGraphStoreError,
)
from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.configuration_space import ConfigurationSpaceError
from pokeop.application.solver.models import GraphEdgeId
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationCursorError,
)
from pokeop.application.use_cases.battle_exploration import (
    AdvanceBattleExplorationUseCase,
    BacktrackBattleExplorationUseCase,
    BattleExplorationUseCaseError,
    BattleNodeNotFoundError,
    BuildBattleReportUseCase,
    EdgeNotInCurrentNodeError,
    IncompatibleCalculationRevisionError,
    InvalidExplorationCursorError,
    ListTransitionGroupsUseCase,
    LoadBattleNodeUseCase,
    LoadTransitionGroupOutcomesUseCase,
    TerminalBattleNodeAdvanceError,
    TransitionGroupNotFoundError,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    BattleInferenceExecutionError,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.application.use_cases.load_battle_inference_profile import (
    BattleInferenceProfileNotFound,
)
from pokeop.application.use_cases.store_battle_graph import (
    FixedOneOnOneBattleExecutor,
    StoreBackedInferOneOnOneBattleUseCase,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)


router = APIRouter()

_DRAGONITE_ID = 149
_WEAVILE_ID = 461
_BRICK_BREAK_ID = 280
_ICE_PUNCH_ID = 8
_FAKE_OUT_ID = 252


def _use_case() -> InferOneOnOneBattleUseCase:
    """创建 HTTP 边界使用的完整推演 composition root。

    Returns:
        使用物化视图 repository、factory 覆盖对账、透明中性特性假设和精确图求解器的
        application 用例。
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


def _inference_executor() -> FixedOneOnOneBattleExecutor:
    """返回可被 FastAPI dependency override 替换的固定推演执行器。

    Returns:
        只暴露 ``execute_fixed`` 的 application 窄协议实现。
    """
    return _use_case()


def _graph_store(request: Request) -> BattleGraphStore:
    """从 FastAPI application state 读取进程生命周期共享 graph store。

    Args:
        request: 当前 HTTP 请求，用于访问创建应用时注册的共享依赖。

    Returns:
        同一 backend 进程内全部推演与探索请求共享的 graph store。

    Raises:
        HTTPException: 应用启动过程未注册合法 store 时返回 HTTP 503。
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


InferenceExecutorDependency = Annotated[
    FixedOneOnOneBattleExecutor,
    Depends(_inference_executor),
]
GraphStoreDependency = Annotated[BattleGraphStore, Depends(_graph_store)]


def _command(
    request: DragoniteWeavileJourneyRequest,
) -> InferFixedOneOnOneBattleCommand:
    """把受控页面输入转换为固定 1v1 推演命令。

    Args:
        request: 快龙特性、玛纽拉行动方案和双方能力预设。

    Returns:
        只允许快龙使用劈瓦、玛纽拉使用冰冻拳或击掌奇袭组合的固定命令。
    """
    pressure_plan = request.weavile_plan == "fake-out-pressure"
    return InferFixedOneOnOneBattleCommand(
        rules=BattleInferenceRules(),
        attacker=PokemonInferenceSelection(
            pokemon_id=_DRAGONITE_ID,
            move_ids=(_BRICK_BREAK_ID,),
            ability_identifier=request.dragonite_ability,
            stat_preset_key=request.dragonite_stat_preset,
        ),
        defender=PokemonInferenceSelection(
            pokemon_id=_WEAVILE_ID,
            move_ids=(
                (_ICE_PUNCH_ID, _FAKE_OUT_ID)
                if pressure_plan
                else (_ICE_PUNCH_ID,)
            ),
            ability_identifier="pressure",
            stat_preset_key=request.weavile_stat_preset,
        ),
        attacker_policy=BattleActionPolicyKind.FIRST_LEGAL,
        defender_policy=(
            BattleActionPolicyKind.UNIFORM_RANDOM
            if pressure_plan
            else BattleActionPolicyKind.FIRST_LEGAL
        ),
    )


def _application_cursor(
    graph_store: BattleGraphStore,
    graph_id: str,
    calculation_revision: str,
    cursor: ExplorationCursorRequest,
) -> ExplorationCursor:
    """使用服务端根节点重建 HTTP cursor。

    Args:
        graph_store: 应用生命周期共享的完整图存储端口。
        graph_id: URL 中指定的稳定图标识。
        calculation_revision: 调用方声明兼容的计算语义版本。
        cursor: 只包含真实 edge steps 的 HTTP 游标。

    Returns:
        绑定 store 中真实根节点的 application cursor；完整边合法性由 use case 校验。
    """
    root = LoadBattleNodeUseCase(graph_store).load_root(
        graph_id,
        calculation_revision,
    )
    return cursor.to_application(
        graph_id=graph_id,
        root_node_id=int(root.cursor.root_node_id),
    )


def _exploration_response(
    graph_store: BattleGraphStore,
    graph_id: str,
    calculation_revision: str,
    cursor: ExplorationCursor,
) -> BattleGraphExplorationResponse:
    """通过 application use cases 组合当前节点、折叠 groups 与结构化战报。

    Args:
        graph_store: 应用生命周期共享的完整图存储端口。
        graph_id: 当前探索图的稳定标识。
        calculation_revision: 当前请求支持的计算语义版本。
        cursor: 已绑定当前图根节点的真实 edge 序列。

    Returns:
        默认不展开 outcomes 的完整当前探索视图。
    """
    groups = ListTransitionGroupsUseCase(graph_store).execute(
        graph_id,
        calculation_revision,
        cursor,
    )
    report = BuildBattleReportUseCase(graph_store).execute(
        graph_id,
        calculation_revision,
        cursor,
    )
    return battle_graph_exploration_response(groups, report)


def _raise_exploration_http_error(error: Exception) -> NoReturn:
    """把 store 与 exploration application 异常映射为稳定 HTTP 语义。

    Args:
        error: router 调用 application use case 时捕获的稳定异常。

    Raises:
        HTTPException: 根据不存在、过期、冲突或服务容量问题返回对应状态码。
    """
    if isinstance(error, BattleGraphExpired):
        status_code, code = 410, "battle_graph_expired"
    elif isinstance(
        error,
        (BattleGraphNotFound, BattleNodeNotFoundError, TransitionGroupNotFoundError),
    ):
        status_code, code = 404, "battle_graph_resource_not_found"
    elif isinstance(
        error,
        (
            IncompatibleCalculationRevisionError,
            EdgeNotInCurrentNodeError,
            InvalidExplorationCursorError,
            TerminalBattleNodeAdvanceError,
            ExplorationCursorError,
            ValueError,
        ),
    ):
        status_code, code = 409, "battle_exploration_conflict"
    elif isinstance(
        error,
        (BattleGraphCapacityExceeded, BattleGraphIdentifierCollision, BattleGraphStoreError),
    ):
        status_code, code = 503, "battle_graph_store_error"
    else:
        status_code, code = 500, "battle_exploration_internal_error"
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(error)},
    ) from error


def _cursor_from_request(
    graph_store: BattleGraphStore,
    graph_id: str,
    request: ExploreBattleGraphRequest,
) -> ExplorationCursor:
    """从通用探索请求重建当前图的 application cursor。

    Args:
        graph_store: 应用生命周期共享的完整图存储端口。
        graph_id: URL 中指定的稳定图标识。
        request: 携带计算版本和 edge steps 的 HTTP 请求。

    Returns:
        绑定真实根节点的 application cursor。
    """
    return _application_cursor(
        graph_store,
        graph_id,
        request.calculation_revision,
        request.cursor,
    )


@router.post(
    "/dragonite-vs-weavile",
    response_model=StoredBattleInferenceJourneyResponse,
    summary="推演快龙 vs 玛纽拉并创建渐进探索图",
)
async def dragonite_vs_weavile(
    request: DragoniteWeavileJourneyRequest,
    inference_executor: InferenceExecutorDependency,
    graph_store: GraphStoreDependency,
) -> StoredBattleInferenceJourneyResponse:
    """执行固定旅程、保存完整图并返回 summary 与可跨请求探索的句柄。

    Args:
        request: 页面允许调整的受控场景参数。
        inference_executor: 构建和精确求解完整状态图的 application 执行器。
        graph_store: 应用生命周期共享的有界完整图存储端口。

    Returns:
        完整概率空间 summary，以及 graph ID、根 cursor 和过期时间。
    """
    try:
        stored = StoreBackedInferOneOnOneBattleUseCase(
            inference_use_case=inference_executor,
            graph_store=graph_store,
        ).execute_fixed_with_handle(_command(request))
    except BattleInferenceProfileNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (BattleInferenceExecutionError, ConfigurationSpaceError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except BattleGraphStoreError as error:
        _raise_exploration_http_error(error)
    return stored_battle_inference_journey_response(stored)


@router.post(
    "/graphs/{graph_id}/explore",
    response_model=BattleGraphExplorationResponse,
    summary="读取 cursor 当前节点和折叠分支组",
)
async def explore_battle_graph(
    graph_id: str,
    request: ExploreBattleGraphRequest,
    graph_store: GraphStoreDependency,
) -> BattleGraphExplorationResponse:
    """读取根节点或 cursor 当前节点，不提前展开任何 group outcomes。"""
    try:
        cursor = _cursor_from_request(graph_store, graph_id, request)
        return _exploration_response(
            graph_store,
            graph_id,
            request.calculation_revision,
            cursor,
        )
    except (BattleGraphStoreError, BattleExplorationUseCaseError, ExplorationCursorError, ValueError) as error:
        _raise_exploration_http_error(error)


@router.post(
    "/graphs/{graph_id}/groups/{group_id}/outcomes",
    response_model=BattleTransitionGroupOutcomesResponse,
    summary="按需展开一个当前节点分支组",
)
async def load_transition_group_outcomes(
    graph_id: str,
    group_id: str,
    request: ExploreBattleGraphRequest,
    graph_store: GraphStoreDependency,
) -> BattleTransitionGroupOutcomesResponse:
    """只加载指定 group 的 outcomes，不重复返回其他 groups 或完整图。"""
    try:
        cursor = _cursor_from_request(graph_store, graph_id, request)
        result = LoadTransitionGroupOutcomesUseCase(graph_store).execute(
            graph_id,
            request.calculation_revision,
            cursor,
            group_id,
        )
        return battle_transition_group_outcomes_response(result)
    except (BattleGraphStoreError, BattleExplorationUseCaseError, ExplorationCursorError, ValueError) as error:
        _raise_exploration_http_error(error)


@router.post(
    "/graphs/{graph_id}/advance",
    response_model=BattleGraphExplorationResponse,
    summary="沿当前节点的一条正式边前进",
)
async def advance_battle_exploration(
    graph_id: str,
    request: AdvanceBattleExplorationRequest,
    graph_store: GraphStoreDependency,
) -> BattleGraphExplorationResponse:
    """通过 application 校验 edge 后返回前进一步的完整探索视图。"""
    try:
        cursor = _cursor_from_request(graph_store, graph_id, request)
        position = AdvanceBattleExplorationUseCase(graph_store).execute(
            graph_id,
            request.calculation_revision,
            cursor,
            GraphEdgeId(request.edge_id),
        )
        return _exploration_response(
            graph_store,
            graph_id,
            request.calculation_revision,
            position.cursor,
        )
    except (BattleGraphStoreError, BattleExplorationUseCaseError, ExplorationCursorError, ValueError) as error:
        _raise_exploration_http_error(error)


@router.post(
    "/graphs/{graph_id}/backtrack",
    response_model=BattleGraphExplorationResponse,
    summary="返回上一级或指定祖先深度",
)
async def backtrack_battle_exploration(
    graph_id: str,
    request: BacktrackBattleExplorationRequest,
    graph_store: GraphStoreDependency,
) -> BattleGraphExplorationResponse:
    """截断真实 edge prefix，并返回祖先节点同步后的完整探索视图。"""
    try:
        cursor = _cursor_from_request(graph_store, graph_id, request)
        use_case = BacktrackBattleExplorationUseCase(graph_store)
        position = (
            use_case.back(graph_id, request.calculation_revision, cursor)
            if request.depth is None
            else use_case.truncate(
                graph_id,
                request.calculation_revision,
                cursor,
                request.depth,
            )
        )
        return _exploration_response(
            graph_store,
            graph_id,
            request.calculation_revision,
            position.cursor,
        )
    except (BattleGraphStoreError, BattleExplorationUseCaseError, ExplorationCursorError, ValueError) as error:
        _raise_exploration_http_error(error)


__all__ = ["router"]
