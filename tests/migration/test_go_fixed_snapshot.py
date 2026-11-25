"""同一真实PG下原固定step与Go→独立Core快照的公开HTTP完整对照。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import pytest

from pokeop.api.schemas.battle_exploration import (
    BattleGraphExplorationResponse,
    ExplorationCursorRequest,
    ExplorationPathStepRequest,
)
from pokeop.api.schemas.fixed_battle import FixedBattleSnapshotStepRequest
from tests.migration.test_go_fixed_inference import _FixedClients, _Requests
from tests.migration.test_go_fixed_inference import fixed_clients as fixed_clients  # noqa: PLC0414 -- pytest显式重导出真实PG依赖fixture。


@dataclass(frozen=True)
class _SnapshotClients:
    """复用真实PG与两个独立HTTP客户端，不替代SQL、准备、resolver或事件。"""

    clients: _FixedClients

    def query(
        self, request: FixedBattleSnapshotStepRequest, label: str, status: int = 200
    ) -> httpx.Response:
        """request是原公开模型；保存双方原始响应，所有字段完整无容差比较。"""
        body = request.model_dump(mode="json")
        path = "/v1/inference/fixed-one-on-one/step"
        expected = self.clients.original.post(path, json=body)
        actual = self.clients.remote.post(path, json=body)
        self.clients.report.joinpath(label + ".request.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2)
        )
        self.clients.report.joinpath(label + ".python.json").write_bytes(
            expected.content
        )
        self.clients.report.joinpath(label + ".go.json").write_bytes(actual.content)
        self.clients.report.joinpath(label + ".status.json").write_text(
            json.dumps({"python": expected.status_code, "go": actual.status_code})
        )
        assert actual.status_code == expected.status_code == status, (
            actual.text,
            expected.text,
        )
        assert actual.json() == expected.json()
        if status == 200:
            BattleGraphExplorationResponse.model_validate_json(actual.content)
        return actual


@pytest.fixture
def snapshot_clients(fixed_clients: _FixedClients) -> _SnapshotClients:
    """原fixed router包含step，不使用store或伪造全图句柄。"""
    return _SnapshotClients(fixed_clients)


class TestGoFixedSnapshot:
    """按需快照重放只展开当前层，不能等待全局求解或把全图预算当终局。"""

    @pytest.mark.parametrize(
        "scenario",
        ("baseline", "fake-out", "uniform", "one-node-budget", "one-turn-budget"),
    )
    def test_actual_snapshot_and_formal_report(
        self, snapshot_clients: _SnapshotClients, scenario: str
    ) -> None:
        """至少根和真实后继全字段一致，包含原已展开组与每条正式边全部替代事件历史。"""
        fixed = _Requests.fixed()
        if scenario in {"fake-out", "uniform"}:
            fixed = _Requests.fixed(
                52, "technician", (252, 10) if scenario == "uniform" else (252,)
            )
        if scenario == "uniform":
            fixed.attacker_policy = "uniform-random"
        elif scenario == "one-node-budget":
            fixed.limits.max_nodes = 1
        elif scenario == "one-turn-budget":
            fixed.limits.max_turns = 1
        request = FixedBattleSnapshotStepRequest.model_validate(
            fixed.model_dump(mode="json")
        )
        root = snapshot_clients.query(request, "snapshot-" + scenario + "-root")
        current = BattleGraphExplorationResponse.model_validate_json(root.content)
        for depth in range(3):
            if current.terminal:
                break
            assert current.transition_groups and all(
                group.expanded for group in current.transition_groups
            )
            outcome = current.transition_groups[0].outcomes[0]
            request.cursor.steps.append(
                ExplorationPathStepRequest(
                    source_node_id=current.node.node_id,
                    edge_id=outcome.edge_id,
                    target_node_id=outcome.target_node_id,
                )
            )
            reply = snapshot_clients.query(
                request, f"snapshot-{scenario}-depth-{depth + 1}"
            )
            current = BattleGraphExplorationResponse.model_validate_json(reply.content)
            assert current.battle_report.depth == depth + 1
            assert current.cursor.model_dump(mode="json") == request.cursor.model_dump(
                mode="json"
            )
            if scenario == "one-turn-budget":
                assert current.node.turn_number > 1

    @pytest.mark.parametrize("scenario", ("source", "edge", "target", "strict-partial"))
    def test_original_cursor_and_strict_rejections(
        self, snapshot_clients: _SnapshotClients, scenario: str
    ) -> None:
        """原cursor构造错误、局部边错误和严格准入错误各自保留原422完整envelope。"""
        request = FixedBattleSnapshotStepRequest.model_validate(
            _Requests.fixed(52, "technician", (252,)).model_dump(mode="json")
        )
        if scenario == "strict-partial":
            request.defender.ability_identifier = "inner-focus"
        else:
            request.cursor = ExplorationCursorRequest(
                steps=[
                    ExplorationPathStepRequest(
                        source_node_id=1 if scenario == "source" else 0,
                        edge_id=999999 if scenario == "edge" else 0,
                        target_node_id=10001 if scenario == "target" else 10000,
                    )
                ]
            )
        snapshot_clients.query(request, "snapshot-reject-" + scenario, 422)
