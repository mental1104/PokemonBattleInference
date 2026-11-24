"""整组能力与性格轴的真实 C ABI 差分，预期使用既有 NATURES 与 calculate_actual_stats。"""
from __future__ import annotations
import random
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict
from pokeop.domain.battle.stats import StatProfile, StatValues, calculate_actual_stats
from pokeop.domain.configuration_presets import NATURES
from tests.migration.test_core_damage import damage_runner


class ProfileInput(BaseModel):
    """完整 profile 请求合同，不在进程适配器中重算性格倍率。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["profile"] = "profile"
    base: StatValues
    ivs: StatValues
    evs: StatValues
    level: int
    decreased_stat_id: int
    increased_stat_id: int


class ProfileBatch(BaseModel):
    """有界批次，使用正式 ABI 并逐项核对完整六项能力。"""
    schema_version: Literal[1] = 1
    operations: tuple[ProfileInput, ...]


class ProfileResult(BaseModel):
    """完整结果边界，缺失任一能力不允许伪通过。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["profile"]
    stats: StatValues


class ProfileReply(BaseModel):
    """固定版本与完整结果，不能把 error 当成空列表。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1]
    engine_version: Literal["0.7.0"]
    rules_version: Literal["calculation-rules.v7"]
    results: tuple[ProfileResult, ...]


class TestCoreProfile:
    """源性格全部覆盖，保留 Python 整组能力与 C++ 精确公式行为。"""
    def test_all_natures_and_full_stat_profiles(self, damage_runner: Path) -> None:
        """damage_runner 为已构建目录；比较 25 性格×64 配置的全部 9600 能力字段。"""
        pack = Path(__file__).parents[2] / "ios/Sources/PokemonAppSupport/Resources/knowledge.sqlite"
        with closing(sqlite3.connect(pack.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            natures = connection.execute("SELECT identifier,decreased_stat_id,increased_stat_id FROM natures ORDER BY id").fetchall()
        assert len(natures) == 25
        randomizer = random.Random(28)
        operations: list[ProfileInput] = []
        expected: list[StatValues] = []
        for identifier, decreased, increased in natures:
            for _ in range(64):
                base = StatValues(*(randomizer.randint(1, 255) for _ in range(6)))
                ivs = StatValues(*(randomizer.randint(0, 31) for _ in range(6)))
                evs = StatValues(*(randomizer.randint(0, 252) for _ in range(6)))
                level = randomizer.randint(1, 100)
                operations.append(ProfileInput(base=base, ivs=ivs, evs=evs, level=level, decreased_stat_id=decreased, increased_stat_id=increased))
                expected.append(calculate_actual_stats(StatProfile(base, evs, ivs, NATURES[identifier].modifier()), level=level))
        batches = tuple(ProfileBatch(operations=tuple(operations[index:index + 100])) for index in range(0, len(operations), 100))
        result = subprocess.run([str(damage_runner.parent / "pbi_abi_vectors")], input="\n".join(batch.model_dump_json() for batch in batches) + "\n",
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines(); assert len(lines) == len(batches)
        actual = [value.stats for line in lines for value in ProfileReply.model_validate_json(line).results]
        assert actual == expected
