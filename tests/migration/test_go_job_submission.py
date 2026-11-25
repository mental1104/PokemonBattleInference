"""原 HTTP 创建的同库完整响应、严格准入与实际 44,100 个 canonical 身份差分。"""

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
from pokeop.api.routers.configuration_jobs import router
from pokeop.api.schemas.configuration_jobs import CreateBattleInferenceJobRequest
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.application.use_cases._battle_inference_jobs.submission import _submission_job_id
from pokeop.application.use_cases.battle_inference_jobs import SubmitBattleInferenceJobCommand
from pokeop.persistence.battle_inference import repository
from pokeop.persistence.battle_inference.runtime_repository import PostgresBattleInferenceJobStore
from tests.migration.test_go_calculator import _OracleDatabase


@dataclass(frozen=True)
class _SubmissionClients:
    """两端读取同一独占 PG；report 保存 runner 的真实输入及逐端原始响应。"""

    remote: httpx.Client
    legacy: TestClient
    report: Path
    store: PostgresBattleInferenceJobStore

    def compare(self, request: CreateBattleInferenceJobRequest, key: str, label: str, status: int = 202) -> None:
        """先由真实 Go 创建，再由原 HTTP 重提；完整响应和 content-addressed ID 必须一致。"""
        body = request.model_dump(mode="json")
        headers = {"Idempotency-Key": key}
        actual = self.remote.post("/v1/inference/configuration-jobs", json=body, headers=headers)
        expected = self.legacy.post("/v1/inference/configuration-jobs", json=body, headers=headers)
        (self.report / f"oracle-{label}.go.json").write_bytes(actual.content)
        (self.report / f"oracle-{label}.python.json").write_bytes(expected.content)
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        assert actual.json() == expected.json()


@pytest.fixture
def submission_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SubmissionClients]:
    """仅替换原连接端口；SQL、工厂对账、准入、canonical 和原 store 都执行实际实现。"""
    endpoint = os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    dsn = os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
    if not endpoint or not dsn:
        pytest.skip("explicit isolated PostgreSQL and Go HTTP endpoint are required")
    engine = create_engine(dsn)
    database = _OracleDatabase(engine)
    monkeypatch.setattr(repository, "_db_runtime", database.runtime)
    store = PostgresBattleInferenceJobStore(transaction_factory=sessionmaker(engine).begin)
    app = FastAPI()
    app.include_router(router, prefix="/v1/inference")
    # 依赖回调只借用上方真实 SQL store；fixture 结束由 engine 统一关闭连接池。
    app.dependency_overrides[job_store] = lambda: store
    try:
        with TestClient(app, raise_server_exceptions=False) as legacy, httpx.Client(base_url=endpoint, timeout=35) as remote:
            yield _SubmissionClients(remote, legacy, Path(os.environ["PBI_SUBMISSION_REPORT"]), store)
    finally:
        engine.dispose()


