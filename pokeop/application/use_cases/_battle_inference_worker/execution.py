"""在子进程执行单配置，并把轻量结果映射为持久化终态。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseResult,
    BattleInferenceCaseStatus,
    BattleInferenceExpectedTurns,
    BattleInferenceExpectedTurnsKind,
    BattleInferenceFailureCode,
    BattleInferenceProbability,
)
from pokeop.application.solver.graph_solver import ExpectedTurnsStatus
from pokeop.application.use_cases._battle_inference_worker.contracts import (
    PreparedBattleInferenceCase,
)
from pokeop.application.use_cases.stream_configuration_pairs import (
    ConfigurationPairAggregate,
    ConfigurationPairExecutionResult,
    ConfigurationPairExecutionStatus,
    ConfigurationPairResultSink,
    NormalizedBattleConfiguration,
    StreamConfigurationPairsCommand,
    StreamConfigurationPairsUseCase,
)
from pokeop.domain.battle.inference_outcome import BattleSide


@dataclass(slots=True)
class _SingleResultSink(ConfigurationPairResultSink):
    """捕获子进程内唯一配置结果，不保留最终聚合。"""

    result: ConfigurationPairExecutionResult | None = None

    def write_result(self, result: ConfigurationPairExecutionResult) -> None:
        """保存唯一轻量结果并拒绝意外的第二项。"""
        if self.result is not None:
            raise RuntimeError("single configuration sink received more than one result")
        self.result = result

    def write_final(self, aggregate: ConfigurationPairAggregate) -> None:
        """接收但不保存单配置聚合。"""


def execute_prepared_battle_inference_case(
    prepared: PreparedBattleInferenceCase,
) -> ConfigurationPairExecutionResult:
    """在子进程中复用 #86 流式执行器求解一个准备完成的配置。"""
    sink = _SingleResultSink()
    command = StreamConfigurationPairsCommand(
        rules=prepared.rules,
        attacker_configurations=(
            NormalizedBattleConfiguration(
                configuration_id=prepared.attacker_configuration_id,
                configuration=prepared.configuration.attacker,
                weight=Fraction(1),
            ),
        ),
        defender_configurations=(
            NormalizedBattleConfiguration(
                configuration_id=prepared.defender_configuration_id,
                configuration=prepared.configuration.defender,
                weight=Fraction(1),
            ),
        ),
        attacker_policy=prepared.attacker_policy,
        defender_policy=prepared.defender_policy,
        observer=BattleSide.ATTACKER,
        graph_limits=prepared.graph_limits,
        max_configuration_pairs=1,
        top_k=1,
    )
    StreamConfigurationPairsUseCase(result_sink=sink).execute(command)
    if sink.result is None:
        raise RuntimeError("single configuration execution produced no result")
    return replace(sink.result, pair_id=prepared.configuration_pair_id)


def persistent_result(
    result: ConfigurationPairExecutionResult,
) -> BattleInferenceCaseResult:
    """把 #86 轻量结果转换为 #85 幂等持久化结果。"""
    if result.status is ConfigurationPairExecutionStatus.SUCCEEDED:
        assert result.win_probability is not None
        assert result.loss_probability is not None
        assert result.draw_probability is not None
        return BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.SUCCEEDED,
            attacker_win=_probability(result.win_probability),
            defender_win=_probability(result.loss_probability),
            draw=_probability(result.draw_probability),
            expected_turns=_expected_turns(result),
            node_count=result.node_count,
            edge_count=result.edge_count,
            budget_consumed=result.node_count + result.edge_count,
        )
    diagnostic = "; ".join(result.diagnostics) or result.status.value
    if result.status is ConfigurationPairExecutionStatus.TRUNCATED:
        return BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.TRUNCATED,
            node_count=result.node_count,
            edge_count=result.edge_count,
            budget_consumed=result.node_count + result.edge_count,
            failure_code=_truncation_code(result.diagnostics),
            diagnostic=diagnostic,
        )
    return BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.FAILED,
        node_count=result.node_count,
        edge_count=result.edge_count,
        budget_consumed=result.node_count + result.edge_count,
        failure_code=BattleInferenceFailureCode.SOLVER_UNRESOLVED,
        diagnostic=diagnostic,
    )


def failure_result(
    code: BattleInferenceFailureCode,
    error: Exception,
) -> BattleInferenceCaseResult:
    """把准备、进程或反序列化异常转换为稳定失败结果。"""
    return BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.FAILED,
        failure_code=code,
        diagnostic=f"{type(error).__name__}: {error}",
    )


def _probability(value: Fraction) -> BattleInferenceProbability:
    """把精确 Fraction 转换为持久化概率。"""
    return BattleInferenceProbability(value.numerator, value.denominator)


def _expected_turns(
    result: ConfigurationPairExecutionResult,
) -> BattleInferenceExpectedTurns:
    """保留有限或无限期望回合语义。"""
    if result.expected_turns_status is ExpectedTurnsStatus.FINITE:
        assert result.expected_turns is not None
        return BattleInferenceExpectedTurns(
            kind=BattleInferenceExpectedTurnsKind.FINITE,
            numerator=result.expected_turns.numerator,
            denominator=result.expected_turns.denominator,
        )
    if result.expected_turns_status is ExpectedTurnsStatus.INFINITE:
        return BattleInferenceExpectedTurns(kind=BattleInferenceExpectedTurnsKind.INFINITE)
    return BattleInferenceExpectedTurns(kind=BattleInferenceExpectedTurnsKind.UNAVAILABLE)


def _truncation_code(diagnostics: tuple[str, ...]) -> BattleInferenceFailureCode:
    """按稳定图运行保护原因选择失败代码。"""
    if "max-nodes" in diagnostics:
        return BattleInferenceFailureCode.GRAPH_NODE_LIMIT
    if "max-edges" in diagnostics:
        return BattleInferenceFailureCode.GRAPH_EDGE_LIMIT
    if "max-turns" in diagnostics:
        return BattleInferenceFailureCode.TURN_LIMIT
    return BattleInferenceFailureCode.SOLVER_UNRESOLVED
