"""旧Python任务的配置图经同PG重新求解，对照Go独立Core及共享图导航的完整响应。"""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from pokeop.api.routers import inference
from pokeop.api.routers._configuration_jobs import results
from pokeop.api.routers._configuration_jobs.dependencies import (
    inference_use_case,
    job_store,
)
from pokeop.api.schemas.battle_exploration import (
    ExploreBattleGraphRequest,
    StoredBattleInferenceJourneyResponse,
)
from pokeop.api.schemas.fixed_battle import FixedBattleSummaryRequest
from pokeop.application.configuration_space.one_on_one import (
    FixedPokemonConfiguration,
    OneOnOneActionPolicy,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
)
from pokeop.application.repositories.battle_inference_jobs import (
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.application.use_cases._battle_inference_worker.execution import (
    execute_prepared_battle_inference_case,
    persistent_result,
)
from pokeop.application.use_cases._battle_inference_worker.preparation import (
    RepositoryBackedBattleInferenceCasePreparer,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
)
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from pokeop.persistence.battle_inference.runtime_repository import (
    PostgresBattleInferenceJobStore,
)
from tests.migration.test_go_fixed_graph import _GraphClients, _GraphPair
from tests.migration.test_go_fixed_inference import _FixedClients, _Requests

pytest_plugins = ["tests.migration.test_go_fixed_inference"]


@dataclass(frozen=True)
class _CaseIdentity:
    """由原canonical/provider产生的任务和pair身份；不包含测试生成的概率或状态图。"""

    job_id: str
    pair_id: str
    attacker_id: str

    def path(self, *, pair: str | None = None) -> str:
        """pair省略时使用真实pair，否则只替换请求身份；完整canonical按URL路径字段编码。"""
        return f"/v1/inference/configuration-jobs/{quote(self.job_id, safe='')}/configurations/{quote(self.pair_id if pair is None else pair, safe='')}/graph"


@dataclass(frozen=True)
class _CaseGraphClients:
    """共享真实PG和独立HTTP，原执行器只负责产生合法历史成功结果，不代替任一被测重算。"""

    fixed: _FixedClients
    engine: Engine
    store: PostgresBattleInferenceJobStore
    created: list[str]

    def seed(self, request: FixedBattleSummaryRequest, *, succeeded: bool = False, defender_level: int | None = None) -> _CaseIdentity:
        """request转换原完整canonical并持久化；succeeded时实际运行原preparer/executor后保存其真实结果。

        defender_level只改变原canonical等级，原worker与本route均按攻击者规则等级准备双方。
        测试不填写猜测概率、图统计或Go私有definition；created只记录本fixture可清理的任务ID。
        """
        attacker, defender = request.attacker, request.defender
        command = OneOnOneMovePoolCommand(
            ruleset_id=request.ruleset_id, version_group_id=request.version_group_id,
            calculation_revision="battle-inference.summary-exploration.v2",
            attacker=PokemonMovePoolSelection(FixedPokemonConfiguration(attacker.pokemon_id, None, attacker.level,
                attacker.stat_profile_id, attacker.ability_identifier, attacker.item_identifier), tuple(attacker.move_ids)),
            defender=PokemonMovePoolSelection(FixedPokemonConfiguration(defender.pokemon_id, None,
                defender.level if defender_level is None else defender_level,
                defender.stat_profile_id, defender.ability_identifier, defender.item_identifier), tuple(defender.move_ids)),
            attacker_policy=OneOnOneActionPolicy.FIRST_LEGAL if request.attacker_policy == "first-legal" else OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION,
            defender_policy=OneOnOneActionPolicy.FIRST_LEGAL if request.defender_policy == "first-legal" else OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION,
        )
        definition = case_definition(next(command.iter_configurations()))
        spec = BattleInferenceExecutionSpec.from_command(command, max_nodes_per_pair=request.limits.max_nodes,
            max_edges_per_pair=request.limits.max_edges, max_turns=request.limits.max_turns)
        job_id, now = "legacy-case-graph-" + uuid4().hex, datetime.now(UTC)
        self.store.create_job_with_execution_spec(CreateBattleInferenceJob(job_id, command.ruleset_id,
            command.version_group_id, command.calculation_revision, (definition,)), spec, created_at=now)
        self.created.append(job_id)
        if succeeded:
            # 旧仓库领取和真正求解后落成功，不用任意概率标记一条假的已完成case。
            claimed = self.store.claim_next_job(lease_owner=job_id, now=now, lease_duration=timedelta(hours=1), calculation_revision=command.calculation_revision)
            assert claimed is not None and claimed.job_id == job_id
            case = self.store.claim_cases(job_id, lease_owner=job_id, now=now, lease_duration=timedelta(hours=1), limit=1, calculation_revision=command.calculation_revision)[0]
            prepared = RepositoryBackedBattleInferenceCasePreparer(inference_use_case()).prepare(self.store.get_job(job_id), case, spec)
            outcome = persistent_result(execute_prepared_battle_inference_case(prepared))
            assert outcome.status.value == "succeeded"
            self.fixed.report.joinpath(job_id + ".actual-seed-result.json").write_text(json.dumps(asdict(outcome), ensure_ascii=False, indent=2))
            self.store.record_case_result(job_id, definition.configuration_pair_id, outcome, lease_owner=job_id,
                completed_at=datetime.now(UTC), calculation_revision=command.calculation_revision)
        with self.engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM poke_runtime.go_job_definitions WHERE job_id=:id"), {"id": job_id}).scalar_one() == 0
        return _CaseIdentity(job_id, definition.configuration_pair_id, definition.attacker_configuration_id)

    def compare(self, identity: _CaseIdentity, label: str, status: int, *, pair: str | None = None) -> _GraphPair | None:
        """实际调用原route和Go/Core，status是明确预期；只有随机UUID/expiry归一，所有数学/事件原样比较。"""
        path = identity.path(pair=pair)
        before = datetime.now(UTC)
        expected, actual = self.fixed.original.post(path), self.fixed.remote.post(path)
        _GraphClients(self.fixed).record(label, path, expected, actual)
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        if status != 200:
            assert actual.content == expected.content if status == 500 else actual.json() == expected.json()
            return None
        left = StoredBattleInferenceJourneyResponse.model_validate_json(actual.content)
        right = StoredBattleInferenceJourneyResponse.model_validate_json(expected.content)
        for handle in (left.exploration, right.exploration):
            assert len(handle.graph_id) == 32 and int(handle.graph_id, 16) >= 0
            assert before + timedelta(minutes=14) < handle.expires_at < datetime.now(UTC) + timedelta(minutes=16)
        assert left.summary == right.summary
        assert left.exploration.model_copy(update={"graph_id": "opaque", "expires_at": before}) == right.exploration.model_copy(update={"graph_id": "opaque", "expires_at": before})
        # 模型检查之外仍比较完整原始DTO，避免Pydantic忽略未知字段而隐藏公开响应差异。
        actual_json, expected_json = actual.json(), expected.json()
        for response in (actual_json, expected_json):
            response["exploration"]["graph_id"] = "opaque"
            response["exploration"]["expires_at"] = "validated-expiry"
        assert actual_json == expected_json
        return _GraphPair(left.exploration.graph_id, right.exploration.graph_id, left.exploration.calculation_revision)

    def change_pair(self, identity: _CaseIdentity, replacement: str) -> _CaseIdentity:
        """只变更历史身份元数据以触发旧校验顺序；实际执行器产生的概率/结果字节完全不改。"""
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE poke_runtime.battle_inference_cases SET configuration_pair_id=:pair WHERE job_id=:id"), {"pair": replacement, "id": identity.job_id})
        return _CaseIdentity(identity.job_id, replacement, identity.attacker_id)


@pytest.fixture
def case_graph_clients(fixed_clients: _FixedClients) -> Iterator[_CaseGraphClients]:
    """原HTTP同PG挂结果route/真实store；唯一连接替换是fixture端口，不替换规则、repository或solver。"""
    engine = create_engine(os.environ["PBI_FIXED_INFERENCE_POSTGRES_URL"])
    store = PostgresBattleInferenceJobStore(transaction_factory=sessionmaker(engine).begin)
    app = cast(FastAPI, fixed_clients.original.app)
    app.state.battle_graph_store = InMemoryBattleGraphStore()
    app.include_router(results.router, prefix="/v1/inference")
    app.include_router(inference.router, prefix="/v1/inference")

    def dependency() -> PostgresBattleInferenceJobStore:
        """返回只连接当前自有PG的真实原store，保留原job/spec/case SQL与异常。"""
        return store

    app.dependency_overrides[job_store] = dependency
    clients = _CaseGraphClients(fixed_clients, engine, store, [])
    try:
        yield clients
    finally:
        with engine.begin() as connection:
            for job_id in clients.created:
                connection.execute(text("DELETE FROM poke_runtime.battle_inference_jobs WHERE job_id=:id"), {"id": job_id})
        engine.dispose()


class TestConfigurationCaseGraph:
    """原已有任务与当前知识重算全链；负向先检查原任务/规格/状态，不因strict新入口改变合同。"""

    @pytest.mark.parametrize("scenario", ("missing-job", "missing-spec", "missing-case", "side-id", "pending"))
    def test_original_lookup_order(self, case_graph_clients: _CaseGraphClients, scenario: str) -> None:
        """真实原表缺失与pending的精确404/409，side身份不能冒充pair，缺spec先于不存在case。"""
        identity = case_graph_clients.seed(_Requests.fixed())
        status, requested = 404, None
        if scenario == "missing-job":
            identity = _CaseIdentity("missing-'case-job", identity.pair_id, identity.attacker_id)
        elif scenario == "missing-spec":
            with case_graph_clients.engine.begin() as connection:
                connection.execute(text("DELETE FROM poke_runtime.battle_inference_job_execution_specs WHERE job_id=:id"), {"id": identity.job_id})
            requested = "also-missing-case"
        elif scenario == "missing-case":
            requested = "missing-case"
        elif scenario == "side-id":
            requested = identity.attacker_id
        else:
            status = 409
        case_graph_clients.compare(identity, "case-lookup-" + scenario, status, pair=requested)

    @pytest.mark.parametrize("scenario", ("baseline", "unequal-levels", "null-turns", "larger-budget"))
    def test_full_graph_from_real_legacy_success(self, case_graph_clients: _CaseGraphClients, scenario: str) -> None:
        """真实原worker成功记录无Go definition；双方重算summary/代表事件路径/SCC/统计及后续root导航完全相同。"""
        request = _Requests.fixed() if scenario in ("baseline", "unequal-levels") else _Requests.fixed(52, "technician", (252,))
        identity = case_graph_clients.seed(request, succeeded=True, defender_level=77 if scenario == "unequal-levels" else None)
        if scenario in ("null-turns", "larger-budget"):
            with case_graph_clients.engine.begin() as connection:
                if scenario == "null-turns":
                    connection.execute(text("UPDATE poke_runtime.battle_inference_job_execution_specs SET max_turns=NULL WHERE job_id=:id"), {"id": identity.job_id})
                else:
                    connection.execute(text("UPDATE poke_runtime.battle_inference_job_execution_specs SET max_nodes_per_pair=500001,max_edges_per_pair=2000001,max_turns=201 WHERE job_id=:id"), {"id": identity.job_id})
        pair = case_graph_clients.compare(identity, "case-success-" + scenario, 200)
        assert pair is not None
        _GraphClients(case_graph_clients.fixed).query(pair, "explore", ExploreBattleGraphRequest(calculation_revision=pair.revision), "case-explore-" + scenario)
        body = json.loads(case_graph_clients.fixed.report.joinpath("case-success-" + scenario + ".go.json").read_text())
        if scenario in ("baseline", "unequal-levels"):
            assert body["summary"]["graph"]["unique_state_count"] == 841
            assert body["summary"]["graph"]["edge_count"] == 16095

    @pytest.mark.parametrize("scenario", ("explicit-attacker-form", "explicit-defender-form", "malformed-canonical"))
    def test_original_historical_identity_rejections(self, case_graph_clients: _CaseGraphClients, scenario: str) -> None:
        """先真正执行小图，再只损坏历史身份元数据；拒绝发生在重新求解前，未造历史Core结果。"""
        identity = case_graph_clients.seed(_Requests.fixed(52, "technician", (252,)), succeeded=True)
        if scenario == "malformed-canonical":
            replacement, status = "invalid-canonical-case", 500
        else:
            prefix = "one-on-one-configuration:"
            payload = json.loads(identity.pair_id[len(prefix):])
            payload[4 if scenario == "explicit-attacker-form" else 5][1] = 1
            replacement, status = prefix + json.dumps(payload, separators=(",", ":")), 422
        identity = case_graph_clients.change_pair(identity, replacement)
        case_graph_clients.compare(identity, "case-identity-" + scenario, status)

    @pytest.mark.parametrize("scenario", ("unknown-profile", "unknown-item", "unknown-move", "unknown-ability", "missing-pokemon", "missing-version", "missing-ruleset", "partial-ability"))
    def test_reprepare_uses_current_reference_boundary(self, case_graph_clients: _CaseGraphClients, scenario: str) -> None:
        """只改真实历史身份/规则元数据后重读当前PG，保原reference维度筛选与原422/未捕获500边界。

        这些历史变更不改先前真实求解的结果字节；本route不会把先前概率当作新的计算结果。
        """
        identity = case_graph_clients.seed(_Requests.fixed(52, "technician", (252,)), succeeded=True)
        prefix = "one-on-one-configuration:"
        payload = json.loads(identity.pair_id[len(prefix):])
        status = 422
        if scenario == "unknown-profile":
            payload[4][3] = "unknown-historical-profile"
        elif scenario == "unknown-item":
            payload[4][5] = "unknown-historical-item"
        elif scenario == "unknown-move":
            payload[4][6] = [999999]
        elif scenario == "unknown-ability":
            payload[4][4] = "unknown-historical-ability"
        elif scenario == "partial-ability":
            payload[5][4] = "inner-focus"
        elif scenario == "missing-pokemon":
            payload[4][0] = 999999
            status = 500
        else:
            status = 500
            with case_graph_clients.engine.begin() as connection:
                if scenario == "missing-version":
                    connection.execute(text("UPDATE poke_runtime.battle_inference_jobs SET version_group_id=999999 WHERE job_id=:id"), {"id": identity.job_id})
                else:
                    connection.execute(text("UPDATE poke_runtime.battle_inference_jobs SET ruleset_id='unknown-historical-ruleset' WHERE job_id=:id"), {"id": identity.job_id})
        identity = case_graph_clients.change_pair(identity, prefix + json.dumps(payload, separators=(",", ":")))
        pair = case_graph_clients.compare(identity, "case-current-reference-" + scenario, status)
        if pair is not None:
            _GraphClients(case_graph_clients.fixed).query(pair, "explore", ExploreBattleGraphRequest(calculation_revision=pair.revision), "case-reference-explore-" + scenario)
