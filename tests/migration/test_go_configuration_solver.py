"""原模板/EV/IV WithSpeed HTTP在真实Go/Core与原FastAPI同PG的完整响应差分。"""

from __future__ import annotations

import base64
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

from pokeop.api.routers.configuration_solver import router
from pokeop.api.schemas.configuration_solver_with_speed import (
    SolveConfigurationWithSpeedRequest, SearchConfigurationSpreadsWithSpeedRequest, ConfigurationSpeedGoalRequest,
)
from pokeop.api.schemas.configuration_solver import ConfigurationGoalRequest
from pokeop.persistence.calculator import repository, ability_repository
from tests.migration.test_go_calculator import _OracleDatabase


@dataclass(frozen=True)
class _SolverClients:
    """借用独立HTTP客户端和原router；report保存每个真实输入和完整双端响应。"""

    remote: httpx.Client
    legacy: TestClient
    report: Path

    def compare(self, body: dict[str, object], search: bool, label: str, status: int = 200) -> None:
        """body是唯一原公开JSON请求，search选择原路由；全部字段比较，失败不取部分候选冒充成功。"""
        suffix = "search-spreads" if search else "solve"
        path = "/v1/configuration_solver/" + suffix
        actual = self.remote.post(path, json=body)
        expected = self.legacy.post(path, json=body)
        prefix = self.report / (suffix + "-" + label)
        prefix.with_suffix(".request.json").write_text(json.dumps(body, ensure_ascii=False, indent=2))
        prefix.with_suffix(".go.json").write_bytes(actual.content)
        prefix.with_suffix(".python.json").write_bytes(expected.content)
        assert actual.status_code == expected.status_code == status, (actual.text, expected.text)
        assert actual.json() == expected.json()


@pytest.fixture
def solver_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SolverClients]:
    """只替换拥有者的连接生命周期；原SQL/模板/速度/二分/展示全部真实执行。"""
    dsn = os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
    endpoint = os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    if not dsn or not endpoint:
        pytest.skip("explicit isolated PostgreSQL and Go HTTP endpoint are required")
    engine = create_engine(dsn)
    database = _OracleDatabase(engine)
    monkeypatch.setattr(repository, "_db_runtime", database.runtime)
    monkeypatch.setattr(ability_repository, "_db_runtime", database.runtime)
    app = FastAPI()
    app.include_router(router, prefix="/v1/configuration_solver")
    try:
        with TestClient(app) as legacy, httpx.Client(base_url=endpoint, timeout=35) as remote:
            yield _SolverClients(remote, legacy, Path(os.environ["PBI_SOLVER_REPORT"]))
    finally:
        engine.dispose()


