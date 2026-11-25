"""构建并求解单个配置对，同时释放完整状态图。"""

from __future__ import annotations

import os
import pickle
import sys
import time
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

try:
    import resource
except ImportError:  # pragma: no cover - Windows 没有 resource 模块。
    resource = None  # type: ignore[assignment]

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveStatus,
    ExpectedTurnsStatus,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.stream_configuration_pairs.executor import (
    _effects,
    _initial_state,
    _policy,
)
from pokeop.benchmarks.models import BenchmarkCaseInput, BenchmarkPairSample
from pokeop.domain.battle.action_policy import ActionPolicy
from pokeop.domain.battle.actions import BattleAction
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.structured_turn_resolver import (
    BattleEventStandardMoveTurnResolver,
)
from pokeop.domain.battle.transitions import WeightedTransition, merge_equivalent_transitions


@dataclass(slots=True)
class _InstrumentedPolicyDrivenExpander:
    """复用真实行动与回合语义，同时统计归并前后转移数量。

    Args:
        turn_resolver: 生产路径使用的完整回合 resolver。
        attacker_policy: 攻击方类型化行动策略。
        defender_policy: 防守方类型化行动策略。
        raw_transition_count: 当前图全部状态累计原始随机转移数量。
        merged_transition_count: 当前图全部状态累计归并后转移数量。
    """

    turn_resolver: BattleEventStandardMoveTurnResolver
    attacker_policy: ActionPolicy[BattleAction]
    defender_policy: ActionPolicy[BattleAction]
    raw_transition_count: int = 0
    merged_transition_count: int = 0

    def expand(self, state: Any) -> tuple[WeightedTransition[Any], ...]:
        """展开一个状态，并累计策略组合与随机分支在归并前后的数量。

        Args:
            state: 当前不可变战斗状态；保持与生产扩展器相同的 domain 合同。

        Returns:
            按后继 StateKey 归并后的精确概率转移元组。
        """
        attacker_actions = self.turn_resolver.legal_actions(state, BattleSide.ATTACKER)
        defender_actions = self.turn_resolver.legal_actions(state, BattleSide.DEFENDER)
        attacker_distribution = self.attacker_policy.distribution_for(attacker_actions)
        defender_distribution = self.defender_policy.distribution_for(defender_actions)
        attacker_distribution.validate_legal_actions(attacker_actions)
        defender_distribution.validate_legal_actions(defender_actions)

        transitions: list[WeightedTransition[Any]] = []
        for attacker_selection in attacker_distribution.selections:
            for defender_selection in defender_distribution.selections:
                resolution = self.turn_resolver.resolve(
                    state,
                    attacker_selection.action,
                    defender_selection.action,
                )
                policy_probability = (
                    attacker_selection.probability * defender_selection.probability
                )
                for transition in resolution.transitions:
                    transitions.append(
                        WeightedTransition(
                            probability=policy_probability * transition.probability,
                            state=transition.state,
                            event_summary=transition.event_summary,
                            source_key=transition.source_key
                            or "benchmark.policy-and-turn",
                        )
                    )
        merged = merge_equivalent_transitions(transitions)
        self.raw_transition_count += len(transitions)
        self.merged_transition_count += len(merged)
        return merged


def _execute_case(case: BenchmarkCaseInput) -> BenchmarkPairSample:
    """执行单个配置对，并把任何异常转换为可聚合的失败样本。

    Args:
        case: 已准备完成、可序列化到子进程的配置对输入。

    Returns:
        不持有完整状态图的成功、截断或失败性能样本。
    """
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    try:
        return _execute_case_unchecked(case)
    except Exception as error:  # noqa: BLE001 - benchmark 必须继续并记录具体失败配置。
        return _failed_benchmark_sample(
            case,
            error,
            wall_seconds=time.perf_counter() - started_wall,
            cpu_seconds=time.process_time() - started_cpu,
        )


