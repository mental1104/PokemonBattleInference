"""真实 Go HTTP/PG/Core 与原 FastAPI/同一 PG 的完整静态计算器差分。"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from enum import StrEnum

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pokeop.api.routers.calculator import router
from pokeop.api.schemas.calculator import CalculateDamageResponse
from pokeop.api.schemas.calculator_abilities import (
    BattleStatStagesInput,
    CalculateDamageWithAbilitiesRequest,
    CalculatorPokemonWithAbilityInput,
)
from pokeop.api.schemas.stat_configurations import StatConfigurationResponse
from pokeop.persistence.calculator import ability_repository, repository


class _DatabaseKind(StrEnum):
    """仅替代旧全局连接选择器的枚举；查询和业务逻辑仍使用真实 owning repository。"""

    POSTGRES = "postgres"


class _OracleDatabase:
    """把原 repository 的连接生命周期绑定到本次独占 PG，避免导入生产全局 DB runtime。"""

    def __init__(self, engine: Engine) -> None:
        """engine 是验收 runner 创建的独占数据库；本对象借用它，不负责释放。"""
        self.engine = engine

    @contextmanager
    def transaction(self, kind: _DatabaseKind) -> Iterator[Session]:
        """kind 必须是独占 PostgreSQL；yield 真实 Session，结束无条件关闭。"""
        assert kind is _DatabaseKind.POSTGRES
        with Session(self.engine) as session:
            yield session

    def runtime(
        self,
    ) -> tuple[
        type[_DatabaseKind],
        Callable[[_DatabaseKind], AbstractContextManager[Session]],
    ]:
        """返回旧连接端口需要的枚举和事务工厂；无内存资料或 SQL 结果替身。"""
        return _DatabaseKind, self.transaction


@pytest.fixture
def legacy_calculator(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """monkeypatch 只注入连接端口；yield 原 FastAPI router，所有资料仍来自 runner 的 PG。"""
    dsn = os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
    if not dsn:
        pytest.skip("PBI_TEST_GO_CALCULATOR_POSTGRES_URL is required")
    engine = create_engine(dsn)
    database = _OracleDatabase(engine)
    monkeypatch.setattr(repository, "_db_runtime", database.runtime)
    monkeypatch.setattr(ability_repository, "_db_runtime", database.runtime)
    app = FastAPI()
    app.include_router(router, prefix="/v1/calculator")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        engine.dispose()


@pytest.fixture
def go_calculator() -> Iterator[httpx.Client]:
    """yield runner 已启动的真实 Go HTTP 客户端；不在测试中创建容器或假服务。"""
    endpoint = os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    if not endpoint:
        pytest.skip("PBI_TEST_GO_CALCULATOR_URL is required")
    with httpx.Client(base_url=endpoint, timeout=35) as client:
        yield client


class TestGoCalculator:
    """围绕原公开计算端点检验完整字段、不可变快照、schema 与合法性边界。"""

    @pytest.mark.parametrize(
        ("attacker", "defender", "move_id", "special"),
        [
            ((212, "technician"), (242, "natural-cure"), 418, False),
            ((134, "water-absorb"), (248, "sand-stream"), 57, True),
            ((474, "adaptability"), (143, "thick-fat"), 161, True),
            ((373, "intimidate"), (464, "solid-rock"), 89, False),
        ],
    )
    @pytest.mark.parametrize("boosted", [False, True])
    def test_complete_differential(
        self,
        legacy_calculator: TestClient,
        go_calculator: httpx.Client,
        attacker: tuple[int, str],
        defender: tuple[int, str],
        move_id: int,
        special: bool,
        boosted: bool,
    ) -> None:
        """两客户端共享 PG；四种双方/招式 × 基线或道具/极端等级，完整响应无浮点容差比较。"""
        command = CalculateDamageWithAbilitiesRequest(
            attacker=CalculatorPokemonWithAbilityInput(
                pokemon_id=attacker[0],
                ability_identifier=attacker[1],
                level=100 if boosted else 50,
                stat_preset="max_spatk_plus" if special else "max_atk_plus",
                item_identifier=("生命寶珠" if special else "Choice Band") if boosted else None,
                stat_stages=BattleStatStagesInput(
                    attack=-6 if boosted else 0,
                    special_attack=6 if boosted else 0,
                    accuracy=-3 if boosted else 0,
                ),
            ),
            defender=CalculatorPokemonWithAbilityInput(
                pokemon_id=defender[0],
                ability_identifier=defender[1],
                stat_preset="max_hp_spdef_plus" if special else "max_hp_def_plus",
                item_identifier="eviolite" if boosted else None,
                stat_stages=BattleStatStagesInput(
                    defense=3 if boosted else 0,
                    special_defense=-3 if boosted else 0,
                ),
            ),
            move_id=move_id,
        )
        body = command.model_dump(mode="json")
        expected = legacy_calculator.post("/v1/calculator/damage", json=body)
        actual = go_calculator.post("/v1/calculator/damage", json=body)
        assert expected.status_code == 200, expected.text
        assert actual.status_code == 200, actual.text
        # 用 owning schema 校验两端完整 DTO 后逐字段相同，含 trace/reasons/null/中文 warning。
        assert CalculateDamageResponse.model_validate_json(actual.content) == (
            CalculateDamageResponse.model_validate_json(expected.content)
        )
        assert actual.json() == expected.json()

    def test_snapshot_survives_soft_delete(
        self, legacy_calculator: TestClient, go_calculator: httpx.Client
    ) -> None:
        """先经真实 API 保存含下降轴/非6V配置，再删除；冻结快照仍与旧引擎逐字段相同。"""
        created = go_calculator.post(
            "/v1/stat-configurations",
            json={
                "name": "快照 & <极端>",
                "nature_id": "modest",
                "evs": {"hp": 4, "attack": 0, "defense": 0, "special_attack": 252, "special_defense": 0, "speed": 252},
                "ivs": {"hp": 0, "attack": 1, "defense": 2, "special_attack": 3, "special_defense": 4, "speed": 5},
                "role": "both",
                "binding_kind": "global",
            },
        )
        assert created.status_code == 201, created.text
        configuration = StatConfigurationResponse.model_validate_json(created.content)
        snapshot = configuration.snapshot_profile_id
        deleted = go_calculator.delete("/v1/stat-configurations/" + configuration.key)
        assert deleted.status_code == 204, deleted.text
        command = CalculateDamageWithAbilitiesRequest(
            attacker=CalculatorPokemonWithAbilityInput(pokemon_id=134, ability_identifier="water-absorb", stat_preset=snapshot),
            defender=CalculatorPokemonWithAbilityInput(pokemon_id=248, ability_identifier="sand-stream", stat_preset="max_hp"),
            move_id=57,
        )
        body = command.model_dump(mode="json")
        expected = legacy_calculator.post("/v1/calculator/damage", json=body)
        actual = go_calculator.post("/v1/calculator/damage", json=body)
        assert expected.status_code == actual.status_code == 200, (expected.text, actual.text)
        assert CalculateDamageResponse.model_validate_json(actual.content) == (
            CalculateDamageResponse.model_validate_json(expected.content)
        )
        assert actual.json() == expected.json()

    @pytest.mark.parametrize(
        ("field", "value", "status"),
        [("ruleset_id", "missing", 400), ("move_id", 999999, 400), ("move_id", 57, 400)],
    )
    def test_original_business_rejections(
        self, legacy_calculator: TestClient, go_calculator: httpx.Client,
        field: str, value: str | int, status: int,
    ) -> None:
        """field/value 改变规则/招式归属；双方应返回相同 status 与原 detail，不能变成假成功。"""
        command = CalculateDamageWithAbilitiesRequest(
            attacker=CalculatorPokemonWithAbilityInput(pokemon_id=212, ability_identifier="technician", stat_preset="no_investment"),
            defender=CalculatorPokemonWithAbilityInput(pokemon_id=242, ability_identifier="natural-cure", stat_preset="no_investment"),
            move_id=418,
        )
        body = command.model_dump(mode="json")
        body[field] = value
        expected = legacy_calculator.post("/v1/calculator/damage", json=body)
        actual = go_calculator.post("/v1/calculator/damage", json=body)
        assert actual.status_code == expected.status_code == status, (expected.text, actual.text)
        assert actual.json() == expected.json()

    @pytest.mark.parametrize("ability", ["inner-focus", "multiscale"])
    def test_dynamic_ability_gap_is_explicit(
        self, legacy_calculator: TestClient, go_calculator: httpx.Client, ability: str
    ) -> None:
        """记录当前静态 Core 的实际边界：旧无动态钩子为200，新明确422，绝不宣称完整兼容。"""
        command = CalculateDamageWithAbilitiesRequest(
            attacker=CalculatorPokemonWithAbilityInput(pokemon_id=212, ability_identifier="technician", stat_preset="max_atk_plus"),
            defender=CalculatorPokemonWithAbilityInput(pokemon_id=149, ability_identifier=ability, stat_preset="max_hp_def_plus"),
            move_id=418,
        )
        body = command.model_dump(mode="json")
        expected = legacy_calculator.post("/v1/calculator/damage", json=body)
        actual = go_calculator.post("/v1/calculator/damage", json=body)
        assert expected.status_code == 200, expected.text
        assert actual.status_code == 422, actual.text
        assert actual.json()["error"]["code"] == "unsupported"
