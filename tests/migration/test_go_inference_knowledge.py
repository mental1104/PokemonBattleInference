"""将真实 Go repository 的完整知识产物与原 Python repository 同 PG 逐字段比较。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from pokeop.application.repositories.battle_inference import (
    BattleInferenceItemProfile,
    BattleInferencePokemonProfile,
    BattleInferenceRulesetContext,
)
from pokeop.persistence.battle_inference import repository


class _Kind(StrEnum):
    """只为原连接端口提供有限值；不模拟查询或持久化。"""

    POSTGRES = "postgres"


class _ReadRuntime:
    """把原 repository 的无参全局连接选择端口指向显式独占 PG。"""

    def __init__(self, engine: Engine) -> None:
        """engine 是 runner 创建的临时库连接池；本对象借用，不释放它。"""
        self.engine = engine

    def transaction(self, kind: _Kind) -> Connection:
        """kind 必须为 PostgreSQL；返回真实连接 context manager，退出关闭并回滚只读查询事务。"""
        assert kind is _Kind.POSTGRES
        return self.engine.connect()

    def runtime(self) -> tuple[type[_Kind], Callable[[_Kind], AbstractContextManager[Connection]]]:
        """返回旧 repository 需要的连接端口；不提供任何内存查询结果。"""
        return _Kind, self.transaction


class TestGoInferenceKnowledge:
    """完整投影保持原 version-aware 合法性和全部 conservative capability，尚不冒称任务创建。"""

    def test_all_fields_from_same_postgres(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """monkeypatch 只替换连接选择；比较七只完整 profile/全部招式/特性/六道具及规则轴。"""
        dsn = os.environ.get("PBI_TEST_GO_CALCULATOR_POSTGRES_URL")
        output = os.environ.get("PBI_TEST_INFERENCE_SNAPSHOT_OUTPUT")
        if not dsn or not output:
            pytest.skip("explicit inference PostgreSQL and Go snapshot output are required")
        actual = json.loads(Path(output).read_text())
        engine = create_engine(dsn)
        runtime = _ReadRuntime(engine)
        monkeypatch.setattr(repository, "_db_runtime", runtime.runtime)
        original = repository.MaterializedViewBattleInferenceRepository()
        try:
            rules = original.get_ruleset_context(ruleset_id="pokemon-champion", version_group_id=25)
            assert actual["ruleset"] == TypeAdapter(BattleInferenceRulesetContext).dump_python(rules, mode="json")
            pokemon_adapter = TypeAdapter(BattleInferencePokemonProfile)
            for pokemon in actual["pokemon"]:
                expected = original.get_pokemon_profile(
                    ruleset_id="pokemon-champion", version_group_id=25, pokemon_id=pokemon["pokemon_id"]
                )
                assert expected is not None
                # Go 保留同一 type_id，未再输出 Python 内部冗余 domain_type Enum；其余每个字段严格相同。
                projected = pokemon_adapter.dump_python(
                    expected, mode="json",
                    exclude={"types": {"__all__": {"domain_type"}}, "moves": {"__all__": {"type": {"domain_type"}}}},
                )
                assert pokemon == projected
            items = original.list_item_candidates(ruleset_id="pokemon-champion", version_group_id=25)
            assert actual["items"] == TypeAdapter(tuple[BattleInferenceItemProfile, ...]).dump_python(items, mode="json")
        finally:
            engine.dispose()