def _execute_case_unchecked(case: BenchmarkCaseInput) -> BenchmarkPairSample:
    """使用真实状态图 builder 和精确 solver 执行一个已验证配置对。

    Args:
        case: 已准备完成、可序列化到子进程的配置对输入。

    Returns:
        包含图规模、精确概率和序列化探针的轻量样本。

    Raises:
        Exception: 构图、求解或摘要阶段的异常交给外层转换为失败样本。
    """
    serialization_started = time.perf_counter()
    input_bytes = len(pickle.dumps(case, protocol=pickle.HIGHEST_PROTOCOL))
    input_serialization_seconds = time.perf_counter() - serialization_started
    wall_started = time.perf_counter()
    cpu_started = time.process_time()
    build_started = time.perf_counter()
    factory = PokemonChampionEffectFactory()
    base_expander = _InstrumentedPolicyDrivenExpander(
        turn_resolver=BattleEventStandardMoveTurnResolver(
            effects=_effects(case.work_item.configuration, factory)
        ),
        attacker_policy=_policy(case.attacker_policy),
        defender_policy=_policy(case.defender_policy),
    )
    graph = StateGraphBuilder(
        expander=base_expander,
        limits=case.graph_limits,
    ).build(_initial_state(case.work_item.configuration, case.rules))
    graph_build_seconds = time.perf_counter() - build_started
    solve_started = time.perf_counter()
    solved = PurePythonBattleGraphSolver().solve(graph, BattleSide.ATTACKER)
    solve_seconds = time.perf_counter() - solve_started
    wall_seconds = time.perf_counter() - wall_started
    cpu_seconds = time.process_time() - cpu_started

    if not graph.is_complete or solved.status is BattleGraphSolveStatus.INCOMPLETE_GRAPH:
        status = "truncated"
        diagnostic = "; ".join(
            tuple(reason.value for reason in graph.truncation_reasons)
            + solved.diagnostics
        )
        probabilities = (None, None, None)
    elif solved.status is BattleGraphSolveStatus.SOLVED:
        status = "succeeded"
        diagnostic = "; ".join(solved.diagnostics) or None
        probabilities = (
            _fraction_tuple(solved.win_probability),
            _fraction_tuple(solved.loss_probability),
            _fraction_tuple(solved.draw_probability),
        )
    else:
        status = "failed"
        diagnostic = "; ".join(solved.diagnostics) or solved.status.value
        probabilities = (None, None, None)
    expected_turns = (
        _fraction_tuple(solved.expected_turns.value)
        if solved.expected_turns.status is ExpectedTurnsStatus.FINITE
        else None
    )
    fraction_values = tuple(
        value
        for value in (*probabilities, expected_turns)
        if value is not None
    )
    sample = BenchmarkPairSample(
        pair_id=case.work_item.pair_id,
        status=status,
        diagnostic=diagnostic,
        win_probability=probabilities[0],
        loss_probability=probabilities[1],
        draw_probability=probabilities[2],
        expected_turns=expected_turns,
        wall_seconds=wall_seconds,
        cpu_seconds=cpu_seconds,
        graph_build_seconds=graph_build_seconds,
        solve_seconds=solve_seconds,
        input_serialization_seconds=input_serialization_seconds,
        output_serialization_seconds=0.0,
        input_bytes=input_bytes,
        output_bytes=0,
        peak_rss_bytes=_peak_rss_bytes(),
        process_id=os.getpid(),
        node_count=graph.statistics.unique_state_count,
        edge_count=graph.statistics.edge_count,
        raw_transition_count=base_expander.raw_transition_count,
        merged_transition_count=base_expander.merged_transition_count,
        scc_count=len(graph.components),
        max_scc_size=max((len(value.node_ids) for value in graph.components), default=0),
        max_turn_number=graph.statistics.max_turn_number,
        numerator_bits=max((abs(value[0]).bit_length() for value in fraction_values), default=0),
        denominator_bits=max((value[1].bit_length() for value in fraction_values), default=0),
    )
    # 输出序列化探针只处理轻量 sample；完整 graph 在函数返回前显式释放。
    del graph
    output_started = time.perf_counter()
    output_bytes = len(pickle.dumps(sample, protocol=pickle.HIGHEST_PROTOCOL))
    output_seconds = time.perf_counter() - output_started
    return replace(
        sample,
        output_serialization_seconds=output_seconds,
        output_bytes=output_bytes,
    )


