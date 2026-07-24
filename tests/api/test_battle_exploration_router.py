"""验证战斗状态图 HTTP API 共享 lifespan store 并保持真实 cursor 语义。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException

from pokeop.api.routers import inference
from pokeop.api.schemas.battle_exploration import (
    AdvanceBattleExplorationRequest,
    BacktrackBattleExplorationRequest,
    BattleGraphExplorationResponse,
    ExploreBattleGraphRequest,
    ExplorationCursorRequest,
    StoredBattleInferenceJourneyResponse,
)
from pokeop.api.schemas.inference import DragoniteWeavileJourneyRequest
from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.application.use_cases.infer_one_on_one_battle import (
    FixedOneOnOneBattleResult,
)
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from pokeop import main as main_module
from tests.api.test_inference_schema import _result as inference_schema_result
from tests.application.use_cases.battle_exploration_test_helpers import (
    REVISION,
    Executor,
    build_graph,
)


@dataclass(slots=True)
class MutableClock:
    """提供 TTL API 测试可显式推进的 timezone-aware 时钟。"""

    current: datetime

    def __call__(self) -> datetime:
        """返回当前测试时间。"""
        return self.current

    def advance(self, delta: timedelta) -> None:
        """按给定时长推进当前测试时间。

        Args:
            delta: 需要增加的正向时间跨度。
        """
        self.current += delta


def _skip_postgres_runtime() -> None:
    """在纯 API 合同测试中跳过真实 PostgreSQL runtime 注册。"""


def _fixed_result() -> FixedOneOnOneBattleResult:
    """创建 summary 与标准分叉/合流/循环图组合的固定推演结果。

    Returns:
        exploration 使用测试 revision 并持有可被 store 保存的完整状态图。
    """
    base = inference_schema_result()
    return replace(
        base,
        exploration=replace(
            base.exploration,
            calculation_revision=REVISION,
            graph_artifact=build_graph(),
            graph_handle=None,
        ),
    )


def _journey_request() -> DragoniteWeavileJourneyRequest:
    """返回不依赖真实数据库的合法受控推演请求。"""
    return DragoniteWeavileJourneyRequest(
        dragonite_ability="multiscale",
        weavile_plan="ice-punch",
        dragonite_stat_preset="max_atk_plus",
        weavile_stat_preset="max_atk_plus",
    )


def _test_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    clock: MutableClock | None = None,
    ttl: timedelta = timedelta(minutes=5),
) -> FastAPI:
    """创建使用可观察进程内 store 且不连接数据库的 FastAPI 应用。

    Args:
        monkeypatch: pytest 注入的模块替换工具。
        clock: 可选 fake clock；省略时使用 store 默认 UTC 时钟。
        ttl: 每份完整图允许跨请求读取的生命周期。

    Returns:
        lifespan 启动后会在 ``app.state`` 注册唯一共享 store 的应用。
    """
    monkeypatch.setattr(main_module, "register_postgres_runtime", _skip_postgres_runtime)

    def graph_store_factory() -> BattleGraphStore:
        """为当前应用 lifespan 创建唯一有界图存储实例。"""
        if clock is None:
            return InMemoryBattleGraphStore(ttl=ttl)
        return InMemoryBattleGraphStore(ttl=ttl, clock=clock)

    return main_module.create_app(graph_store_factory=graph_store_factory)


def _cursor_request(response: BattleGraphExplorationResponse) -> ExplorationCursorRequest:
    """把上一次响应 cursor 转回下一次请求 DTO。

    Args:
        response: 前一步 explore、advance 或 backtrack 的完整响应。

    Returns:
        只包含有序 edge steps 的请求游标。
    """
    return ExplorationCursorRequest.model_validate(response.cursor.model_dump())


async def _start_journey(
    store: BattleGraphStore,
) -> StoredBattleInferenceJourneyResponse:
    """通过 router 初始入口保存标准测试图并返回 graph handle。

    Args:
        store: 当前应用 lifespan 共享的 graph store。

    Returns:
        包含空 cursor、过期时间和固定 summary 的首次响应。
    """
    return await inference.dragonite_vs_weavile(
        _journey_request(),
        Executor(_fixed_result()),
        store,
    )


async def _advance(
    store: BattleGraphStore,
    graph_id: str,
    response: BattleGraphExplorationResponse,
    edge_id: int,
) -> BattleGraphExplorationResponse:
    """沿上一次响应 cursor 的指定正式边前进。

    Args:
        store: 当前应用 lifespan 共享的 graph store。
        graph_id: 首次推演返回的稳定图标识。
        response: 决定当前 source node 的上一步探索响应。
        edge_id: 必须从当前节点出发的正式边 ID。

    Returns:
        目标节点、更新 cursor、折叠 groups 和同步战报。
    """
    return await inference.advance_battle_exploration(
        graph_id,
        AdvanceBattleExplorationRequest(
            calculation_revision=REVISION,
            cursor=_cursor_request(response),
            edge_id=edge_id,
        ),
        store,
    )


def test_progressive_api_routes_are_registered() -> None:
    """验证动态路由扫描器注册 Issue #64 的全部 POST 路径。"""
    application = main_module.create_app()
    expected_paths = {
        "/v1/inference/dragonite-vs-weavile",
        "/v1/inference/graphs/{graph_id}/explore",
        "/v1/inference/graphs/{graph_id}/groups/{group_id}/outcomes",
        "/v1/inference/graphs/{graph_id}/advance",
        "/v1/inference/graphs/{graph_id}/backtrack",
    }
    routes = {
        route.path: route
        for route in application.routes
        if route.path in expected_paths
    }

    assert set(routes) == expected_paths
    assert all("POST" in route.methods for route in routes.values())


