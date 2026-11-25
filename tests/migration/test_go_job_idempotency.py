"""原configuration-jobs跨Python/Go定义格式的幂等合同；不把fixed仅key身份套到此入口。"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import create_engine, text

from pokeop.api.schemas.configuration_jobs import CreateBattleInferenceJobRequest
from pokeop.application.repositories.battle_inference_jobs import (
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.application.use_cases._battle_inference_jobs.submission import (
    _submission_job_id,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    SubmitBattleInferenceJobCommand,
)
from tests.migration.test_go_job_submission import _SubmissionClients

# 只复用项目已有真实PG/原HTTP fixture的pytest声明，不替换原准入/身份/持久化用例。
pytest_plugins = ["tests.migration.test_go_job_submission"]


def _request(clients: _SubmissionClients) -> CreateBattleInferenceJobRequest:
    """从runner已成功提交的原完整单case请求读取独立DTO；clients.report为本次独占报告目录。"""
    return CreateBattleInferenceJobRequest.model_validate_json(clients.report.joinpath("create-request.json").read_text())


class TestConfigurationJobIdempotency:
    """所有检查通过原HTTP和真实PG，不改原ID算法，也不静默覆盖旧任务的冻结证据。"""

    def test_original_python_job_without_go_definition(self, submission_clients: _SubmissionClients) -> None:
        """原Python先创建无Go definition任务；同一个合法请求由Go重放仍应原202/时间戳。"""
        request = _request(submission_clients)
        response = submission_clients.legacy.post("/v1/inference/configuration-jobs", json=request.model_dump(mode="json"), headers={"Idempotency-Key": "compat-python-first"})
        assert response.status_code == 202, response.text
        submission_clients.compare(request, "compat-python-first", "compat-python-first", 202)

    def test_only_core_metadata_changes_do_not_conflict(self, submission_clients: _SubmissionClients) -> None:
        """只改变历史Core版本元数据并保存正确字节SHA；重放不应误409或重写旧冻结值。"""
        request = _request(submission_clients)
        key = "compat-historical-core"
        submission_clients.compare(request, key, "compat-metadata-create", 202)
        job_id = json.loads(submission_clients.report.joinpath("oracle-compat-metadata-create.go.json").read_text())["job_id"]
        engine = create_engine(os.environ["PBI_TEST_GO_CALCULATOR_POSTGRES_URL"])
        try:
            with engine.begin() as connection:
                source = connection.execute(text("SELECT definition_json::text FROM poke_runtime.go_job_definitions WHERE job_id=:job"), {"job": job_id}).scalar_one()
                assert isinstance(source, str)
                body = json.loads(source)
                native = body["admission"]["core_response"]
                changed = source
                for field, value in (("engine_version", "historical-core"), ("rules_version", "historical-rules")):
                    marker = json.dumps(field) + ":" + json.dumps(native[field])
                    assert changed.count(marker) == 1
                    changed = changed.replace(marker, json.dumps(field) + ":" + json.dumps(value), 1)
                    native[field] = value
                assert json.loads(changed) == body
                # 只换两个metadata字符串，其他原始字节不重排，校验与Go Store对完整JSON的SHA相同。
                digest = sha256(changed.encode()).hexdigest()
                connection.execute(text("UPDATE poke_runtime.go_job_definitions SET definition_json=CAST(:body AS json),definition_hash=:hash WHERE job_id=:job"), {"body": changed, "hash": digest, "job": job_id})
            submission_clients.compare(request, key, "compat-metadata-replay", 202)
            with engine.connect() as connection:
                preserved = connection.execute(text("SELECT definition_json::text,definition_hash FROM poke_runtime.go_job_definitions WHERE job_id=:job"), {"job": job_id}).one()
                assert preserved[0] == changed and preserved[1] == digest
        finally:
            engine.dispose()

    def test_same_key_new_budget_keeps_original_new_identity(self, submission_clients: _SubmissionClients) -> None:
        """原config入口SHA包含预算；同key改变预算必须新ID202，不能按fixed入口误判409。"""
        request = _request(submission_clients)
        submission_clients.compare(request, "compat-budget", "compat-budget-before", 202)
        previous = json.loads(submission_clients.report.joinpath("oracle-compat-budget-before.go.json").read_text())["job_id"]
        request.execution.max_nodes_per_pair += 1
        submission_clients.compare(request, "compat-budget", "compat-budget-after", 202)
        current = json.loads(submission_clients.report.joinpath("oracle-compat-budget-after.go.json").read_text())["job_id"]
        assert previous != current

    def test_existing_same_identity_with_different_spec_conflicts(self, submission_clients: _SubmissionClients) -> None:
        """原store真实保存同ID却不同规格的任务；原HTTP与Go均应409，不能广泛放行所有旧记录。"""
        request = _request(submission_clients)
        command, spec = request.to_application()
        job_id = _submission_job_id(SubmitBattleInferenceJobCommand(move_pool=command, execution_spec=spec, idempotency_key="compat-conflict"))
        seed = CreateBattleInferenceJob(job_id=job_id, ruleset_id=command.ruleset_id, version_group_id=command.version_group_id,
                                       calculation_revision=command.calculation_revision, cases=tuple(case_definition(item) for item in command.iter_configurations()))
        submission_clients.store.create_job_with_execution_spec(seed, replace(spec, max_nodes_per_pair=spec.max_nodes_per_pair + 1), created_at=datetime.now(UTC))
        submission_clients.compare(request, "compat-conflict", "compat-spec-conflict", 409)