def _failed_benchmark_sample(
    case: BenchmarkCaseInput,
    error: Exception,
    *,
    wall_seconds: float = 0.0,
    cpu_seconds: float = 0.0,
) -> BenchmarkPairSample:
    """把配置构建、子进程或序列化异常转换为稳定失败样本。

    Args:
        case: 失败对应的稳定配置对输入。
        error: 原始异常，仅保留异常类型和文本用于诊断。
        wall_seconds: 已在当前进程消耗的墙钟时间。
        cpu_seconds: 已在当前进程消耗的 CPU 时间。

    Returns:
        概率与图规模为空值语义、可继续参与批量统计的失败样本。
    """
    try:
        serialization_started = time.perf_counter()
        input_bytes = len(pickle.dumps(case, protocol=pickle.HIGHEST_PROTOCOL))
        input_serialization_seconds = time.perf_counter() - serialization_started
    except Exception:  # noqa: BLE001 - 原始序列化失败时不能再次覆盖主诊断。
        input_bytes = 0
        input_serialization_seconds = 0.0
    sample = BenchmarkPairSample(
        pair_id=case.work_item.pair_id,
        status="failed",
        diagnostic=f"{type(error).__name__}: {error}",
        win_probability=None,
        loss_probability=None,
        draw_probability=None,
        expected_turns=None,
        wall_seconds=wall_seconds,
        cpu_seconds=cpu_seconds,
        graph_build_seconds=0.0,
        solve_seconds=0.0,
        input_serialization_seconds=input_serialization_seconds,
        output_serialization_seconds=0.0,
        input_bytes=input_bytes,
        output_bytes=0,
        peak_rss_bytes=_peak_rss_bytes(),
        process_id=os.getpid(),
        node_count=0,
        edge_count=0,
        raw_transition_count=0,
        merged_transition_count=0,
        scc_count=0,
        max_scc_size=0,
        max_turn_number=0,
        numerator_bits=0,
        denominator_bits=0,
    )
    try:
        output_started = time.perf_counter()
        output_bytes = len(pickle.dumps(sample, protocol=pickle.HIGHEST_PROTOCOL))
        output_seconds = time.perf_counter() - output_started
    except Exception:  # pragma: no cover - sample 只含基础类型，保留防御路径。
        return sample
    return replace(
        sample,
        output_serialization_seconds=output_seconds,
        output_bytes=output_bytes,
    )


def _peak_rss_bytes() -> int:
    """返回当前进程已观测峰值 RSS，并统一转换为字节。

    Returns:
        resource 模块可用时的峰值常驻集字节数，否则返回 0。
    """
    if resource is None:
        return 0
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _fraction_tuple(value: Fraction | None) -> tuple[int, int] | None:
    """把 Fraction 转成可直接 JSON 化的分子分母二元组。

    Args:
        value: 精确概率、期望回合或未提供值。

    Returns:
        分子与分母二元组；输入为 None 时保持 None。
    """
    return None if value is None else (value.numerator, value.denominator)


def _fraction_text(value: tuple[int, int] | None) -> str:
    """把可选分子分母二元组转换为稳定摘要文本。

    Args:
        value: 可选精确分子分母二元组。

    Returns:
        n/d 文本或表示缺失值的 none。
    """
    return "none" if value is None else f"{value[0]}/{value[1]}"


__all__ = [
    "_execute_case",
    "_failed_benchmark_sample",
    "_fraction_text",
    "_peak_rss_bytes",
]
