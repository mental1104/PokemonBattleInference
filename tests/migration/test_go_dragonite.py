"""真实PG上原快龙旅程与Go reference配置→独立Core→唯一图store的完整公开对照。"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from pokeop.api.schemas.battle_exploration import (
    BattleGraphExplorationResponse,
    BattleTransitionGroupOutcomesResponse,
    ExploreBattleGraphRequest,
    StoredBattleInferenceJourneyResponse,
)
from pokeop.api.schemas.inference import DragoniteWeavileJourneyRequest
from tests.migration.test_go_fixed_graph import _GraphClients, _GraphPair
from tests.migration.test_go_fixed_graph import graph_clients as graph_clients  # noqa: PLC0414 -- pytest需要显式重导出fixture。
from tests.migration.test_go_fixed_inference import fixed_clients as fixed_clients  # noqa: PLC0414 -- 保留graph_clients的真实PG依赖。


class TestGoDragoniteJourney:
    """透明中性假设只在原reference入口运行；工厂PARTIAL维度仍保持原拒绝。"""

    @pytest.mark.parametrize(
        "scenario",
        ("default", "fake-out-pressure", "defensive", "inner-focus", "unknown-profile"),
    )
    def test_real_reference_journey(
        self, graph_clients: _GraphClients, scenario: str
    ) -> None:
        """完整summary/代表路径/机制覆盖及后续导航相等，唯一归一store的随机UUID/已验证时间。"""
        request = DragoniteWeavileJourneyRequest()
        status = 200
        if scenario == "fake-out-pressure":
            request.weavile_plan = "fake-out-pressure"
            # 原repository/provider会过滤此招式组合，实际合同是完整422；选项存在不保证可执行。
            status = 422
        elif scenario == "defensive":
            request.dragonite_stat_preset = "max_hp_def_plus"
        elif scenario == "inner-focus":
            request.dragonite_ability = "inner-focus"
            status = 422
        elif scenario == "unknown-profile":
            request.weavile_stat_preset = "unknown-profile"
            status = 422
        path = "/v1/inference/dragonite-vs-weavile"
        before = datetime.now(UTC)
        expected = graph_clients.clients.original.post(
            path, json=request.model_dump(mode="json")
        )
        actual = graph_clients.clients.remote.post(
            path, json=request.model_dump(mode="json")
        )
        graph_clients.record(
            "dragonite-" + scenario, request.model_dump_json(indent=2), expected, actual
        )
        assert actual.status_code == expected.status_code == status, (
            actual.text,
            expected.text,
        )
        if status != 200:
            assert actual.json() == expected.json()
            return
        left = StoredBattleInferenceJourneyResponse.model_validate_json(actual.content)
        right = StoredBattleInferenceJourneyResponse.model_validate_json(
            expected.content
        )
        for handle in (left.exploration, right.exploration):
            assert re.fullmatch(r"[0-9a-f]{32}", handle.graph_id)
            assert (
                before + timedelta(minutes=14)
                < handle.expires_at
                < datetime.now(UTC) + timedelta(minutes=16)
            )
        body = actual.json()
        reference = expected.json()
        for value in (body, reference):
            value["exploration"]["graph_id"] = "<opaque-graph>"
            value["exploration"]["expires_at"] = "<validated-expiry>"
        assert body == reference
        assert (
            "ability:pressure:real_ability_behavior" in left.summary.excluded_mechanisms
        )
        pair = _GraphPair(
            left.exploration.graph_id,
            right.exploration.graph_id,
            left.exploration.calculation_revision,
        )
        position = ExploreBattleGraphRequest(calculation_revision=pair.revision)
        root = graph_clients.query(
            pair, "explore", position, "dragonite-" + scenario + "-explore"
        )
        node = BattleGraphExplorationResponse.model_validate_json(root.content)
        assert node.node.defender.ability == "unknown"
        group = node.transition_groups[0]
        result = graph_clients.query(
            pair,
            f"groups/{group.group_id}/outcomes",
            position,
            "dragonite-" + scenario + "-outcomes",
        )
        expanded = BattleTransitionGroupOutcomesResponse.model_validate_json(
            result.content
        )
        graph_clients.query(
            pair,
            "advance",
            position,
            "dragonite-" + scenario + "-advance",
            edge_id=expanded.transition_group.outcomes[0].edge_id,
        )

    @pytest.mark.parametrize(
        "field,value",
        (
            ("dragonite_ability", "other"),
            ("weavile_plan", "other"),
            ("dragonite_ability", None),
        ),
    )
    def test_original_schema_rejections(
        self, graph_clients: _GraphClients, field: str, value: str | None
    ) -> None:
        """原受控字段非法值/显式null都是422，格式化validation文本不当作机制业务错误。"""
        body = {field: value}
        path = "/v1/inference/dragonite-vs-weavile"
        expected = graph_clients.clients.original.post(path, json=body)
        actual = graph_clients.clients.remote.post(path, json=body)
        graph_clients.record(
            "dragonite-invalid-" + field + ("-null" if value is None else ""),
            json.dumps(body),
            expected,
            actual,
        )
        assert actual.status_code == expected.status_code == 422
