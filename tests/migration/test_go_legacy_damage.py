"""修复原缺失director后，旧真实责任链与Go旧damage HTTP的确定字段/随机支持集验收。"""

from __future__ import annotations

import contextlib
import io
import json
import os
import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from pokeop.api.routers import damage
from pokeop.api.schemas.damage import DamageRequest, DamageResponse
from pokeop.domain.models.nature import Nature
from pokeop.domain.models.move import MoveType
from pokeop.domain.models.pokemon import PokemonEntity
from pokeop.domain.models.types import type_efficacy
from tests.migration.test_core_legacy_damage import _Pokemon


class _RawPokemon(BaseModel):
    """真实raw SQL返回的固定基础事实，进入历史构造前完成完整schema解析。"""

    base: tuple[int, ...] = Field(min_length=6,max_length=6)
    types: tuple[int, ...] = Field(min_length=1,max_length=2)


class _HistoricalDirector:
    """仅恢复6e4dc6f^已删除constructor的资料/实体组装；能力与伤害仍执行原拥有者实现。"""

    def __init__(self, engine: Engine) -> None:
        """借用验收自有PG engine；不关闭共享engine，不缓存或伪造原基础事实。"""
        self.engine = engine

    def construct_from_database(self, id: int, level: int | None = 100, basepoint: list[int] | None = None, nature: Nature | None = Nature.JOLLY) -> PokemonEntity:
        """参数对应原router实际传入值；实际IV固定31，原AbilityFactory负责全部历史数值构造。"""
        with self.engine.connect() as connection:
            body = connection.execute(text("SELECT jsonb_build_object('base',(SELECT jsonb_agg(s.base_stat ORDER BY s.stat_id) FROM poke_raw.pokemon_stats s WHERE s.pokemon_id=p.id AND s.stat_id BETWEEN 1 AND 6),'types',(SELECT jsonb_agg(t.type_id ORDER BY t.slot) FROM poke_raw.pokemon_types t WHERE t.pokemon_id=p.id)) FROM poke_raw.pokemon p WHERE p.id=:id"), {"id":id}).scalar_one_or_none()
        if body is None:
            raise ValueError(f"Pokemon with id {id} not found.")
        raw = _RawPokemon.model_validate(body)
        if basepoint is None or level is None:
            raise TypeError("legacy level and basepoint must not be null")
        return _Pokemon(level=level,base=raw.base,basepoint=tuple(basepoint),nature=nature,types=raw.types).entity()