def test_initial_explore_expand_advance_and_backtrack_share_lifespan_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证首次推演到回退的完整 API 序列使用同一 graph artifact。

    根 explore 必须只返回折叠 group；单 group outcomes 接口只展开目标组；advance
    追加真实 edge step 并精确返回 1/3；backtrack 截断到根后同步清空战报步骤。
    """
    application = _test_app(monkeypatch)

    async def scenario() -> None:
        """在同一应用 lifespan 内执行完整渐进探索序列。"""
        async with application.router.lifespan_context(application):
            store = application.state.battle_graph_store
            initial = await _start_journey(store)
            graph_id = initial.exploration.graph_id

            assert initial.exploration.root_node_id == 0
            assert initial.exploration.calculation_revision == REVISION
            assert initial.exploration.cursor.steps == []
            assert initial.exploration.expires_at.tzinfo is not None

            root = await inference.explore_battle_graph(
                graph_id,
                ExploreBattleGraphRequest(calculation_revision=REVISION),
                store,
            )
            assert root.node.node_id == 0
            assert root.cumulative_probability.numerator == "1"
            assert root.cumulative_probability.denominator == "1"
            assert root.battle_report.steps == []
            assert len(root.transition_groups) == 1
            assert root.transition_groups[0].expanded is False
            assert root.transition_groups[0].outcomes == []

            group_id = root.transition_groups[0].group_id
            outcomes = await inference.load_transition_group_outcomes(
                graph_id,
                group_id,
                ExploreBattleGraphRequest(calculation_revision=REVISION),
                store,
            )
            assert outcomes.transition_group.group_id == group_id
            assert outcomes.transition_group.expanded is True
            assert [item.edge_id for item in outcomes.transition_group.outcomes] == [0, 1]

            advanced = await _advance(store, graph_id, root, edge_id=0)
            assert advanced.node.node_id == 1
            assert advanced.cursor.steps[0].edge_id == 0
            assert advanced.cumulative_probability.numerator == "1"
            assert advanced.cumulative_probability.denominator == "3"
            assert advanced.battle_report.depth == 1

            backtracked = await inference.backtrack_battle_exploration(
                graph_id,
                BacktrackBattleExplorationRequest(
                    calculation_revision=REVISION,
                    cursor=_cursor_request(advanced),
                ),
                store,
            )
            assert backtracked.node.node_id == 0
            assert backtracked.cursor.steps == []
            assert backtracked.battle_report.steps == []

    asyncio.run(scenario())


def test_cycle_back_edge_and_terminal_node_preserve_real_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证循环回根和终局路径都按真实 edge sequence 工作。

    路径先执行 ``0 -> 1 -> 3 -> 0`` 循环回边，再从重复 root 经另一分支到终局。
    cursor 必须保留六条真实边而不是按 node ID 去重；终局 explore 返回 200、空 groups，
    继续 advance 才返回稳定 409 冲突。
    """
    application = _test_app(monkeypatch)

    async def scenario() -> None:
        """在同一 cursor 中依次验证 cycle 与 terminal 语义。"""
        async with application.router.lifespan_context(application):
            store = application.state.battle_graph_store
            initial = await _start_journey(store)
            graph_id = initial.exploration.graph_id
            position = await inference.explore_battle_graph(
                graph_id,
                ExploreBattleGraphRequest(calculation_revision=REVISION),
                store,
            )

            for edge_id in (0, 2, 4):
                position = await _advance(store, graph_id, position, edge_id)
            assert position.node.node_id == 0
            assert [step.edge_id for step in position.cursor.steps] == [0, 2, 4]
            assert position.battle_report.depth == 3

            for edge_id in (1, 3, 5):
                position = await _advance(store, graph_id, position, edge_id)
            assert position.node.node_id == 4
            assert position.terminal is True
            assert position.transition_groups == []
            assert [step.edge_id for step in position.cursor.steps] == [0, 2, 4, 1, 3, 5]
            assert position.battle_report.depth == 6

            with pytest.raises(HTTPException) as exc_info:
                await _advance(store, graph_id, position, edge_id=0)
            assert exc_info.value.status_code == 409
            assert exc_info.value.detail["code"] == "battle_exploration_conflict"

    asyncio.run(scenario())


def test_expired_graph_returns_http_410(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证首次读取到期图时释放 artifact 并返回稳定 HTTP 410。"""
    clock = MutableClock(datetime(2026, 7, 24, tzinfo=timezone.utc))
    application = _test_app(
        monkeypatch,
        clock=clock,
        ttl=timedelta(seconds=1),
    )

    async def scenario() -> None:
        """保存图、推进 fake clock，并触发过期读取。"""
        async with application.router.lifespan_context(application):
            store = application.state.battle_graph_store
            initial = await _start_journey(store)
            clock.advance(timedelta(seconds=2))

            with pytest.raises(HTTPException) as exc_info:
                await inference.explore_battle_graph(
                    initial.exploration.graph_id,
                    ExploreBattleGraphRequest(calculation_revision=REVISION),
                    store,
                )
            assert exc_info.value.status_code == 410
            assert exc_info.value.detail["code"] == "battle_graph_expired"

    asyncio.run(scenario())
