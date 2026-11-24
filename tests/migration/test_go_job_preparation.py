"""原202→逐case准备失败异步合同，经真实 Go daemon 与原 SQL/协调器完整差分。"""

from __future__ import annotations

import time
import os
import base64
import json
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pokeop.api.routers._configuration_jobs.dependencies import inference_use_case, job_store
from pokeop.api.routers.configuration_jobs import router
from pokeop.api.schemas.configuration_jobs import CreateBattleInferenceJobRequest
from pokeop.application.use_cases._battle_inference_worker.coordinator import RunBattleInferenceWorkerUseCase
from pokeop.application.use_cases._battle_inference_worker.preparation import RepositoryBackedBattleInferenceCasePreparer
from pokeop.persistence.battle_inference import repository
from pokeop.persistence.battle_inference.runtime_repository import PostgresBattleInferenceJobStore
from pokeop.persistence.runtime_schema import create_runtime_tables
from tests.migration.test_go_calculator import _OracleDatabase
from tests.migration.test_go_job_submission import _SubmissionClients


_INVALID_NATURE_SNAPSHOT = "preset-snapshot:" + base64.urlsafe_b64encode(json.dumps({
    "nature_id": "not-a-nature",
    "evs": {field: 0 for field in ("hp", "attack", "defense", "special_attack", "special_defense", "speed")},
    "ivs": {field: 31 for field in ("hp", "attack", "defense", "special_attack", "special_defense", "speed")},
}).encode()).decode().rstrip("=")


@pytest.fixture
def preparation_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SubmissionClients]:
    """原 worker 使用同知识版本的独占参考数据库，避免两个实际coordinator争抢对方待领取任务。"""
    dsn = os.environ.get("PBI_TEST_PREPARATION_REFERENCE_DSN")
    endpoint = os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    if not dsn or not endpoint:
        pytest.skip("explicit isolated reference PostgreSQL and Go HTTP endpoint are required")
    engine = create_engine(dsn)
    create_runtime_tables(engine)
    database = _OracleDatabase(engine)
    monkeypatch.setattr(repository, "_db_runtime", database.runtime)
    store = PostgresBattleInferenceJobStore(transaction_factory=sessionmaker(engine).begin)
    app = FastAPI()
    app.include_router(router, prefix="/v1/inference")
    # 原API依赖只借用真正SQL store；engine生命周期由此fixture统一拥有。
    app.dependency_overrides[job_store] = lambda: store
    try:
        with TestClient(app) as legacy, httpx.Client(base_url=endpoint, timeout=35) as remote:
            yield _SubmissionClients(remote, legacy, Path(os.environ["PBI_SUBMISSION_REPORT"]), store)
    finally:
        engine.dispose()


class TestOriginalPreparationFailure:
    """无战斗子进程参与准备失败；真实数据库领取/逐case失败/收口必须保留原行为。"""

    @pytest.mark.parametrize("profile", ["unknown-profile", "no_investment", "max_spatk_plus", "max_spatk_neutral", "preset-snapshot:!!!!", pytest.param(_INVALID_NATURE_SNAPSHOT, id="snapshot-unknown-nature")])
    def test_real_coordinators_match(self, preparation_clients: _SubmissionClients, profile: str) -> None:
        """profile 只换原能力键；原严格准入接受全部五case，之后两个实际worker各自产生相同失败。"""
        clients = preparation_clients
        request = CreateBattleInferenceJobRequest.model_validate_json((clients.report / "create-request.json").read_text())
        request.attacker.fixed.stat_profile_id = profile
        request.attacker.candidate_move_ids = [17, 404, 806, 814, 851]
        body = request.model_dump(mode="json")
        trial = uuid4().hex
        (clients.report / f"preparation-{trial}.request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        actual = clients.remote.post("/v1/inference/configuration-jobs", json=body, headers={"Idempotency-Key": "go-preparation-" + trial})
        assert actual.status_code == 202, actual.text
        go_id = actual.json()["job_id"]
        deadline = time.monotonic() + 20
        while True:
            go_status = clients.remote.get(f"/v1/inference/configuration-jobs/{go_id}")
            assert go_status.status_code == 200, go_status.text
            if go_status.json()["status"] == "partial":
                break
            assert time.monotonic() < deadline, go_status.text
            time.sleep(0.05)

        # 使用独立key创建原任务；原公开协调器真实领取并调用repository-backed preparer，不手工塞失败结果。
        expected = clients.legacy.post("/v1/inference/configuration-jobs", json=body, headers={"Idempotency-Key": "python-preparation-" + trial})
        assert expected.status_code == 202, expected.text
        python_id = expected.json()["job_id"]
        original = RunBattleInferenceWorkerUseCase(
            store=clients.store,
            preparer=RepositoryBackedBattleInferenceCasePreparer(inference_use_case()),
            worker_id="python-preparation-oracle-" + trial,
            poll_interval_seconds=0,
        )
        assert original.run_once()
        python_status = clients.legacy.get(f"/v1/inference/configuration-jobs/{python_id}")
        assert python_status.status_code == 200, python_status.text
        old, new = python_status.json(), go_status.json()
        for field in ("job_id", "created_at", "updated_at", "completed_at"):
            old.pop(field)
            new.pop(field)
        assert old == new
        assert new["counts"]["failed"] == new["counts"]["total"] == 5
        assert new["last_failure_code"] is None and new["last_failure_diagnostic"] is None

        go_results = clients.remote.get(f"/v1/inference/configuration-jobs/{go_id}/results")
        old_results = clients.legacy.get(f"/v1/inference/configuration-jobs/{python_id}/results")
        assert go_results.status_code == old_results.status_code == 200
        assert go_results.json()["items"] == old_results.json()["items"]
        for result in go_results.json()["items"]:
            assert result["failure_code"] == "invalid_configuration"
            expected_reason = "invalid stat configuration snapshot" if profile.startswith("preset-snapshot:") else "unknown stat profile preset: " + profile
            if profile == _INVALID_NATURE_SNAPSHOT:
                expected_reason = "unsupported nature: not-a-nature"
            assert result["diagnostic"] == "ConfigurationSpaceError: " + expected_reason
            assert result["node_count"] == result["edge_count"] == 0
            assert result["attacker_win_probability"] is None and result["expected_turns"] is None
        (clients.report / f"preparation-{trial}.go.json").write_bytes(go_results.content)
        (clients.report / f"preparation-{trial}.python.json").write_bytes(old_results.content)