@dataclass(frozen=True)
class _LegacyClients:
    """独立Go HTTP与修复前/仅恢复历史constructor的原HTTP；report保存完整原始请求与双端响应。"""

    remote: httpx.Client
    legacy: TestClient
    report: Path

    def compare(self, request: DamageRequest, label: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Go产生真实随机值；确定字段逐字相同，随机值/百分比必须落在原全部两位随机档支持集。"""
        body = request.model_dump(mode="json")
        actual = self.remote.post("/v1/damage",json=body)
        assert actual.status_code==200,actual.text
        expected = None
        possible = set()
        for index in range(101):
            unit=index/100
            # 只注入原始unit；原random.uniform/round/责任链都真实执行，不在测试重新计算伤害。
            monkeypatch.setattr(random._inst,"random",lambda:unit)
            with contextlib.redirect_stdout(io.StringIO()):
                response=self.legacy.post("/v1/damage",json=body)
            assert response.status_code==200,response.text
            candidate=DamageResponse.model_validate_json(response.content)
            possible.add((candidate.random_damage,candidate.random_damage_percent))
            if index==50:
                expected=response
        assert expected is not None
        new,old=actual.json(),expected.json()
        assert set(new)==set(old)==set(DamageResponse.model_fields)
        chosen=(new.pop("random_damage"),new.pop("random_damage_percent"))
        old.pop("random_damage");old.pop("random_damage_percent")
        assert new==old,(new,old)
        assert chosen in possible,(chosen,possible)
        (self.report/f"{label}.request.json").write_text(json.dumps(body,ensure_ascii=False,indent=2))
        (self.report/f"{label}.go.json").write_bytes(actual.content)
        (self.report/f"{label}.restored-python.json").write_bytes(expected.content)
        (self.report/f"{label}.random-support.json").write_text(json.dumps(sorted(possible)))


@pytest.fixture
def legacy_clients(monkeypatch: pytest.MonkeyPatch) -> Iterator[_LegacyClients]:
    """先证明原router NameError，再仅恢复历史constructor；真正PG/static324知识和旧数学不替换。"""
    endpoint=os.environ.get("PBI_TEST_GO_CALCULATOR_URL")
    dsn=os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
    if not endpoint or not dsn:
        pytest.skip("explicit isolated PostgreSQL and Go HTTP endpoint are required")
    engine=create_engine(dsn)
    app=FastAPI();app.include_router(damage.router,prefix="/v1/damage")
    report=Path(os.environ["PBI_LEGACY_HTTP_REPORT"])
    probe=DamageRequest.model_validate({"attacker":{"id":149},"defenser":{"id":212}}).model_dump(mode="json")
    original=TestClient(app,raise_server_exceptions=False).post("/v1/damage",json=probe)
    assert original.status_code==500,original.text
    with engine.connect() as connection:
        factors=connection.execute(text("SELECT damage_type_id,target_type_id,damage_factor FROM poke_raw.type_efficacy WHERE damage_type_id BETWEEN 1 AND 18 AND target_type_id BETWEEN 1 AND 18 ORDER BY damage_type_id,target_type_id")).all()
    assert [tuple(row) for row in factors]==[(a,d,type_efficacy[a][d]) for a in range(1,19) for d in range(1,19)]
    # 原缺失类的唯一恢复点；SQL与owning AbilityFactory/责任链完全真实，明确不是原故障HTTP等价声明。
    monkeypatch.setattr(damage,"PokemonDirector",lambda:_HistoricalDirector(engine),raising=False)
    try:
        with TestClient(app) as reference,httpx.Client(base_url=endpoint,timeout=35) as remote:
            yield _LegacyClients(remote,reference,report)
    finally:
        engine.dispose()


class TestLegacyDamageHTTP:
    """原NameError故障修复后的旧算法验收；随机结果比较支持集，不伪称逐次随机采样相同。"""

    @pytest.mark.parametrize("scenario",["historical-example","quiet-fractional-ev","special","negative-power","status","immunity","large-extra-ev","nullable-nature","defaults","ignored-ivs"])
    def test_old_algorithm(self,legacy_clients:_LegacyClients,monkeypatch:pytest.MonkeyPatch,scenario:str) -> None:
        """覆盖Champion范围外全Pokedex、旧构造怪异边界、随机结果及全部七字段，不能替换成现代链。"""
        request=DamageRequest.model_validate({"attacker":{"id":10021,"level":100,"basepoint":[0,252,0,0,0,252],"nature":"Adamant"},"defenser":{"id":598,"level":100,"basepoint":[252,0,252,0,0,0],"nature":"Impish"},"move":{"power":100,"type":"Ground","move_type":"physical_move"}})
        if scenario=="quiet-fractional-ev":
            request.attacker.id,request.defenser.id=149,212
            request.attacker.level=request.defenser.level=53
            request.attacker.basepoint=[2]*6
            request.attacker.nature=Nature.QUIET
            request.defenser.nature=None
            request.move.move_type=MoveType.special_move
        elif scenario=="special":
            request.attacker.id,request.defenser.id=6,9
            request.attacker.level=request.defenser.level=50
            request.attacker.basepoint=request.defenser.basepoint=[4,0,0,252,0,252]
            request.attacker.nature=Nature.TIMID;request.defenser.nature=Nature.MODEST
            request.move.power=90;request.move.type="Fire";request.move.move_type=MoveType.special_move
        elif scenario=="negative-power":
            request.move.power=-20
        elif scenario=="status":
            request.move.move_type=MoveType.status_move
        elif scenario=="immunity":
            request.attacker.id,request.defenser.id=128,94
            request.move.type="Normal"
        elif scenario=="large-extra-ev":
            request.attacker.basepoint=[999,2**60+7,5,11,0,9,44444]
        elif scenario=="nullable-nature":
            request.attacker.nature=request.defenser.nature=None
        elif scenario=="defaults":
            request=DamageRequest.model_validate({"attacker":{"id":212},"defenser":{"id":149}})
        elif scenario=="ignored-ivs":
            request.attacker.individual_values=[0]
            request.defenser.individual_values=None
        legacy_clients.compare(request,scenario,monkeypatch)

    @pytest.mark.parametrize("name",["Unknown","Stellar"," Normal"])
    def test_unrecognized_type_is_not_normalized(self,legacy_clients:_LegacyClients,name:str) -> None:
        """原Type没有UNKNOWN枚举且不strip；保留原明确ValueError含义，不把0行或新类型映普通。

        新HTTP修复原未捕获异常为400，单独验证分类和原消息，不宣称旧故障状态相同。
        """
        body=DamageRequest.model_validate({"attacker":{"id":149},"defenser":{"id":212},"move":{"type":name}}).model_dump(mode="json")
        with pytest.raises(ValueError) as failure:
            legacy_clients.legacy.post("/v1/damage",json=body)
        actual=legacy_clients.remote.post("/v1/damage",json=body)
        assert actual.status_code==400,actual.text
        assert actual.json()=={"detail":str(failure.value)}

    @pytest.mark.parametrize("field",["attacker","defenser","move","move.power","move.type","attacker.id"])
    def test_schema_nulls(self,legacy_clients:_LegacyClients,field:str) -> None:
        """原非nullable字段显式null保持422；不把null冒用为原省略默认，框架文案不作逐字等价声明。"""
        body=DamageRequest.model_validate({"attacker":{"id":149},"defenser":{"id":212}}).model_dump(mode="json")
        if "." in field:
            parent,name=field.split(".")
            body[parent][name]=None
        else:
            body[field]=None
        actual=legacy_clients.remote.post("/v1/damage",json=body)
        expected=legacy_clients.legacy.post("/v1/damage",json=body)
        assert actual.status_code==expected.status_code==422,(actual.text,expected.text)
