"""小型真实固定战斗 benchmark；原 Python 与 C++ 对相同输入逐字段核对完整结果。"""

from __future__ import annotations

import argparse
import hashlib
import platform
import statistics
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pokeop.application.solver.graph_solver import BattleGraphSolveStatus
from pokeop.application.solver.models import StateGraphLimits
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.models.types import Type, TypeHelper
from tests.migration.benchmark_core_graph import TimingSamples
from tests.migration.test_core_damage import TypeEfficacySnapshot
from tests.migration.test_core_state import _StateOracle, _reference
from tests.migration.test_core_turn import FixedReply, Mode, TurnInput, _TurnCase, _TurnOracle


class FixedBattleBenchmark(BaseModel):
    """保留原始样本、精确校验与工作量边界，不能把微型场景结果外推到完整配置空间。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int = 1
    scenarios: tuple[str, ...]
    graph_nodes: tuple[int, ...]
    graph_edges: tuple[int, ...]
    repeats: int
    input_sha256: str
    runner_sha256: str
    python_version: str
    platform: str
    python: TimingSamples
    cpp_process: TimingSamples
    all_results_equal: bool
    scope: str


def benchmark_cases() -> tuple[tuple[str, _TurnCase], ...]:
    """无输入；返回五个完整可解的小型合成领域场景，不查询数据库或执行旧空间 benchmark。"""
    state = _reference()
    for side in BattleSide:
        battler = state.battler(side)
        move = replace(battler.spec.moves[0], max_pp=1)
        spec = replace(battler.spec, moves=(move,))
        slot = replace(battler.move_slots[0], max_pp=1, current_pp=1)
        state = state.with_battler(side, replace(battler, spec=spec, move_slots=(slot,), current_hp=1))
    tie = state.with_battler(BattleSide.DEFENDER, replace(state.defender, spec=replace(state.defender.spec,
        stats=replace(state.defender.spec.stats, speed=state.attacker.spec.stats.speed))))
    struggle, closed, inaccurate = state, state, tie
    for side in BattleSide:
        battler = state.battler(side)
        struggle = struggle.with_battler(side, battler.with_move_slot(replace(battler.move_slots[0], current_pp=0)))
        move = replace(battler.spec.moves[0], effect_identifier="fake_out", priority=3)
        closed = closed.with_battler(side, replace(battler, spec=replace(battler.spec, moves=(move,)), is_first_turn=False))
        current = inaccurate.battler(side)
        move = replace(current.spec.moves[0], accuracy=75)
        inaccurate = inaccurate.with_battler(side, replace(current, spec=replace(current.spec, moves=(move,))))
    limits = StateGraphLimits(max_nodes=64, max_edges=256, max_turns=16)
    return tuple((name, _TurnCase(value, Mode.FIXED, graph_limits=limits)) for name, value in (
        ("priority-knockout", state), ("speed-tie-knockout", tie), ("struggle-mutual-knockout", struggle),
        ("fake-out-closed-cycle", closed), ("accuracy-and-struggle", inaccurate)))


def run_benchmark(runner: Path, repeats: int) -> FixedBattleBenchmark:
    """对同一五场完整固定战斗采样，并在每次计时后核对全部图/事件/精确解。

    Args:
        runner: 实际 pbi_turn_vectors 原生程序，不调用 Python 代理。
        repeats: 正数采样次数，默认入口使用五次。

    Returns:
        可重放原始耗时与校验信息；截断、求解不完整或任一字段不同立即失败。
    """
    if repeats <= 0:
        raise ValueError("benchmark repeats must be greater than 0")
    scenarios = benchmark_cases()
    chart = tuple(TypeEfficacySnapshot(attacking=first, defending=second, percent=TypeHelper.get_type_efficacy(first, second)) for first in Type for second in Type)
    inputs = tuple(TurnInput(mode=case.mode, state=_StateOracle.snapshot(case.state), type_chart=chart,
        attacker_action=None, defender_action=None, attacker_policy=case.attacker_policy, defender_policy=case.defender_policy,
        observer=case.observer, graph_limits=case.graph_limits) for _, case in scenarios)
    encoded = "\n".join(value.model_dump_json() for value in inputs) + "\n"
    reference = tuple(_TurnOracle.expected(case) for _, case in scenarios)
    for result in reference:
        assert isinstance(result, FixedReply)
        assert result.solution.status is BattleGraphSolveStatus.SOLVED and not result.graph.truncations
    python_samples: list[float] = []
    cpp_samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        original = tuple(_TurnOracle.expected(case) for _, case in scenarios)
        python_samples.append(time.perf_counter() - started)
        assert original == reference
        started = time.perf_counter()
        process = subprocess.run([str(runner)], input=encoded, text=True, capture_output=True, check=True, timeout=90)
        cpp_samples.append(time.perf_counter() - started)
        actual = tuple(FixedReply.model_validate_json(line) for line in process.stdout.splitlines())
        assert actual == reference
    verified = tuple(value for value in reference if isinstance(value, FixedReply))
    return FixedBattleBenchmark(scenarios=tuple(name for name, _ in scenarios), graph_nodes=tuple(len(value.graph.nodes) for value in verified),
        graph_edges=tuple(len(value.graph.edges) for value in verified), repeats=repeats,
        input_sha256=hashlib.sha256(encoded.encode()).hexdigest(), runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
        python_version=platform.python_version(), platform=platform.platform(),
        python=TimingSamples(samples_seconds=tuple(python_samples), median_seconds=statistics.median(python_samples)),
        cpp_process=TimingSamples(samples_seconds=tuple(cpp_samples), median_seconds=statistics.median(cpp_samples)), all_results_equal=True,
        scope="Five bounded synthetic domain battles, complete turn -> strategy -> BFS/SCC -> exact solution. Python includes domain/result model projection; C++ includes process, JSON and IPC. Not pure function or configuration space performance.")


def main() -> None:
    """读取显式 runner/output，输出实际 benchmark JSON；只写调用方指定报告路径。"""
    parser = argparse.ArgumentParser(description="Benchmark verified complete fixed battles")
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run_benchmark(arguments.runner, arguments.repeats)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(result.model_dump_json(indent=2) + "\n")
    print(f"Fixed battle benchmark verified: {len(result.scenarios)} scenarios, {result.repeats} repeats")


if __name__ == "__main__":
    main()
