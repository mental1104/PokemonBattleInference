"""原固定任务与组合预览的真实同PG HTTP对照，测试不得生成替代数学结果。"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pokeop.api.routers._configuration_jobs.dependencies import job_store
from pokeop.api.routers.fixed_battle import router
from pokeop.persistence.battle_inference import repository
from pokeop.persistence.battle_inference.runtime_repository import (
    PostgresBattleInferenceJobStore,
)
from tests.migration.test_go_calculator import _OracleDatabase
from tests.migration.test_go_fixed_inference import _Requests


@dataclass(frozen=True)
class _Clients:
    """两端读取真实同PG；原store仅供原HTTP真实重放，report保存原始协议证据。"""
    original: TestClient
    remote: httpx.Client
    report: Path

    def compare(self, path: str, body: dict[str, object], label: str, status: int, key: str | None = None) -> None:
        """先Go后原HTTP；同库创建避免时间差，所有公开字段与原始状态完全比较。"""
        headers = {} if key is None else {"Idempotency-Key": key}
        actual = self.remote.post(path, json=body, headers=headers)
        expected = self.original.post(path, json=body, headers=headers)
        self.report.joinpath(label + ".request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        self.report.joinpath(label + ".go.json").write_bytes(actual.content)
        self.report.joinpath(label + ".python.json").write_bytes(expected.content)
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        assert actual.json() == expected.json()


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Clients]:
    """只替换连接生命周期，原SQL/工厂/strict/枚举/canonical和固定任务用例全部真实执行。"""
    endpoint = os.environ.get("PBI_FIXED_WORKFLOW_URL")
    dsn = os.environ.get("PBI_FIXED_WORKFLOW_DSN")
    report = os.environ.get("PBI_FIXED_WORKFLOW_REPORT")
    if not endpoint or not dsn or not report:
        pytest.skip("explicit isolated service, PostgreSQL and report directory are required")
    directory = Path(report)
    directory.mkdir(parents=True, exist_ok=True)
    engine = create_engine(dsn)
    monkeypatch.setattr(repository, "_db_runtime", _OracleDatabase(engine).runtime)
    store = PostgresBattleInferenceJobStore(transaction_factory=sessionmaker(engine).begin)
    app = FastAPI()
    app.include_router(router, prefix="/v1/inference")
    app.dependency_overrides[job_store] = lambda: store
    try:
        with TestClient(app, raise_server_exceptions=False) as original, httpx.Client(base_url=endpoint, timeout=35) as remote:
            yield _Clients(original, remote, directory)
    finally:
        engine.dispose()


class TestFixedJobsAndCombinations:
    """真实原合同成功、重放、冲突、完整strict及最大组合；worker由runner随后独立消费。"""

    @pytest.mark.parametrize("scenario", ["baseline", "none", "unknown-profile", "uniform", "reversed", "html-key"])
    def test_fixed_creation(self, clients: _Clients, scenario: str) -> None:
        """原单case任务202逐字段相同；unknown profile保留异步准备失败，不在这里伪造stats。"""
        request = _Requests.fixed()
        if scenario == "none":
            request.attacker.item_identifier = "none"
        if scenario == "unknown-profile":
            request.attacker.stat_profile_id = "missing-profile"
        if scenario == "uniform":
            request.attacker_policy = request.defender_policy = "uniform-random"
        if scenario == "reversed":
            request.attacker.move_ids = [851, 404]
        key = "fixed-workflow-" + scenario + ("<>&" if scenario == "html-key" else "")
        body = request.model_dump(mode="json")
        clients.compare("/v1/inference/fixed-one-on-one-jobs", body, "fixed-" + scenario, 202, key)
        clients.compare("/v1/inference/fixed-one-on-one-jobs", body, "replay-" + scenario, 202, key)

    def test_key_conflict(self, clients: _Clients) -> None:
        """同key更换预算后仍对应原job ID，两端真实不可变规格冲突409，原任务不被替换。"""
        request = _Requests.fixed()
        clients.compare("/v1/inference/fixed-one-on-one-jobs", request.model_dump(mode="json"), "conflict-create", 202, "fixed-workflow-conflict")
        request.limits.max_nodes += 1
        clients.compare("/v1/inference/fixed-one-on-one-jobs", request.model_dump(mode="json"), "conflict", 409, "fixed-workflow-conflict")

    def test_original_created_replay(self, clients: _Clients) -> None:
        """真实原Python已创建的任务没有Go definition，同请求仍202；不借重放认领旧任务执行。"""
        body = _Requests.fixed().model_dump(mode="json")
        path = "/v1/inference/fixed-one-on-one-jobs"
        created = clients.original.post(path, json=body, headers={"Idempotency-Key": "fixed-workflow-python-first"})
        assert created.status_code == 202, created.text
        clients.compare(path, body, "original-first-replay", 202, "fixed-workflow-python-first")
        # 该旧任务只验幂等读取；公开取消阻止随后真实Go worker误领未迁移的旧执行资料。
        cancelled = clients.remote.post(created.json()["links"]["cancel"])
        assert cancelled.status_code == 200, cancelled.text

    @pytest.mark.parametrize("scenario", ["one", "five", "ten", "unknown-profile", "wrong-revision", "ability", "item", "move", "illegal", "duplicate", "ability-before-duplicates", "missing-pokemon"])
    def test_combinations(self, clients: _Clients, scenario: str) -> None:
        """两侧完整列表/名字/顺序/ID与原直接枚举相同；拒绝场景比较完整reason而非数量。"""
        body = _Requests.fixed().model_dump(mode="json")
        for name in ("attacker", "defender"):
            side = body[name]
            assert isinstance(side, dict)
            side["candidate_move_ids"] = side.pop("move_ids")
        body = {name: body[name] for name in ("ruleset_id", "version_group_id", "attacker", "defender")}
        body["calculation_revision"] = "battle-inference.summary-exploration.v2"
        attacker = body["attacker"]
        defender = body["defender"]
        assert isinstance(attacker, dict) and isinstance(defender, dict)
        status = 200
        if scenario == "five":
            attacker["candidate_move_ids"] = [851, 814, 806, 404, 17]
        if scenario == "ten":
            for side, pokemon_id in ((attacker, 184), (defender, 183)):
                side.update(pokemon_id=pokemon_id, ability_identifier="thick-fat", candidate_move_ids=[885, 861, 851, 802, 401, 304, 56, 55, 33, 21])
        if scenario == "unknown-profile":
            attacker["stat_profile_id"] = "does-not-need-stats"
        if scenario == "wrong-revision":
            body["calculation_revision"] = "old"
            status = 422
        if scenario == "ability":
            attacker["ability_identifier"] = "pressure"
            status = 422
        if scenario == "item":
            attacker["item_identifier"] = "missing"
            status = 422
        if scenario == "move":
            attacker["candidate_move_ids"] = [418]
            status = 422
        if scenario == "illegal":
            attacker["candidate_move_ids"] = [999999]
            status = 422
        if scenario == "duplicate":
            attacker["candidate_move_ids"] = [404, 404]
            status = 422
        if scenario == "ability-before-duplicates":
            attacker.update(ability_identifier="pressure", candidate_move_ids=[404, 404])
            status = 422
        if scenario == "missing-pokemon":
            attacker["pokemon_id"] = 999999
            status = 404
        clients.compare("/v1/inference/move-set-combinations", body, "combinations-" + scenario, status)

    @pytest.mark.parametrize("scenario", ["move", "ability", "duplicate"])
    def test_fixed_strict(self, clients: _Clients, scenario: str) -> None:
        """固定任务复用整池strict，失败结构沿原fixed envelope，不混configuration-job source字段。"""
        request = _Requests.fixed()
        if scenario == "move":
            request.attacker.move_ids = [418]
        elif scenario == "ability":
            request.attacker.ability_identifier = "pressure"
        else:
            request.attacker.move_ids = [404, 404]
        clients.compare("/v1/inference/fixed-one-on-one-jobs", request.model_dump(mode="json"), "fixed-strict-" + scenario, 422, "fixed-workflow-strict-" + scenario)

    def test_terminal_replay(self, clients: _Clients) -> None:
        """runner完成真实worker消费后，重提同key返回实际succeeded而不是固定pending。"""
        clients.compare("/v1/inference/fixed-one-on-one-jobs", _Requests.fixed().model_dump(mode="json"), "terminal-replay", 202, "fixed-workflow-baseline")
        response = json.loads(clients.report.joinpath("terminal-replay.go.json").read_bytes())
        assert response["status"] == "succeeded", response