class TestOriginalConfigurationSolver:
    """按原调用者的伤害/速度/自定义配置与错误域组织，完全复用原HTTP模型作为输入事实源。"""

    @pytest.mark.parametrize("search", [False, True], ids=["templates", "ev-iv-search"])
    @pytest.mark.parametrize("scenario", ["attack", "defense", "mixed", "speed-only", "damage-speed", "snapshot", "unimplemented-ability", "inner-focus"])
    def test_full_results(self, solver_clients: _SolverClients, search: bool, scenario: str) -> None:
        """验证所有候选/首失败/安全区间/性格选项/中文warnings，不用单伤害结果替代完整反推。"""
        damage = ConfigurationGoalRequest.model_validate({"goal_id": "attack", "kind": "attack", "target_pokemon_id": 149, "move_id": 404, "target_ability_identifier": "multiscale", "target_stat_preset": "max_hp_def_plus", "required_turns": 2})
        defense = ConfigurationGoalRequest.model_validate({"goal_id": "defense", "kind": "defense", "target_pokemon_id": 149, "move_id": 337, "target_ability_identifier": "inner-focus", "target_stat_preset": "max_atk_plus", "required_turns": 2})
        speed = ConfigurationSpeedGoalRequest(goal_id="speed",target_pokemon_id=149,target_stat_preset="no_investment")
        body = SolveConfigurationWithSpeedRequest(subject_pokemon_id=212,subject_ability_identifier="technician",goals=[damage],max_candidates=3)
        if scenario == "defense":
            body.goals = [defense]
        elif scenario == "mixed":
            body.goals = [damage, defense]
        elif scenario == "speed-only":
            body.goals, body.speed_goals = [], [speed]
        elif scenario == "damage-speed":
            body.speed_goals = [speed]
        elif scenario == "snapshot":
            fields = ("hp", "attack", "defense", "special_attack", "special_defense", "speed")
            snapshot = "preset-snapshot:" + base64.urlsafe_b64encode(json.dumps({"nature_id": "adamant", "label": "原配置 & 快照", "evs": dict(zip(fields, [252, 252, 0, 0, 0, 0])), "ivs": dict(zip(fields, [31, 31, 30, 29, 28, 27]))}).encode()).decode().rstrip("=")
            body.allowed_stat_presets = ["max_hp_def_plus", snapshot, "max_atk_plus", snapshot]
            damage.target_stat_preset = snapshot
        elif scenario == "unimplemented-ability":
            body.subject_pokemon_id, body.subject_ability_identifier, body.subject_item_identifier = 461, "pressure", "life-orb"
            damage.move_id, damage.required_turns = 8, 1
        elif scenario == "inner-focus":
            body.subject_pokemon_id, body.subject_ability_identifier, body.level = 149, "inner-focus", 100
            damage.target_pokemon_id, damage.target_ability_identifier, damage.move_id, damage.required_turns = 212, "technician", 337, 1
        model = SearchConfigurationSpreadsWithSpeedRequest if search else SolveConfigurationWithSpeedRequest
        validated = model.model_validate(body.model_dump(mode="json"))
        solver_clients.compare(validated.model_dump(mode="json"), search, scenario)

    @pytest.mark.parametrize("search", [False, True], ids=["templates", "ev-iv-search"])
    @pytest.mark.parametrize("scenario", ["empty", "missing-subject", "bad-ability", "bad-item", "unknown-move", "duplicate-id", "unknown-ruleset"])
    def test_business_errors(self, solver_clients: _SolverClients, search: bool, scenario: str) -> None:
        """原业务错误必须完整400且不返回候选；这些输入仍通过原HTTP字段类型/范围校验。"""
        body = SolveConfigurationWithSpeedRequest.model_validate({"subject_pokemon_id": 212, "subject_ability_identifier": "technician", "goals": [{"goal_id": "goal", "kind": "attack", "target_pokemon_id": 149, "move_id": 404, "target_ability_identifier": "multiscale"}]})
        if scenario == "empty":
            body.goals = []
        elif scenario == "missing-subject":
            body.subject_pokemon_id = 999999
        elif scenario == "bad-ability":
            body.subject_ability_identifier = "multiscale"
        elif scenario == "bad-item":
            body.subject_item_identifier = "unknown-item"
        elif scenario == "unknown-move":
            body.goals[0].move_id = 999999
        elif scenario == "duplicate-id":
            body.speed_goals = [ConfigurationSpeedGoalRequest(goal_id="goal",target_pokemon_id=149,target_stat_preset="no_investment")]
        else:
            body.ruleset_id = "unknown"
        solver_clients.compare(body.model_dump(mode="json"), search, scenario, 400)

    @pytest.mark.parametrize("search", [False, True], ids=["templates", "ev-iv-search"])
    def test_transport_defaults_and_ignored_extra(self, solver_clients: _SolverClients, search: bool) -> None:
        """真实客户端省略level/候选数/目标默认字段；额外字段沿原BaseModel忽略，不改变搜索空间。"""
        body: dict[str,object] = {"subject_pokemon_id":212,"subject_ability_identifier":"technician","goals":[{"goal_id":"def","kind":"defense","target_pokemon_id":149,"move_id":337,"target_ability_identifier":"multiscale"}],"ignored_extra":{"nullable":None}}
        if search:
            body["allowed_stat_presets"] = {"ignored-by-original-search":None}
        solver_clients.compare(body,search,"transport-defaults")

    @pytest.mark.parametrize("search", [False, True], ids=["templates", "ev-iv-search"])
    @pytest.mark.parametrize("field", ["level","max_candidates","goals","speed_goals"])
    def test_nonnullable_fields(self, solver_clients: _SolverClients, search: bool, field: str) -> None:
        """原HTTP非nullable字段不能把显式null冒用为省略默认；框架detail只比较原422分类。"""
        body = SolveConfigurationWithSpeedRequest.model_validate({"subject_pokemon_id":212,"subject_ability_identifier":"technician","speed_goals":[{"goal_id":"speed","target_pokemon_id":149,"target_stat_preset":"no_investment"}]}).model_dump(mode="json")
        body[field] = None
        route = "/v1/configuration_solver/" + ("search-spreads" if search else "solve")
        actual,expected = solver_clients.remote.post(route,json=body),solver_clients.legacy.post(route,json=body)
        assert actual.status_code == expected.status_code == 422, (actual.text,expected.text)
