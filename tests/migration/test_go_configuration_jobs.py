"""原 Python 持久任务资料经新 Go 四查询 API 的同库差分；只验证已存结果，不伪造执行器。"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from pokeop.api.routers._configuration_jobs.dependencies import job_store
from pokeop.api.routers.configuration_jobs import router
from pokeop.application.configuration_space.one_on_one import (
    FixedPokemonConfiguration, OneOnOneMovePoolCommand, PokemonMovePoolSelection,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseResult, BattleInferenceCaseStatus, BattleInferenceExpectedTurns,
    BattleInferenceExpectedTurnsKind, BattleInferenceFailureCode, BattleInferenceProbability,
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.application.use_cases.battle_inference_jobs import BattleInferenceExecutionSpec
from pokeop.persistence.battle_inference.runtime_repository import PostgresBattleInferenceJobStore


@dataclass(frozen=True)
class _StoredJob:
    """保存本次原仓库写入的只读测试夹具；没有 Go definition，也不声称经过战斗执行。"""

    store: PostgresBattleInferenceJobStore
    engine: Engine
    legacy: TestClient
    remote: httpx.Client
    job_id: str
    command: OneOnOneMovePoolCommand
    now: datetime
    pairs: tuple[str, ...]

    def record(self, label: str, actual: httpx.Response, expected: httpx.Response) -> None:
        """label 区分验收阶段，actual/expected 是两端原始响应；只向 runner 显式报告目录写协议证据。"""
        report = os.environ.get("PBI_TEST_CONFIGURATION_JOB_REPORT")
        if report:
            directory = Path(report)
            directory.mkdir(parents=True, exist_ok=True)
            name = self.job_id + "-" + hashlib.sha256(label.encode() + b"\x00" + actual.content).hexdigest()[:12]
            (directory / (name + ".go.json")).write_bytes(actual.content)
            (directory / (name + ".python.json")).write_bytes(expected.content)
            (directory / (name + ".request.txt")).write_text(
                f"{actual.request.method} {actual.request.url.raw_path.decode('ascii')}\n"
                f"go_status={actual.status_code} python_status={expected.status_code}\n",
                encoding="utf-8",
            )

    def check(self, suffix: str = "") -> None:
        """suffix 是原公开查询的相对路径；两个客户端读取同一行，完整 JSON 含时间/null/精确概率相同。"""
        path = "/v1/inference/configuration-jobs/" + self.job_id + suffix
        expected = self.legacy.get(path)
        actual = self.remote.get(path)
        self.record(suffix, actual, expected)
        assert expected.status_code == actual.status_code == 200, (expected.text, actual.text)
        assert actual.json() == expected.json()

    def success(self) -> BattleInferenceCaseResult:
        """返回超过 int64 分母的旧原生结果 DTO 夹具，仅用于读取协议验证。"""
        denominator = 10**35 + 1
        return BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.SUCCEEDED,
            attacker_win=BattleInferenceProbability(1, denominator),
            defender_win=BattleInferenceProbability(denominator - 1, denominator),
            draw=BattleInferenceProbability(0, 1),
            expected_turns=BattleInferenceExpectedTurns(BattleInferenceExpectedTurnsKind.FINITE, 4, 3),
            node_count=23, edge_count=41, budget_consumed=64,
            explanation_json='{"summary":"原结果 & <字段>","items":[1,null,true]}',
        )


@pytest.fixture
def stored_job() -> Iterator[_StoredJob]:
    """经原 Python store 创建 canonical 五 case 并持久化三种终态；全部连接仅指向 runner 独占库。"""
    dsn = os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
    endpoint = os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    if not dsn or not endpoint:
        pytest.skip("explicit isolated PostgreSQL and Go HTTP endpoint are required")
    engine = create_engine(dsn)
    store = PostgresBattleInferenceJobStore(transaction_factory=sessionmaker(engine).begin)
    command = OneOnOneMovePoolCommand(
        ruleset_id="pokemon-champion", version_group_id=25,
        calculation_revision="battle-inference.summary-exploration.v2",
        attacker=PokemonMovePoolSelection(
            FixedPokemonConfiguration(212, None, 50, "max_atk_plus", "technician", None),
            (33, 98, 232, 404, 418),
        ),
        defender=PokemonMovePoolSelection(
            FixedPokemonConfiguration(464, None, 50, "max_hp_def_plus", "solid-rock", "choice-band"),
            (89, 444),
        ),
    )
    job_id = "legacy-read-fixture-" + uuid4().hex
    now = datetime(2026, 11, 24, 1, 2, 3, 123456, tzinfo=UTC)
    cases = tuple(case_definition(item) for item in command.iter_configurations())
    spec = BattleInferenceExecutionSpec.from_command(command)
    store.create_job_with_execution_spec(
        CreateBattleInferenceJob(job_id, command.ruleset_id, command.version_group_id, command.calculation_revision, cases),
        spec, created_at=now,
    )
    app = FastAPI()
    app.include_router(router, prefix="/v1/inference")

    def dependency() -> PostgresBattleInferenceJobStore:
        """返回同一真实原仓库；只替换生产连接选择，无数据库或业务结果替身。"""
        return store

    app.dependency_overrides[job_store] = dependency
    try:
        with TestClient(app) as legacy, httpx.Client(base_url=endpoint, timeout=15) as remote:
            fixture = _StoredJob(store, engine, legacy, remote, job_id, command, now, tuple(item.configuration_pair_id for item in cases))
            fixture.check()  # 初始 pending→queued 的原完整时间/预算响应。
            claimed = store.claim_next_job(lease_owner=job_id, now=now, lease_duration=timedelta(days=1), calculation_revision=command.calculation_revision)
            assert claimed is not None and claimed.job_id == job_id
            running = store.claim_cases(job_id, lease_owner="legacy-worker", now=now, lease_duration=timedelta(days=1), limit=4, calculation_revision=command.calculation_revision)
            assert len(running) == 4
            outcomes = (
                fixture.success(),
                BattleInferenceCaseResult(status=BattleInferenceCaseStatus.FAILED, failure_code=BattleInferenceFailureCode.WORKER_CRASH, diagnostic="archived worker failure", node_count=3, edge_count=5),
                BattleInferenceCaseResult(status=BattleInferenceCaseStatus.TRUNCATED, failure_code=BattleInferenceFailureCode.GRAPH_NODE_LIMIT, diagnostic="archived graph limit", node_count=17, edge_count=29),
            )
            for case, outcome in zip(running, outcomes, strict=False):
                store.record_case_result(job_id, case.definition.configuration_pair_id, outcome, lease_owner="legacy-worker", completed_at=now + timedelta(seconds=1), calculation_revision=command.calculation_revision)
            with engine.connect() as connection:
                count = connection.execute(text("SELECT COUNT(*) FROM poke_runtime.go_job_definitions WHERE job_id=:id"), {"id": job_id}).scalar_one()
                assert count == 0, "legacy fixture must not acquire a Go definition"
            yield fixture
    finally:
        engine.dispose()


class TestConfigurationJobReads:
    """四个真实 HTTP 入口读取原 Python 表/规格/结果，兼容分页、取消和历史 explanation。"""

    @pytest.mark.parametrize("suffix", [
        "", "/results", "/results?limit=2", "/results?offset=2&limit=2",
        "/results?offset=99&limit=2", "/results?status=succeeded", "/results?status=pending",
        "/results?status=running", "/issues", "/issues?limit=1", "/issues?cursor=1&limit=1",
        "/issues?status=failed", "/issues?status=truncated&error_code=graph_node_limit",
        "/issues?error_code=worker_crash", "/issues?error_code=cancelled",
        "/results?limit=2&limit=1&offset=0&offset=1",
        "/issues?limit=2&limit=1&status=failed&status=truncated",
    ])
    def test_complete_pages(self, stored_job: _StoredJob, suffix: str) -> None:
        """stored_job 是原表夹具；suffix 覆盖过滤在分页前执行、空页、后页游标和全部 nullable 精确摘要。"""
        stored_job.check(suffix)

    @pytest.mark.parametrize("value", ["legacy unstructured note", "[1,2]", "null", '{"ok":true}'])
    def test_original_explanation_fallback(self, stored_job: _StoredJob, value: str) -> None:
        """value 是旧库允许的任意非空说明；原 presenter 的损坏/非对象 fallback 必须相同，写入约束不放宽。"""
        with stored_job.engine.begin() as connection:
            connection.execute(text("UPDATE poke_runtime.battle_inference_cases SET explanation_json=:value WHERE job_id=:job AND sequence_no=0"), {"value": value, "job": stored_job.job_id})
        stored_job.check("/results?status=succeeded")

    def test_cancel_is_persistent_and_idempotent(self, stored_job: _StoredJob) -> None:
        """先由 Go 持久取消，再让原 API 重放；请求时间不改变，旧行/已完成结果与终态响应完整一致。"""
        path = "/v1/inference/configuration-jobs/" + stored_job.job_id + "/cancel"
        actual = stored_job.remote.post(path)
        before = stored_job.store.get_job(stored_job.job_id)
        expected = stored_job.legacy.post(path)
        stored_job.record("cancel-requested", actual, expected)
        after = stored_job.store.get_job(stored_job.job_id)
        assert actual.status_code == expected.status_code == 200, (actual.text, expected.text)
        assert actual.json() == expected.json()
        assert before.cancel_requested_at == after.cancel_requested_at
        stored_job.check()
        stored_job.store.cancel_unclaimed_cases(stored_job.job_id, cancelled_at=stored_job.now + timedelta(days=2))
        stored_job.store.finalize_job(stored_job.job_id, completed_at=stored_job.now + timedelta(days=2))
        stored_job.check()
        stored_job.check("/results")
        terminal = stored_job.remote.post(path)
        terminal_expected = stored_job.legacy.post(path)
        stored_job.record("cancel-terminal", terminal, terminal_expected)
        assert terminal.json() == terminal_expected.json()

    def test_partial_terminal_status(self, stored_job: _StoredJob) -> None:
        """经原真实仓库完成剩余 running/pending，Go 与原 API 对 completed_with_failures→partial 的映射相同。"""
        job = stored_job
        job.store.record_case_result(job.job_id, job.pairs[3], job.success(), lease_owner="legacy-worker", completed_at=job.now + timedelta(seconds=2), calculation_revision=job.command.calculation_revision)
        claimed = job.store.claim_cases(job.job_id, lease_owner="legacy-worker", now=job.now + timedelta(seconds=2), lease_duration=timedelta(days=1), limit=1, calculation_revision=job.command.calculation_revision)
        assert len(claimed) == 1
        job.store.record_case_result(job.job_id, job.pairs[4], job.success(), lease_owner="legacy-worker", completed_at=job.now + timedelta(seconds=3), calculation_revision=job.command.calculation_revision)
        job.store.finalize_job(job.job_id, completed_at=job.now + timedelta(seconds=3))
        job.check()
        job.check("/results")

    @pytest.mark.parametrize("suffix", ["", "/results", "/issues", "/cancel"])
    def test_missing_job_envelope(self, stored_job: _StoredJob, suffix: str) -> None:
        """suffix 选择四条原端点；不存在任务必须完整保留404 code/message，而非空列表或假取消成功。"""
        path = "/v1/inference/configuration-jobs/missing-job" + suffix
        method = "POST" if suffix == "/cancel" else "GET"
        actual = stored_job.remote.request(method, path)
        expected = stored_job.legacy.request(method, path)
        stored_job.record("missing" + suffix, actual, expected)
        assert actual.status_code == expected.status_code == 404
        assert actual.json() == expected.json()

    @pytest.mark.parametrize("suffix", [
        "/results?status=unknown", "/issues?error_code=unknown", "/issues?cursor=abc",
    ])
    def test_original_query_error_messages(self, stored_job: _StoredJob, suffix: str) -> None:
        """suffix 的原业务 ValueError 消息属于稳定协议；状态、detail 和枚举名逐字相同。"""
        path = "/v1/inference/configuration-jobs/" + stored_job.job_id + suffix
        actual, expected = stored_job.remote.get(path), stored_job.legacy.get(path)
        stored_job.record("invalid" + suffix, actual, expected)
        assert actual.status_code == expected.status_code == 422
        assert actual.json() == expected.json()

    @pytest.mark.parametrize("suffix", [
        "/results?limit=0", "/results?limit=501", "/results?offset=-1", "/results?limit=",
        "/issues?limit=501", "/issues?status=succeeded",
    ])
    def test_query_schema_boundaries(self, stored_job: _StoredJob, suffix: str) -> None:
        """suffix 违反原 schema 类型/范围；两端均422，框架生成的校验 detail 文案不冒称逐字兼容。"""
        path = "/v1/inference/configuration-jobs/" + stored_job.job_id + suffix
        actual, expected = stored_job.remote.get(path), stored_job.legacy.get(path)
        stored_job.record("schema" + suffix, actual, expected)
        assert actual.status_code == expected.status_code == 422
