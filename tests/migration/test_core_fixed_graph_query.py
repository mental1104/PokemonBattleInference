"""真实原回合构图/公开导航对照冻结事实重算入口；不传完整图、不复刻分组和概率。"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from pokeop.api.routers import inference
from pokeop.api.schemas.battle_exploration import BattleGraphExplorationResponse, BattleTransitionGroupOutcomesResponse, ExplorationCursorRequest
from pokeop.application.battle_graph_store import BattleGraphArtifact
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from tests.migration.test_core_state import _reference
from tests.migration.test_core_turn import Mode, _TurnCase, _TurnOracle
from tests.migration.test_core_turn_abi import FixedOperation, _ABIOracle

_REVISION = "battle-inference.summary-exploration.v2"


class _Contract(BaseModel):
    """进程边界冻结模型；未知字段失败，不把输出缺失当空成功。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Versions(_Contract):
    """同一个实际C ABI envelope的两轴版本，不在测试重复版本常量。"""
    engine_version: str
    rules_version: str


class _Query(_Contract):
    """原导航请求只增加明确模式/外部句柄，不预计算任何业务字段。"""
    mode: Literal["explore", "outcomes", "advance", "backtrack"]
    graph_id: str
    calculation_revision: str = _REVISION
    cursor: ExplorationCursorRequest = ExplorationCursorRequest()
    group_id: str | None = None
    edge_id: int | None = None
    depth: int | None = None


class _Operation(_Contract):
    """同一完整状态/知识/策略/预算冻结输入；计数来自真实原构图。"""
    kind: Literal["fixed_graph_query"] = "fixed_graph_query"
    fixed_request: FixedOperation
    expected_engine_version: str
    expected_rules_version: str
    expected_nodes: int
    expected_edges: int
    query: _Query


class _Failure(_Contract):
    """Core显式业务拒绝，由HTTP层机械编码原envelope。"""
    http_status: int
    code: str
    message: str


class _Reply(_Contract):
    """互斥完整结果；整数仅由原公开模型解析，概率不做容差转换。"""
    kind: Literal["fixed_graph_query"]
    mode: Literal["explore", "outcomes", "advance", "backtrack"]
    value: BattleGraphExplorationResponse | BattleTransitionGroupOutcomesResponse | None = None
    error: _Failure | None = None


@dataclass(frozen=True)
class _Core:
    """真实独立可执行查询入口；所有输入输出通过原边界模型。"""
    runner: Path
    versions: _Versions

    def query(self, operation: _Operation) -> _Reply:
        """operation是完整冻结事实；返回完整Core结果，非零/超时/缺行均失败。"""
        payload = operation.model_dump(mode="json")
        payload["query"] = operation.query.model_dump(mode="json", exclude_none=True)
        result = subprocess.run([str(self.runner)], input=json.dumps(payload)+"\n", text=True, capture_output=True, check=True, timeout=45)
        return _Reply.model_validate_json(result.stdout)


@pytest.fixture
def fixed_query_core() -> _Core:
    """缺显式入口单列SKIP；版本必须从真实同库envelope读取。"""
    raw = os.environ.get("PBI_FIXED_GRAPH_QUERY_RUNNER")
    if raw is None:
        pytest.skip("PBI_FIXED_GRAPH_QUERY_RUNNER is required")
    runner = Path(raw)
    assert runner.is_file()
    result = subprocess.run([str(runner)], input='{"kind":"versions"}\n', text=True, capture_output=True, check=True, timeout=5)
    return _Core(runner, _Versions.model_validate_json(result.stdout))


class TestFixedGraphQuery:
    """真实结构化回合/原BFS/原HTTP与Core按需重建的完整页面及错误对照。"""

    @pytest.mark.parametrize("budget", ("complete", "one-node", "one-turn"))
    def test_original_navigation(self, fixed_query_core: _Core, budget: str) -> None:
        """三种完整/截断图逐页比较，包含正式边事件战报/累计概率和祖先回退。"""
        state = _reference()
        for side in BattleSide:
            state = state.with_battler(side, replace(state.battler(side), current_hp=1))
        limits = StateGraphLimits(max_nodes=1 if budget == "one-node" else 64, max_edges=256, max_turns=1 if budget == "one-turn" else 4)
        case = _TurnCase(state, Mode.FIXED, graph_limits=limits)
        graph = StateGraphBuilder(_PolicyDrivenBattleStateExpander(_TurnOracle.resolver(state), _TurnOracle.policy(case.attacker_policy), _TurnOracle.policy(case.defender_policy)), limits).build(state)
        store = InMemoryBattleGraphStore()
        handle = store.put(BattleGraphArtifact(graph, _REVISION))
        app = FastAPI()
        app.state.battle_graph_store = store
        app.include_router(inference.router, prefix="/v1/inference")
        fixed = _ABIOracle.request(case).operations[0]
        assert isinstance(fixed, FixedOperation)
        base = _Operation(fixed_request=fixed, expected_engine_version=fixed_query_core.versions.engine_version,
            expected_rules_version=fixed_query_core.versions.rules_version, expected_nodes=len(graph.nodes), expected_edges=len(graph.edges),
            query=_Query(mode="explore", graph_id=handle.graph_id))
        with TestClient(app) as client:
            root = self.compare(fixed_query_core, base, client)
            assert isinstance(root.value, BattleGraphExplorationResponse)
            for group in root.value.transition_groups:
                expanded = self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"outcomes", "group_id":group.group_id})}), client)
                assert isinstance(expanded.value, BattleTransitionGroupOutcomesResponse)
                for outcome in expanded.value.transition_group.outcomes[:2]:
                    advanced = self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"advance", "edge_id":outcome.edge_id})}), client)
                    assert isinstance(advanced.value, BattleGraphExplorationResponse)
                    cursor = ExplorationCursorRequest.model_validate(advanced.value.cursor.model_dump())
                    self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"backtrack", "cursor":cursor})}), client)
                    self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"backtrack", "cursor":cursor, "depth":999})}), client)
            self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"backtrack"})}), client)
            self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"advance", "edge_id":999999})}), client)
            self.compare(fixed_query_core, base.model_copy(update={"query":base.query.model_copy(update={"mode":"outcomes", "group_id":"missing"})}), client)
        for guard in ({"expected_engine_version":"changed"},{"expected_rules_version":"changed"},{"expected_nodes":len(graph.nodes)+1},{"expected_edges":len(graph.edges)+1}):
            rejected = fixed_query_core.query(base.model_copy(update=guard))
            assert rejected.value is None and rejected.error is not None and rejected.error.http_status == 409

    @staticmethod
    def compare(core: _Core, operation: _Operation, client: TestClient) -> _Reply:
        """真实原HTTP产生预期；不归一任何身份、分数、浮点展示或事件，只比较相同句柄。"""
        query = operation.query
        suffix = f"groups/{query.group_id}/outcomes" if query.mode == "outcomes" else query.mode
        body = query.model_dump(mode="json", exclude_none=True, exclude={"mode", "graph_id", "group_id"})
        expected = client.post(f"/v1/inference/graphs/{query.graph_id}/{suffix}", json=body)
        actual = core.query(operation)
        assert actual.mode == query.mode
        if expected.status_code == 200:
            assert actual.error is None and actual.value is not None
            assert actual.value.model_dump(mode="json") == expected.json()
        else:
            assert actual.value is None and actual.error is not None
            assert actual.error.http_status == expected.status_code
            assert {"detail":{"code":actual.error.code,"message":actual.error.message}} == expected.json()
        return actual
