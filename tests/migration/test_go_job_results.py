"""公开任务创建→真实独立协调器→PG→HTTP结果，与原摘要构图及完整业务归因逐字段对照。"""

from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest

from pokeop.api.routers._configuration_jobs.dependencies import inference_use_case
from pokeop.api.schemas.configuration_jobs import CreateBattleInferenceJobRequest
from pokeop.application.use_cases._battle_inference_worker.coordinator import (
    RunBattleInferenceWorkerUseCase,
)
from pokeop.application.use_cases._battle_inference_worker.preparation import (
    RepositoryBackedBattleInferenceCasePreparer,
)
from tests.migration.test_go_job_preparation import (
    preparation_clients as preparation_clients,  # noqa: PLC0414 -- pytest显式加载独占参考库fixture。
)
from tests.migration.test_go_job_submission import _SubmissionClients


class TestOriginalPersistentJobResults:
    """两端使用同版本完整知识、独立PG任务队列，直接比较真实成功和预算终态。"""

    @pytest.mark.parametrize(
        "scenario", ("solved", "node-budget", "edge-budget", "turn-budget")
    )
    def test_real_summary_and_business_explanation(
        self, preparation_clients: _SubmissionClients, scenario: str
    ) -> None:
        """执行同一原公开合同，比较完整结果而非由测试重算数学或归因。

        Args:
            preparation_clients: 真正Go服务及原HTTP/协调器，参考库仅复用相同知识快照。
            scenario: 完整求解或原节点、边、回合预算；每项只含一个真实canonical配置。

        两端请求、状态和完整结果写入专项报告；只有随机任务ID及服务端时刻允许归一。
        """
        clients = preparation_clients
        request = CreateBattleInferenceJobRequest.model_validate_json(
            (clients.report / "create-request.json").read_text()
        )
        if scenario == "node-budget":
            request.execution.max_nodes_per_pair = 2
        elif scenario == "edge-budget":
            request.execution.max_edges_per_pair = 2
        elif scenario == "turn-budget":
            request.execution.max_turns = 1
        body = request.model_dump(mode="json")
        trial = "summary-" + scenario + "-" + uuid4().hex
        (clients.report / (trial + ".request.json")).write_text(
            json.dumps(body, ensure_ascii=False, indent=2)
        )
        actual = clients.remote.post(
            "/v1/inference/configuration-jobs",
            json=body,
            headers={"Idempotency-Key": "go-" + trial},
        )
        expected = clients.legacy.post(
            "/v1/inference/configuration-jobs",
            json=body,
            headers={"Idempotency-Key": "python-" + trial},
        )
        assert actual.status_code == expected.status_code == 202, (
            actual.text,
            expected.text,
        )
        go_id, python_id = actual.json()["job_id"], expected.json()["job_id"]

        # 原协调器必须真实执行repository-backed preparer与原Summary构图，不能直接写入预期结果。
        original = RunBattleInferenceWorkerUseCase(
            store=clients.store,
            preparer=RepositoryBackedBattleInferenceCasePreparer(inference_use_case()),
            worker_id="python-" + trial,
            poll_interval_seconds=0,
        )
        assert original.run_once()
        deadline = time.monotonic() + 60
        while True:
            go_status = clients.remote.get(f"/v1/inference/configuration-jobs/{go_id}")
            assert go_status.status_code == 200, go_status.text
            if go_status.json()["status"] in (
                "completed",
                "partial",
                "failed",
                "cancelled",
            ):
                break
            assert time.monotonic() < deadline, go_status.text
            time.sleep(0.05)

        python_status = clients.legacy.get(
            f"/v1/inference/configuration-jobs/{python_id}"
        )
        go_results = clients.remote.get(
            f"/v1/inference/configuration-jobs/{go_id}/results"
        )
        python_results = clients.legacy.get(
            f"/v1/inference/configuration-jobs/{python_id}/results"
        )
        for label, response in (
            ("go-status", go_status),
            ("python-status", python_status),
            ("go", go_results),
            ("python", python_results),
        ):
            (clients.report / (trial + "." + label + ".json")).write_bytes(
                response.content
            )
            assert response.status_code == 200, response.text

        left, right = go_status.json(), python_status.json()
        for field in ("job_id", "created_at", "updated_at", "completed_at"):
            left.pop(field)
            right.pop(field)
        assert left == right
        results = go_results.json()
        reference = python_results.json()
        assert results["job_id"] == go_id and reference["job_id"] == python_id
        # 两个独立任务使用不同幂等key；只归一外层job_id，case身份、预算和完整解释均严格比较。
        results["job_id"] = reference["job_id"] = "<independent-job>"
        assert results == reference
        assert results["total"] == len(results["items"]) == 1
        item = results["items"][0]
        if scenario == "solved":
            assert item["status"] == "succeeded"
            assert item["explanation"]["version"] == "battle-inference.explanation.v1"
            assert item["explanation"]["basis"] == "root-action-pair-attribution"
        else:
            assert item["status"] == "truncated"
            assert item["explanation"] is None
            assert item["attacker_win_probability"] is None