class TestOriginalJobSubmission:
    """按真实调用者的创建/重试/拒绝与全池持久化责任聚合，不在测试内重写组合数学。"""

    @pytest.mark.parametrize("item,key", [(None, "oracle-normal"), ("none", "oracle-none"), (None, "oracle-<&>")])
    def test_success_and_idempotency(self, submission_clients: _SubmissionClients, item: str | None, key: str) -> None:
        """null/明确 none 和含 HTML 标点的合法 HTTP 幂等键均走原应用 SHA；重提恢复实际任务。"""
        request = CreateBattleInferenceJobRequest.model_validate_json((submission_clients.report / "create-request.json").read_text())
        request.attacker.fixed.item_identifier = item
        submission_clients.compare(request, key, key.encode().hex())
        submission_clients.compare(request, key, key.encode().hex() + "-replay")

    @pytest.mark.parametrize("scenario", ["partial-ability", "missing-selection", "partial-moves"])
    def test_strict_rejection(self, submission_clients: _SubmissionClients, scenario: str) -> None:
        """原 strict 必须收齐失败及去重顺序；不可选择项不能被过滤成较小的成功任务。"""
        request = CreateBattleInferenceJobRequest.model_validate_json((submission_clients.report / "create-request.json").read_text())
        if scenario == "partial-ability":
            request.attacker.fixed.pokemon_id = 461
            request.attacker.fixed.ability_identifier = "pressure"
            request.attacker.candidate_move_ids = [8, 280]
        elif scenario == "missing-selection":
            request.attacker.fixed.ability_identifier = "unknown-ability"
            request.attacker.fixed.item_identifier = "unknown-item"
            request.attacker.candidate_move_ids = [999999, 999998, 999997, 999996, 999995]
        else:
            request.attacker.fixed.pokemon_id = 461
            request.attacker.fixed.ability_identifier = "pickpocket"
            request.attacker.candidate_move_ids = [8, 280, 17, 404, 806]
        submission_clients.compare(request, "oracle-" + scenario, scenario, 422)

    def test_all_stored_concrete_cases(self, submission_clients: _SubmissionClients) -> None:
        """实际 202 后存出的全部 44,100 case 与原公开 command iterator/identity 逐字段一致。"""
        directory = submission_clients.report
        request = CreateBattleInferenceJobRequest.model_validate_json((directory / "bulk-request.json").read_text())
        command, spec = request.to_application()
        stored = json.loads((directory / "bulk-definition.json").read_text())
        assert stored["job_id"] == _submission_job_id(SubmitBattleInferenceJobCommand(
            move_pool=command, execution_spec=spec, idempotency_key="p3-bulk-44100-shared-template"
        ))
        assert len(stored["cases"]) == 44100
        for actual, configuration in zip(stored["cases"], command.iter_configurations(), strict=True):
            expected = case_definition(configuration)
            assert actual == {
                "configuration_pair_id": expected.configuration_pair_id,
                "attacker_configuration_id": expected.attacker_configuration_id,
                "defender_configuration_id": expected.defender_configuration_id,
                "attacker_move_ids": list(expected.attacker_move_ids),
                "defender_move_ids": list(expected.defender_move_ids),
            }
        native = stored["admission"]["core_response"]
        assert stored["core_request_template"] and native["schema_version"] == 1
        assert native["engine_version"] and native["rules_version"]

    def test_unknown_ruleset(self, submission_clients: _SubmissionClients) -> None:
        """原 composition 在读取资料前拒绝非工厂 ruleset，完整业务错误必须相同。"""
        request = CreateBattleInferenceJobRequest.model_validate_json((submission_clients.report / "create-request.json").read_text())
        request.ruleset_id = "unknown-ruleset"
        submission_clients.compare(request, "oracle-unknown-ruleset", "unknown-ruleset", 422)

    @pytest.mark.parametrize("scenario", ["missing-pokemon", "wrong-version"])
    def test_business_input_rejection(self, submission_clients: _SubmissionClients, scenario: str) -> None:
        """显式记录两项旧资料缺失500/新入口422差异；不将修复原未捕获异常记成逐字等价。"""
        request = CreateBattleInferenceJobRequest.model_validate_json((submission_clients.report / "create-request.json").read_text())
        if scenario == "missing-pokemon":
            request.attacker.fixed.pokemon_id = 999999
        elif scenario == "wrong-version":
            request.version_group_id = 999999
        headers = {"Idempotency-Key": "oracle-" + scenario}
        body = request.model_dump(mode="json")
        actual = submission_clients.remote.post("/v1/inference/configuration-jobs", json=body, headers=headers)
        expected = submission_clients.legacy.post("/v1/inference/configuration-jobs", json=body, headers=headers)
        (submission_clients.report / f"boundary-{scenario}.go.body").write_bytes(actual.content)
        (submission_clients.report / f"boundary-{scenario}.python.body").write_bytes(expected.content)
        assert actual.status_code == 422, actual.text
        assert expected.status_code == 500, expected.text
        assert actual.json()["detail"]["code"] == "battle_inference_job_invalid_request"
