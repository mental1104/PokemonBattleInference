"""真实流式聚合与原AggregateState逐步进度、完整Top-K和分数位数差分。"""

from __future__ import annotations

import os
import random
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.solver.graph_solver import ExpectedTurnsStatus
from pokeop.application.use_cases.stream_configuration_pairs.aggregation import AggregateState
from pokeop.application.use_cases.stream_configuration_pairs.models import (
    ConfigurationPairAggregate, ConfigurationPairExecutionResult, ConfigurationPairExecutionStatus,
    ConfigurationPairProgress, ConfigurationPairRankingEntry, ConfigurationPairStopReason,
)
from tests.migration.test_core_damage import ExactFraction


class _Contract(BaseModel):
    """冻结精确进程合同，拒绝任何被省略或额外字段。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Identity(_Contract):
    """成功排行保留的完整轻量身份，不引用完整配置/状态图。"""

    pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]


class Observation(Identity):
    """原result全部聚合输入，计数用十进制字符串避免JSON大整数变浮点。"""

    configuration_weight: ExactFraction
    status: ConfigurationPairExecutionStatus
    win_probability: ExactFraction | None
    loss_probability: ExactFraction | None
    draw_probability: ExactFraction | None
    expected_turns: ExactFraction | None
    expected_turns_status: ExpectedTurnsStatus
    node_count: str
    edge_count: str
    scc_count: str
    max_turn_number: str


class AggregateInput(_Contract):
    """一次完整或部分原执行流，不预先计算任何聚合值。"""

    top_k: int
    total_pair_count: str
    stop_reason: ConfigurationPairStopReason
    results: tuple[Observation, ...]


class Progress(_Contract):
    """每次Add后的原完整进度。"""

    processed_pair_count: str
    total_pair_count: str
    succeeded_count: str
    truncated_count: str
    failed_count: str
    attempted_weight: ExactFraction
    completed_weight: ExactFraction
    cumulative_node_count: str
    cumulative_edge_count: str


class Ranking(Identity):
    """原有界排行全部字段，不能只比较ID掩盖指标或代表变化。"""

    win_probability: ExactFraction
    loss_probability: ExactFraction
    draw_probability: ExactFraction
    expected_turns: ExactFraction | None
    node_count: str
    edge_count: str


class Complexity(_Contract):
    """每个中间/最终Fraction的精确位数指标。"""

    observed_fraction_count: str
    max_numerator_bits: int
    max_denominator_bits: int
    final_win_numerator_bits: int
    final_win_denominator_bits: int
    final_loss_numerator_bits: int
    final_loss_denominator_bits: int
    final_draw_numerator_bits: int
    final_draw_denominator_bits: int


class Aggregate(Progress):
    """完整最终聚合，仍以未缩减的原始配置空间作为分母。"""

    stop_reason: ConfigurationPairStopReason
    unprocessed_pair_count: str
    weighted_win_probability: ExactFraction
    weighted_loss_probability: ExactFraction
    weighted_draw_probability: ExactFraction
    top_win_probability: tuple[Ranking, ...]
    top_expected_turns: tuple[Ranking, ...]
    top_node_count: tuple[Ranking, ...]
    fraction_complexity: Complexity


class AggregateReply(_Contract):
    """所有中间进度与最终结果都必须与原业务相同。"""

    progresses: tuple[Progress, ...]
    aggregate: Aggregate


class _Oracle:
    """仅负责类型边界投影，不复制原统计、排名、位数或归一化算法。"""

    @staticmethod
    def fraction(value: Fraction) -> ExactFraction:
        """把原精确分数映射为规范字符串，不经float。"""
        return ExactFraction(numerator=str(value.numerator), denominator=str(value.denominator))

    @staticmethod
    def observation(value: Observation) -> ConfigurationPairExecutionResult:
        """由完整事实构造原已验证result；失败/截断不能携带部分概率。"""
        return ConfigurationPairExecutionResult(pair_id=value.pair_id,
            attacker_configuration_id=value.attacker_configuration_id, defender_configuration_id=value.defender_configuration_id,
            attacker_move_ids=value.attacker_move_ids, defender_move_ids=value.defender_move_ids,
            configuration_weight=value.configuration_weight.value(), status=value.status,
            win_probability=None if value.win_probability is None else value.win_probability.value(),
            loss_probability=None if value.loss_probability is None else value.loss_probability.value(),
            draw_probability=None if value.draw_probability is None else value.draw_probability.value(),
            expected_turns=None if value.expected_turns is None else value.expected_turns.value(),
            expected_turns_status=value.expected_turns_status, node_count=int(value.node_count), edge_count=int(value.edge_count),
            scc_count=int(value.scc_count), max_turn_number=int(value.max_turn_number))

    @classmethod
    def progress(cls, value: ConfigurationPairProgress | ConfigurationPairAggregate) -> Progress:
        """完整投影原进度字段，不据状态重新求和。"""
        return Progress(processed_pair_count=str(value.processed_pair_count), total_pair_count=str(value.total_pair_count),
            succeeded_count=str(value.succeeded_count), truncated_count=str(value.truncated_count), failed_count=str(value.failed_count),
            attempted_weight=cls.fraction(value.attempted_weight), completed_weight=cls.fraction(value.completed_weight),
            cumulative_node_count=str(value.cumulative_node_count), cumulative_edge_count=str(value.cumulative_edge_count))

    @classmethod
    def ranking(cls, value: ConfigurationPairRankingEntry) -> Ranking:
        """保留每项原排行身份、概率、期望与资源字段。"""
        return Ranking(pair_id=value.pair_id, attacker_configuration_id=value.attacker_configuration_id,
            defender_configuration_id=value.defender_configuration_id, attacker_move_ids=value.attacker_move_ids, defender_move_ids=value.defender_move_ids,
            win_probability=cls.fraction(value.win_probability), loss_probability=cls.fraction(value.loss_probability), draw_probability=cls.fraction(value.draw_probability),
            expected_turns=None if value.expected_turns is None else cls.fraction(value.expected_turns), node_count=str(value.node_count), edge_count=str(value.edge_count))

    @classmethod
    def reference(cls, request: AggregateInput) -> AggregateReply:
        """调用原AggregateState处理相同顺序的完整流，输出每步与最终精确结果。"""
        original = AggregateState(request.top_k)
        total = int(request.total_pair_count)
        progresses: list[Progress] = []
        for observation in request.results:
            original.add(cls.observation(observation))
            progresses.append(cls.progress(original.progress(total_pair_count=total)))
        result = original.finish(stop_reason=request.stop_reason, total_pair_count=total)
        bits = result.fraction_complexity
        return AggregateReply(progresses=tuple(progresses), aggregate=Aggregate(
            **cls.progress(result).model_dump(), stop_reason=result.stop_reason, unprocessed_pair_count=str(result.unprocessed_pair_count),
            weighted_win_probability=cls.fraction(result.weighted_win_probability), weighted_loss_probability=cls.fraction(result.weighted_loss_probability),
            weighted_draw_probability=cls.fraction(result.weighted_draw_probability), top_win_probability=tuple(cls.ranking(value) for value in result.top_win_probability),
            top_expected_turns=tuple(cls.ranking(value) for value in result.top_expected_turns), top_node_count=tuple(cls.ranking(value) for value in result.top_node_count),
            fraction_complexity=Complexity(observed_fraction_count=str(bits.observed_fraction_count), max_numerator_bits=bits.max_numerator_bits,
                max_denominator_bits=bits.max_denominator_bits, final_win_numerator_bits=bits.final_win_numerator_bits,
                final_win_denominator_bits=bits.final_win_denominator_bits, final_loss_numerator_bits=bits.final_loss_numerator_bits,
                final_loss_denominator_bits=bits.final_loss_denominator_bits, final_draw_numerator_bits=bits.final_draw_numerator_bits,
                final_draw_denominator_bits=bits.final_draw_denominator_bits)))

    @staticmethod
    def run(runner: Path, requests: tuple[AggregateInput, ...]) -> tuple[AggregateReply, ...]:
        """批量调用真实C++，严格解析每一条完整响应，不接受error当作零值。"""
        result = subprocess.run([str(runner)], input="".join(request.model_dump_json() + "\n" for request in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        return tuple(AggregateReply.model_validate_json(line) for line in lines)


@pytest.fixture
def configuration_aggregate_runner() -> Path:
    """使用外部实际编译入口；缺少时明确skip，不以内存fake替代Core。"""
    value = os.getenv("PBI_CONFIGURATION_AGGREGATE_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_AGGREGATE_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreConfigurationAggregate:
    """逐步精确权重、全部状态桶、有界稳定排行和分数复杂度的真实业务差分。"""

    def test_full_and_partial_streams(self, configuration_aggregate_runner: Path) -> None:
        """384组随机完整/部分流，覆盖全部停止原因、三状态和无限期望。"""
        rng = random.Random(854321)
        requests: list[AggregateInput] = []
        reasons = tuple(ConfigurationPairStopReason)
        for case in range(384):
            total = rng.randint(0, 32)
            processed = rng.randint(0, total)
            weights = tuple(rng.randint(1, 1000) for _ in range(total))
            results: list[Observation] = []
            for index in range(processed):
                status = rng.choice(tuple(ConfigurationPairExecutionStatus))
                win: ExactFraction | None = None
                loss: ExactFraction | None = None
                draw: ExactFraction | None = None
                expected: ExactFraction | None = None
                expected_status = ExpectedTurnsStatus.UNAVAILABLE
                if status is ConfigurationPairExecutionStatus.SUCCEEDED:
                    components = (rng.randint(0, 13), rng.randint(0, 13), rng.randint(1, 13))
                    win, loss, draw = tuple(_Oracle.fraction(Fraction(value, sum(components))) for value in components)
                    expected_status = rng.choice((ExpectedTurnsStatus.FINITE, ExpectedTurnsStatus.INFINITE))
                    if expected_status is ExpectedTurnsStatus.FINITE:
                        expected = _Oracle.fraction(Fraction(rng.randint(0, 50), rng.randint(1, 9)))
                results.append(Observation(pair_id=f"pair-{index % 4}", attacker_configuration_id=f"attacker-{index}",
                    defender_configuration_id=f"defender-{index}", attacker_move_ids=(1, 2), defender_move_ids=(4,),
                    configuration_weight=_Oracle.fraction(Fraction(weights[index], sum(weights))), status=status,
                    win_probability=win, loss_probability=loss, draw_probability=draw, expected_turns=expected, expected_turns_status=expected_status,
                    node_count=str(10 ** 100 if index == 0 and case % 8 == 0 else rng.randint(0, 20)), edge_count=str(rng.randint(0, 30)),
                    scc_count=str(rng.randint(0, 5)), max_turn_number=str(rng.randint(0, 20))))
            requests.append(AggregateInput(top_k=rng.randint(1, 10), total_pair_count=str(total), stop_reason=reasons[case % len(reasons)], results=tuple(results)))
        actual = _Oracle.run(configuration_aggregate_runner, tuple(requests))
        assert actual == tuple(_Oracle.reference(request) for request in requests)
