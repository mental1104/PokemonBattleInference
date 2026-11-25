"""同一真实PG下原固定图/渐进导航与Go→隔离Core的公开HTTP完整字段对照。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import httpx
import pytest
from fastapi import FastAPI

from pokeop.api.routers import inference
from pokeop.api.schemas.battle_exploration import (
    BattleGraphExplorationResponse,
    BattleTransitionGroupOutcomesResponse,
    ExploreBattleGraphRequest,
    ExplorationCursorRequest,
    ExplorationPathStepRequest,
    StoredBattleInferenceJourneyResponse,
)
from pokeop.api.schemas.fixed_battle import FixedBattleSummaryRequest
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from tests.migration.test_go_fixed_inference import _FixedClients, _Requests, fixed_clients
from tests.migration.test_core_actions_abi import ActionStrategy
from tests.migration.test_core_turn import Mode, _TurnCase
from tests.migration.test_core_turn_abi import _ABIOracle
from pokeop.application.solver.models import StateGraphLimits


@dataclass(frozen=True)
class _GraphPair:
    """两实际服务器独立随机句柄，其他计算身份/节点/边必须完全相同。"""

    actual: str
    expected: str
    revision: str


@dataclass(frozen=True)
class _GraphClients:
    """复用真实独立HTTP客户端与同PG原路由，仅归一服务端随机graph句柄。"""

    clients: _FixedClients

    def record(self, label: str, body: str, expected: httpx.Response, actual: httpx.Response) -> None:
        """保存原请求/双方响应和状态；所有差异先留证，不只记录断言摘要。"""
        self.clients.report.joinpath(label + ".request.json").write_text(body)
        self.clients.report.joinpath(label + ".python.json").write_bytes(expected.content)
        self.clients.report.joinpath(label + ".go.json").write_bytes(actual.content)
        self.clients.report.joinpath(label + ".status.json").write_text(json.dumps({"python": expected.status_code, "go": actual.status_code}))

    def capture_native_diagnosis(self, expected: httpx.Response, request: FixedBattleSummaryRequest, label: str) -> None:
        """只把原实际PG图的根状态导出正式Core请求，供失败后诊断输出预算；不生成HTTP预期。

        原HTTP断言仍只比较两个独立公开响应，此补充记录不替换SQL、工厂、solver或事件。
        """
        if expected.status_code != 200:
            return
        response = StoredBattleInferenceJourneyResponse.model_validate_json(expected.content)
        app = cast(FastAPI, self.clients.original.app)
        graph = app.state.battle_graph_store.get(response.exploration.graph_id).graph
        policy = {"first-legal": ActionStrategy.first, "uniform-random": ActionStrategy.uniform}
        case = _TurnCase(graph.node(graph.root_node_id).state, Mode.FIXED,
            attacker_policy=policy[request.attacker_policy], defender_policy=policy[request.defender_policy],
            graph_limits=StateGraphLimits(max_nodes=request.limits.max_nodes, max_edges=request.limits.max_edges, max_turns=request.limits.max_turns))
        self.clients.report.joinpath(label + ".native.request.json").write_text(_ABIOracle.request(case).model_dump_json(indent=2))

    def create(self, request: FixedBattleSummaryRequest, label: str) -> _GraphPair:
        """实际原工厂/BFS/solver/store与实际Go/Core各执行一次，除了随机句柄/时间外完整JSON一致。"""
        path = "/v1/inference/fixed-one-on-one/graph"
        body = request.model_dump(mode="json")
        before = datetime.now(timezone.utc)
        expected = self.clients.original.post(path, json=body)
        actual = self.clients.remote.post(path, json=body)
        self.record(label, request.model_dump_json(indent=2), expected, actual)
        self.capture_native_diagnosis(expected, request, label)
        assert actual.status_code == expected.status_code == 200, (actual.text, expected.text)
        reference = StoredBattleInferenceJourneyResponse.model_validate_json(expected.content)
        result = StoredBattleInferenceJourneyResponse.model_validate_json(actual.content)
        for handle in (reference.exploration, result.exploration):
            assert re.fullmatch(r"[0-9a-f]{32}", handle.graph_id)
            assert before + timedelta(minutes=14) < handle.expires_at < datetime.now(timezone.utc) + timedelta(minutes=16)
        left, right = actual.json(), expected.json()
        for value in (left, right):
            value["exploration"]["graph_id"] = "<opaque-graph>"
            value["exploration"]["expires_at"] = "<validated-expiry>"
        assert left == right
        assert result.exploration.calculation_revision == reference.exploration.calculation_revision
        return _GraphPair(result.exploration.graph_id, reference.exploration.graph_id, result.exploration.calculation_revision)

    def query(self, pair: _GraphPair, suffix: str, request: ExploreBattleGraphRequest, label: str,
              status: int = 200, **extra: int) -> httpx.Response:
        """对两随机句柄执行同一公开操作；不归一groupID、节点、边、概率、事件或错误语义。"""
        body = request.model_dump(mode="json") | extra
        expected = self.clients.original.post(f"/v1/inference/graphs/{pair.expected}/{suffix}", json=body)
        actual = self.clients.remote.post(f"/v1/inference/graphs/{pair.actual}/{suffix}", json=body)
        self.record(label, json.dumps(body, ensure_ascii=False, indent=2), expected, actual)
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        # 唯一允许变化的是独立store分配的UUID；错误里的同一UUID也只替换为相同占位。
        left = json.loads(actual.text.replace(pair.actual, "<opaque-graph>"))
        right = json.loads(expected.text.replace(pair.expected, "<opaque-graph>"))
        assert left == right
        if status == 200:
            if suffix.startswith("groups/"):
                BattleTransitionGroupOutcomesResponse.model_validate_json(actual.content)
            else:
                BattleGraphExplorationResponse.model_validate_json(actual.content)
        return actual


@pytest.fixture
def graph_clients(fixed_clients: _FixedClients) -> _GraphClients:
    """原FastAPI挂接真实进程内store和原导航router；PG/规则/随机/求解都不替换。"""
    app = cast(FastAPI, fixed_clients.original.app)
    app.state.battle_graph_store = InMemoryBattleGraphStore()
    app.include_router(inference.router, prefix="/v1/inference")
    return _GraphClients(fixed_clients)


class TestGoFixedGraph:
    """全图创建、按需group、实际路径前进/回退和原冲突边界，不以路由存在作为通过。"""

    @pytest.mark.parametrize("scenario", ("baseline", "fake-out", "uniform"))
    def test_actual_graph_creation(self, graph_clients: _GraphClients, scenario: str) -> None:
        """保留841节点/16095边的真实baseline，不只用小图掩盖输出或图浏览预算差异。"""
        request = _Requests.fixed()
        if scenario == "fake-out":
            request = _Requests.fixed(52, "technician", (252,))
        elif scenario == "uniform":
            request = _Requests.fixed(52, "technician", (252, 10))
            request.attacker_policy = "uniform-random"
        pair = graph_clients.create(request, "graph-create-" + scenario)
        if scenario == "baseline":
            position = ExploreBattleGraphRequest(calculation_revision=pair.revision)
            root = graph_clients.query(pair, "explore", position, "baseline-explore")
            group = BattleGraphExplorationResponse.model_validate_json(root.content).transition_groups[0]
            expanded = graph_clients.query(pair, f"groups/{group.group_id}/outcomes", position, "baseline-outcomes")
            outcome = BattleTransitionGroupOutcomesResponse.model_validate_json(expanded.content).transition_group.outcomes[0]
            advanced = graph_clients.query(pair, "advance", position, "baseline-advance", edge_id=outcome.edge_id)
            cursor = BattleGraphExplorationResponse.model_validate_json(advanced.content).cursor
            graph_clients.query(pair, "backtrack", ExploreBattleGraphRequest(calculation_revision=pair.revision,
                cursor=ExplorationCursorRequest.model_validate(cursor.model_dump())), "baseline-backtrack")

    def test_original_graph_navigation_and_full_report(self, graph_clients: _GraphClients) -> None:
        """真实非均匀两组选招图：逐字段检查折叠/展开、正式边战报、回退和终局优先错误。"""
        request = _Requests.fixed(52, "technician", (252, 10))
        request.attacker_policy = "uniform-random"
        pair = graph_clients.create(request, "navigate-create")
        position = ExploreBattleGraphRequest(calculation_revision=pair.revision)
        root = graph_clients.query(pair, "explore", position, "navigate-root")
        assert len(root.json()["transition_groups"]) == 2
        current = root
        for depth in range(8):
            node = BattleGraphExplorationResponse.model_validate_json(current.content)
            if node.terminal:
                graph_clients.query(pair, "advance", position, "navigate-terminal-reject", 409, edge_id=0)
                break
            group = node.transition_groups[0]
            expanded = graph_clients.query(pair, f"groups/{group.group_id}/outcomes", position, f"navigate-outcomes-{depth}")
            outcome = BattleTransitionGroupOutcomesResponse.model_validate_json(expanded.content).transition_group.outcomes[0]
            current = graph_clients.query(pair, "advance", position, f"navigate-advance-{depth}", edge_id=outcome.edge_id)
            actual = BattleGraphExplorationResponse.model_validate_json(current.content)
            position = ExploreBattleGraphRequest(calculation_revision=pair.revision,
                cursor=ExplorationCursorRequest.model_validate(actual.cursor.model_dump()))
            assert actual.battle_report.depth == depth + 1
            assert len(actual.battle_report.steps) == depth + 1
        else:
            pytest.fail("the selected actual fixture did not terminate within its known two-turn graph")
        graph_clients.query(pair, "backtrack", position, "navigate-back-one")
        graph_clients.query(pair, "backtrack", position, "navigate-back-root", depth=0)
        graph_clients.query(pair, "backtrack", ExploreBattleGraphRequest(calculation_revision=pair.revision), "navigate-root-back-reject", 409)
        graph_clients.query(pair, "backtrack", position, "navigate-invalid-depth", 409, depth=999)

    def test_original_navigation_resource_and_cursor_rejections(self, graph_clients: _GraphClients) -> None:
        """原revision、group、正式边和cursor目标冲突全部完整envelope对照，不伪装空图成功。"""
        pair = graph_clients.create(_Requests.fixed(52, "technician", (252,)), "reject-graph-create")
        position = ExploreBattleGraphRequest(calculation_revision=pair.revision)
        graph_clients.query(pair, "explore", ExploreBattleGraphRequest(calculation_revision="future-revision"), "graph-revision-mismatch", 409)
        graph_clients.query(pair, "groups/missing-group/outcomes", position, "graph-group-missing", 404)
        graph_clients.query(pair, "advance", position, "graph-edge-missing", 409, edge_id=999999)
        graph_clients.query(_GraphPair("missing-graph", "missing-graph", pair.revision), "explore", position, "graph-missing", 404)
        invalid = position.model_copy(deep=True)
        invalid.cursor.steps = [ExplorationPathStepRequest(source_node_id=0, edge_id=999999, target_node_id=1)]
        graph_clients.query(pair, "explore", invalid, "graph-invalid-cursor-edge", 409)
