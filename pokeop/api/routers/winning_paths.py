"""暴露按固定配置查询胜利路径 Top-K 与行动前缀树的 HTTP 入口。"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request

from pokeop.api.schemas.winning_paths import (
    ListWinningPathGroupsRequest,
    WinningPathGroupsResponse,
    winning_path_groups_response,
)
from pokeop.application.battle_graph_store import (
    BattleGraphExpired,
    BattleGraphNotFound,
    BattleGraphStore,
    BattleGraphStoreError,
)
from pokeop.application.use_cases.battle_exploration import (
    IncompatibleCalculationRevisionError,
)
from pokeop.application.use_cases.winning_paths import (
    ListWinningPathGroupsUseCase,
    WinningPathQueryError,
    WinningPathSort,
    WinningPathWinner,
)


router = APIRouter()


def _graph_store(request: Request) -> BattleGraphStore:
    """从 FastAPI application state 读取进程生命周期共享 graph store。

    Args:
        request: 当前 HTTP 请求，用于访问应用启动时注册的共享依赖。

    Returns:
        同一 backend 进程内推演、探索和胜利路径查询共享的 graph store。

    Raises:
        HTTPException: 应用未注册合法 graph store 时返回 HTTP 503。
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


def _raise_winning_path_http_error(error: Exception) -> NoReturn:
    """把 store、版本和查询游标异常映射为稳定 HTTP 语义。

    Args:
        error: router 调用 application use case 时捕获的稳定异常。

    Raises:
        HTTPException: 根据过期、不存在、查询冲突或存储错误返回对应状态码。
    """
    if isinstance(error, BattleGraphExpired):
        status_code, code = 410, "battle_graph_expired"
    elif isinstance(error, BattleGraphNotFound):
        status_code, code = 404, "battle_graph_not_found"
    elif isinstance(
        error,
        (IncompatibleCalculationRevisionError, WinningPathQueryError, ValueError),
    ):
        status_code, code = 409, "winning_path_query_conflict"
    elif isinstance(error, BattleGraphStoreError):
        status_code, code = 503, "battle_graph_store_error"
    else:
        status_code, code = 500, "winning_path_query_internal_error"
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(error)},
    ) from error


@router.post(
    "/graphs/{graph_id}",
    response_model=WinningPathGroupsResponse,
    summary="查询固定配置的胜利路径 Top-K 与行动前缀树",
)
async def list_winning_path_groups(
    graph_id: str,
    request: ListWinningPathGroupsRequest,
    graph_store: GraphStoreDependency,
) -> WinningPathGroupsResponse:
    """查询一个胜者的分页行动路径组，不枚举循环产生的无限 walk。

    Args:
        graph_id: 首次推演写入 graph store 后返回的稳定图标识。
        request: 计算版本、胜者、页大小、不透明游标和排序策略。
        graph_store: 应用生命周期共享的完整图存储端口。

    Returns:
        当前页路径组、行动前缀树、精确概率覆盖和循环引用。
    """
    try:
        result = ListWinningPathGroupsUseCase(graph_store).execute(
            graph_id,
            request.calculation_revision,
            winner=WinningPathWinner(request.winner),
            limit=request.limit,
            cursor=request.cursor,
            sort=WinningPathSort(request.sort),
        )
    except (
        BattleGraphStoreError,
        IncompatibleCalculationRevisionError,
        WinningPathQueryError,
        ValueError,
    ) as error:
        _raise_winning_path_http_error(error)
    return winning_path_groups_response(result)


__all__ = ["router"]
