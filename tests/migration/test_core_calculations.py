"""通过真实 C++ 进程比较冻结向量、Python 参考行为和精确分数，不依赖外部服务。"""

from __future__ import annotations

import os
import random
import subprocess
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.domain.battle.ko import estimate_ko_chance
from pokeop.domain.battle.stat_stage_math import apply_stat_stage
from pokeop.domain.battle.stats import calculate_hp_stat, calculate_non_hp_stat


class StatVector(BaseModel):
    """单项能力的共享输入与独立冻结结果；性格编码以十分制表达。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    operation: Literal["hp", "stat"]
    base: int
    iv: int
    ev: int
    level: int
    nature_tenths: Literal[9, 10, 11] = 10
    expected: int


class StageVector(BaseModel):
    """单项战斗能力等级输入及冻结结果，不涉及状态或知识查询。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    value: int
    stage: int
    expected: int


class KoVector(BaseModel):
    """保留重复伤害槽位权重及精确概率字符串的冻结击杀向量。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    rolls: tuple[int, ...]
    defender_hp: int
    ohko: str
    two_hit: str
    guaranteed_ohko: bool
    guaranteed_two_hit: bool


class CalculationVectors(BaseModel):
    """版本化共享文件边界；不允许未知字段被静默忽略。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1]
    stats: tuple[StatVector, ...]
    stages: tuple[StageVector, ...]
    ko: tuple[KoVector, ...]


@pytest.fixture(scope="module")
def core_runner() -> Path:
    """提供已构建的真实 C++ 向量入口，不启动编译或基础设施。

    Returns:
        runner 可执行路径。未配置且未构建时精确跳过；显式配置错误时失败。
    """
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    path = Path(configured) if configured else Path(__file__).resolve().parents[2] / "build/core/pbi_core_vectors"
    if not path.is_file() or not os.access(path, os.X_OK):
        if configured:
            pytest.fail("PBI_CORE_VECTOR_RUNNER must point to an executable core runner")
        pytest.skip("run make test-core or set PBI_CORE_VECTOR_RUNNER to enable C++ differential tests")
    return path


def run_vectors(runner: Path, lines: Sequence[str]) -> list[str]:
    """批量执行向量并检查逐行协议完整性。

    Args:
        runner: 已构建的 C++ 可执行入口，只读使用。
        lines: 每项一个空格分隔向量，不包含换行。

    Returns:
        与输入逐项对应的完整结果；进程错误、超时或行数不符直接使测试失败。
    """
    result = subprocess.run(
        [str(runner)], input="\n".join(lines) + "\n", text=True,
        capture_output=True, check=True, timeout=30,
    )
    outputs = result.stdout.splitlines()
    assert len(outputs) == len(lines)
    return outputs


class TestCoreCalculations:
    """围绕公开整数计算入口验证冻结合同、广域差分和错误路径。"""

    def test_shared_vectors(self, core_runner: Path) -> None:
        """core_runner 为真实 C++ 入口；冻结结果必须同时匹配 Python 与新 Core。"""
        vectors = CalculationVectors.model_validate_json(
            (Path(__file__).parents[1] / "vectors/calculations.v1.json").read_text()
        )
        lines: list[str] = []
        expected: list[str] = []
        for vector in vectors.stats:
            if vector.operation == "hp":
                result = calculate_hp_stat(base=vector.base, iv=vector.iv, ev=vector.ev, level=vector.level)
            else:
                result = calculate_non_hp_stat(base=vector.base, iv=vector.iv, ev=vector.ev, level=vector.level, nature_modifier=vector.nature_tenths / 10)
            assert result == vector.expected
            lines.append(f"{vector.operation} {vector.base} {vector.iv} {vector.ev} {vector.level}"
                         + (f" {vector.nature_tenths}" if vector.operation == "stat" else ""))
            expected.append(str(vector.expected))
        for vector in vectors.stages:
            assert apply_stat_stage(vector.value, vector.stage) == vector.expected
            lines.append(f"stage {vector.value} {vector.stage}")
            expected.append(str(vector.expected))
        for vector in vectors.ko:
            result = estimate_ko_chance(rolls=vector.rolls, defender_hp=vector.defender_hp)
            assert result.ohko_chance == pytest.approx(float(Fraction(vector.ohko)))
            assert result.two_hit_ko_chance == pytest.approx(float(Fraction(vector.two_hit)))
            assert result.guaranteed_ohko == vector.guaranteed_ohko
            assert result.guaranteed_2hko == vector.guaranteed_two_hit
            lines.append(f"ko {vector.defender_hp} " + " ".join(map(str, vector.rolls)))
            expected.append(f"{vector.ohko} {vector.two_hit} {int(vector.guaranteed_ohko)} {int(vector.guaranteed_two_hit)}")
        assert run_vectors(core_runner, lines) == expected

    def test_generated_stat_and_stage_differential(self, core_runner: Path) -> None:
        """core_runner 为真实 C++ 入口；固定种子覆盖 floor、EV 余数与全部能力等级。"""
        randomizer = random.Random(20261124)
        lines: list[str] = []
        expected: list[str] = []
        for _ in range(4096):
            base, iv, ev, level = randomizer.randint(1, 255), randomizer.randint(0, 31), randomizer.randint(0, 252), randomizer.randint(1, 100)
            nature = randomizer.choice((9, 10, 11))
            lines.extend((f"hp {base} {iv} {ev} {level}", f"stat {base} {iv} {ev} {level} {nature}"))
            expected.extend((str(calculate_hp_stat(base=base, iv=iv, ev=ev, level=level)),
                             str(calculate_non_hp_stat(base=base, iv=iv, ev=ev, level=level, nature_modifier=nature / 10))))
        for value in (1, 2, 73, 110, 137, 255, 999):
            for stage in range(-6, 7):
                lines.append(f"stage {value} {stage}")
                expected.append(str(apply_stat_stage(value, stage)))
        assert run_vectors(core_runner, lines) == expected

    def test_exact_ko_differential(self, core_runner: Path) -> None:
        """core_runner 为真实 C++ 入口；枚举有序对给出精确 oracle，同时核对旧 float 展示值。"""
        randomizer = random.Random(42)
        lines: list[str] = []
        expected: list[str] = []
        for count in (1, 2, 3, 7, 16, 31):
            for _ in range(24):
                rolls = tuple(randomizer.randint(-5, 300) for _ in range(count))
                hp = randomizer.randint(1, 600)
                ohko = Fraction(sum(damage >= hp for damage in rolls), count)
                two_hit = Fraction(sum(first + second >= hp for first in rolls for second in rolls), count * count)
                legacy = estimate_ko_chance(rolls=rolls, defender_hp=hp)
                assert legacy.ohko_chance == float(ohko)
                assert legacy.two_hit_ko_chance == float(two_hit)
                lines.append(f"ko {hp} " + " ".join(map(str, rolls)))
                expected.append(f"{ohko} {two_hit} {int(legacy.guaranteed_ohko)} {int(legacy.guaranteed_2hko)}")
        assert run_vectors(core_runner, lines) == expected

    def test_invalid_inputs_do_not_stop_following_vectors(self, core_runner: Path) -> None:
        """core_runner 为真实 C++ 入口；错误必须显式报告，后续合法计算仍可完成。"""
        outputs = run_vectors(core_runner, ["unknown", "stage 0 0", "stage 100 7", "ko 0 1", "ko 1", "stat 65 31 252 50 12", "hp 95 31 252 50"])
        assert all(output.startswith("ERROR ") for output in outputs[:-1])
        assert outputs[-1] == "202"
