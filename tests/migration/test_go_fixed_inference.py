"""同一真实PG下对照原固定推演HTTP与独立Go/Core的完整summary与拒绝响应。"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from pokeop.api.routers.fixed_battle import router
from pokeop.api.schemas.fixed_battle import FixedBattleChosenSideRequest, FixedBattleGraphLimitsRequest, FixedBattleSummaryRequest
from pokeop.api.schemas.inference import BattleInferenceSummaryResponse
from pokeop.persistence.battle_inference import repository
from tests.migration.test_go_calculator import _OracleDatabase


@dataclass(frozen=True)
class _FixedClients:
    """两个公开HTTP客户端读取同一自有PG，report独立保存每次请求和双方原始响应。"""
    original: TestClient
    remote: httpx.Client
    report: Path

    def compare(self, request: FixedBattleSummaryRequest, label: str, status: int) -> tuple[httpx.Response, httpx.Response]:
        """request是原公开DTO；label只用于自有报告，完整字段无容差比较，失败不会静默跳过。"""
        body = request.model_dump(mode="json")
        path = "/v1/inference/fixed-one-on-one"
        self.report.joinpath(label + ".request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        expected = self.original.post(path, json=body)
        actual = self.remote.post(path, json=body)
        self.report.joinpath(label + ".python.json").write_bytes(expected.content)
        self.report.joinpath(label + ".go.json").write_bytes(actual.content)
        self.report.joinpath(label + ".status.json").write_text(json.dumps({"python": expected.status_code, "go": actual.status_code}))
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        if status == 200:
            assert BattleInferenceSummaryResponse.model_validate_json(actual.content) == BattleInferenceSummaryResponse.model_validate_json(expected.content)
        assert actual.json() == expected.json()
        return actual, expected


class _Requests:
    """只组装原选择和预算，不计算任何能力、图、概率或覆盖结果。"""
    @staticmethod
    def fixed(attacker: int = 212, ability: str = "technician", moves: tuple[int, ...] = (404,), *, level: int = 50) -> FixedBattleSummaryRequest:
        """返回原公开固定输入；defender沿用真实Dragonite/Multiscale和合法DragonClaw。"""
        return FixedBattleSummaryRequest(
            attacker=FixedBattleChosenSideRequest(pokemon_id=attacker, level=level, stat_profile_id="max_atk_plus", ability_identifier=ability, move_ids=list(moves)),
            defender=FixedBattleChosenSideRequest(pokemon_id=149, level=level, stat_profile_id="max_hp_def_plus", ability_identifier="multiscale", move_ids=[337]),
            attacker_policy="first-legal", defender_policy="first-legal",
            limits=FixedBattleGraphLimitsRequest(max_nodes=20000, max_edges=80000, max_turns=20),
        )


@pytest.fixture
def fixed_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FixedClients]:
    """仅替换原repository连接端口；yield实际原路由与独立Go HTTP，退出关闭自己的连接池。"""
    endpoint = os.environ.get("PBI_FIXED_INFERENCE_URL")
    dsn = os.environ.get("PBI_FIXED_INFERENCE_POSTGRES_URL")
    report = os.environ.get("PBI_FIXED_INFERENCE_REPORT_DIRECTORY")
    if not endpoint or not dsn or not report:
        pytest.skip("explicit isolated Go HTTP, PostgreSQL and report directory are required")
    directory = Path(report)
    directory.mkdir(parents=True, exist_ok=True)
    engine = create_engine(dsn)
    database = _OracleDatabase(engine)
    monkeypatch.setattr(repository, "_db_runtime", database.runtime)
    app = FastAPI()
    app.include_router(router, prefix="/v1/inference")
    try:
        with TestClient(app, raise_server_exceptions=False) as original, httpx.Client(base_url=endpoint, timeout=35) as remote:
            yield _FixedClients(original, remote, directory)
    finally:
        engine.dispose()


class TestGoFixedInference:
    """真实固定摘要闭环，严格边界与原局部允许partial旅程保持不同策略。"""
    @pytest.mark.parametrize("scenario", ["baseline", "choice-band", "fake-out", "two-moves", "uniform", "level-100"])
    def test_complete_summary(self, fixed_clients: _FixedClients, scenario: str) -> None:
        """真实双方资料、Core状态和全部summary字段，对照原summary builder/factory/solver。"""
        request = _Requests.fixed()
        if scenario == "choice-band":
            request.attacker.item_identifier = "choice-band"
        elif scenario == "fake-out":
            request = _Requests.fixed(52, "technician", (252,))
        elif scenario == "two-moves":
            request = _Requests.fixed(52, "technician", (252, 10))
        elif scenario == "uniform":
            request = _Requests.fixed(52, "technician", (252, 10))
            request.attacker_policy = "uniform-random"
        elif scenario == "level-100":
            request = _Requests.fixed(52, "technician", (252,), level=100)
        fixed_clients.compare(request, "summary-" + scenario, 200)

    @pytest.mark.parametrize("scenario", ["partial-ability", "partial-move", "priority-move", "multiple-missing", "defender-partial", "unknown-profile", "unknown-ruleset"])
    def test_original_business_rejection(self, fixed_clients: _FixedClients, scenario: str) -> None:
        """partial/unknown不偷偷缩减技能组；原逐侧strict顺序、全部理由及错误envelope严格相同。"""
        request = _Requests.fixed()
        if scenario == "partial-ability":
            request.attacker.ability_identifier = "inner-focus"
        elif scenario == "partial-move":
            request = _Requests.fixed(461, "pressure", (8, 280))
        elif scenario == "priority-move":
            request.attacker.move_ids = [418, 404]
        elif scenario == "multiple-missing":
            request.attacker.move_ids = [999999, 999998]
            request.attacker.ability_identifier = "unknown-ability"
            request.attacker.item_identifier = "unknown-item"
            request.defender.ability_identifier = "unknown-defender"
        elif scenario == "defender-partial":
            request.defender.ability_identifier = "inner-focus"
        elif scenario == "unknown-profile":
            request.attacker.stat_profile_id = "unknown-stat-profile"
        elif scenario == "unknown-ruleset":
            request.ruleset_id = "unknown-ruleset"
        fixed_clients.compare(request, "reject-" + scenario, 422)

    @pytest.mark.parametrize("scenario", ["nodes", "edges", "turns"])
    def test_truncation_is_not_success_or_draw(self, fixed_clients: _FixedClients, scenario: Literal["nodes", "edges", "turns"]) -> None:
        """真实图预算触发后原诊断一致，不返回零概率、数学平局或200部分结果。"""
        request = _Requests.fixed()
        if scenario == "nodes":
            request.limits.max_nodes = 1
        elif scenario == "edges":
            request.limits.max_edges = 1
        else:
            request.limits.max_turns = 1
        fixed_clients.compare(request, "limit-" + scenario, 422)

    @pytest.mark.parametrize("scenario", ["pokemon", "version"])
    def test_missing_actual_knowledge(self, fixed_clients: _FixedClients, scenario: str) -> None:
        """真实PG缺失资料沿原fixed专属404边界，不能伪造零能力或默认知识。"""
        request = _Requests.fixed()
        if scenario == "pokemon":
            request.attacker.pokemon_id = 999999
        else:
            request.version_group_id = 999999
        fixed_clients.compare(request, "missing-" + scenario, 404)

    def test_original_schema_rejects_explicit_null(self, fixed_clients: _FixedClients) -> None:
        """省略默认不等于显式null；框架生成的detail文案只比较422状态，不冒称逐字等价。"""
        path = "/v1/inference/fixed-one-on-one"
        baseline = _Requests.fixed().model_dump(mode="json")
        for field in ("ruleset_id", "version_group_id", "attacker_policy", "limits"):
            body = dict(baseline)
            body[field] = None
            expected = fixed_clients.original.post(path, json=body)
            actual = fixed_clients.remote.post(path, json=body)
            fixed_clients.report.joinpath("schema-" + field + ".python.json").write_bytes(expected.content)
            fixed_clients.report.joinpath("schema-" + field + ".go.json").write_bytes(actual.content)
            assert actual.status_code == expected.status_code == 422
