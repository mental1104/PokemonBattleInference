"""真实公开图创建后的胜利路径查询差分；只固定随机graph句柄，不替换图/搜索/概率。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from pokeop.api.routers.winning_paths import router
from pokeop.api.schemas.fixed_battle import FixedBattleSummaryRequest
from pokeop.api.schemas.winning_paths import (
    ListWinningPathGroupsRequest,
    WinningPathGroupsResponse,
)
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from tests.migration.test_go_fixed_inference import (
    _FixedClients,
    _Requests,
)

# 复用已有真实PG/HTTP fixture的pytest注册，不新增应用运行时插件或计算替代。
pytest_plugins = ["tests.migration.test_go_fixed_inference"]


@dataclass(frozen=True)
class _WinningClients:
    """共享同PG实际原HTTP与Go客户端；store只注入Go已经生成的随机句柄使cursor可原样比较。"""
    clients: _FixedClients
    store: InMemoryBattleGraphStore

    def create(self, request: FixedBattleSummaryRequest, label: str) -> str:
        """两端各实际构图；只统一随机graph ID，完整数学/状态/选择仍由各端原实现执行。"""
        path = "/v1/inference/fixed-one-on-one/graph"
        actual = self.clients.remote.post(path, json=request.model_dump(mode="json"))
        self.clients.report.joinpath(label + ".create.go.json").write_bytes(actual.content)
        assert actual.status_code == 200, actual.text
        graph_id = str(actual.json()["exploration"]["graph_id"])
        # 句柄由测试控制，原store的容量/锁/TTL/完整图写入路径仍真实执行。
        self.store.graph_id_factory = lambda: graph_id
        expected = self.clients.original.post(path, json=request.model_dump(mode="json"))
        self.clients.report.joinpath(label + ".create.python.json").write_bytes(expected.content)
        assert expected.status_code == 200, expected.text
        assert expected.json()["exploration"]["graph_id"] == graph_id
        assert actual.json()["summary"] == expected.json()["summary"]
        return graph_id

    def compare(self, graph_id: str, request: ListWinningPathGroupsRequest, label: str, status: int = 200) -> httpx.Response:
        """保留完整原请求/双方响应；包括不透明cursor和所有整数/概率，无归一或近似容差。"""
        path = f"/v1/winning_paths/graphs/{graph_id}"
        body = request.model_dump(mode="json")
        started = perf_counter()
        expected = self.clients.original.post(path, json=body)
        original_seconds = perf_counter() - started
        started = perf_counter()
        actual = self.clients.remote.post(path, json=body)
        actual_seconds = perf_counter() - started
        self.clients.report.joinpath(label + ".request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        self.clients.report.joinpath(label + ".go.json").write_bytes(actual.content)
        self.clients.report.joinpath(label + ".python.json").write_bytes(expected.content)
        self.clients.report.joinpath(label + ".timing.json").write_text(json.dumps({"python_seconds": original_seconds, "go_seconds": actual_seconds, "python_bytes": len(expected.content), "go_bytes": len(actual.content)}))
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        if status == 200:
            WinningPathGroupsResponse.model_validate_json(actual.content)
        assert actual.json() == expected.json()
        return actual


@pytest.fixture
def winning_clients(fixed_clients: _FixedClients) -> _WinningClients:
    """原FastAPI额外挂真实winning路由与进程store；repository仍为同一独占PG，无计算替代。"""
    app = cast(FastAPI, fixed_clients.original.app)
    store = InMemoryBattleGraphStore()
    app.state.battle_graph_store = store
    app.include_router(router, prefix="/v1/winning_paths")
    return _WinningClients(fixed_clients, store)


class TestGoWinningPaths:
    """真实图→DFS/精确求解/行动归并/前缀与cursor的完整公开响应，而非Core JSON demo。"""

    def test_original_baseline_both_winners(self, winning_clients: _WinningClients) -> None:
        """使用原841节点/16095边图，检查空获胜侧与实际获胜侧，不以tiny图回避输入预算。"""
        graph_id = winning_clients.create(_Requests.fixed(), "winning-baseline")
        for winner in ("attacker", "defender"):
            winning_clients.compare(graph_id, ListWinningPathGroupsRequest(calculation_revision="battle-inference.summary-exploration.v2", winner=winner), "winning-baseline-" + winner)

    def test_uniform_pagination_and_cursor_binding(self, winning_clients: _WinningClients) -> None:
        """真实双行动图第一页/下一页完整cursor一致，跨winner重用和损坏cursor返回原409。"""
        request = _Requests.fixed(52, "technician", (252, 10))
        request.attacker_policy = "uniform-random"
        graph_id = winning_clients.create(request, "winning-uniform")
        query = ListWinningPathGroupsRequest(calculation_revision="battle-inference.summary-exploration.v2", winner="defender", limit=1)
        first = winning_clients.compare(graph_id, query, "winning-page-1").json()
        assert first["has_more"] and first["next_cursor"] is not None, first
        query.cursor = first["next_cursor"]
        winning_clients.compare(graph_id, query, "winning-page-2")
        query.winner = "attacker"
        winning_clients.compare(graph_id, query, "winning-cross-winner", 409)
        query.cursor = "broken"
        winning_clients.compare(graph_id, query, "winning-broken-cursor", 409)

    def test_original_query_errors(self, winning_clients: _WinningClients) -> None:
        """原不存在图、错误sort及标识错误的优先级保持完整envelope，不需要替代图数据。"""
        query = ListWinningPathGroupsRequest(calculation_revision="battle-inference.summary-exploration.v2", winner="attacker")
        winning_clients.compare("missing-graph", query, "winning-missing", 404)
        query.sort = "unknown-sort"
        winning_clients.compare("missing-graph", query, "winning-sort-first", 409)
        query.calculation_revision = " old "
        winning_clients.compare("missing-graph", query, "winning-sort-before-revision", 409)
        query.sort = "shortest-high-probability"
        winning_clients.compare("missing-graph", query, "winning-revision-normalization", 409)
