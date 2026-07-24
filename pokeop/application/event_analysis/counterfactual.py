"""定义两次独立 revision 重算的战斗事件反事实分析合同。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Protocol, runtime_checkable

from pokeop.domain.battle.inference_outcome import BattleSide

from .analyzer import BattleEventAnalyzer
from .models import (
    BattleEventAnalysisArtifact,
    BattleEventAnalysisError,
    BattleEventAnalysisResult,
    BattleEventQuery,
)


@dataclass(frozen=True, slots=True)
class BattleRuleOverride:
    """表示反事实 revision 相对基线启用的一个稳定规则覆盖。

    Args:
        identifier: 可由推演执行端识别的稳定规则键。
        value: 覆盖后的规范化序列化值。
    """

    identifier: str
    value: str

    def __post_init__(self) -> None:
        """校验规则标识和值均为规范化非空文本。"""
        for field_name, text in (
            ("identifier", self.identifier),
            ("value", self.value),
        ):
            if not text.strip() or text != text.strip():
                raise BattleEventAnalysisError(
                    f"counterfactual override {field_name} must be normalized"
                )


@dataclass(frozen=True, slots=True)
class CounterfactualBattleEventRequest:
    """定义需要独立执行的基线 revision 与规则覆盖 revision。

    Args:
        baseline_revision: 不应用覆盖的基线计算 revision。
        counterfactual_revision: 应用覆盖后的独立计算 revision。
        rule_overrides: 传给推演端的显式规则覆盖集合。
        query: 两个 revision 共同使用的事件查询。
        observer: 两个 revision 共同使用的获胜观察侧。
    """

    baseline_revision: str
    counterfactual_revision: str
    rule_overrides: tuple[BattleRuleOverride, ...]
    query: BattleEventQuery
    observer: BattleSide = BattleSide.ATTACKER

    def __post_init__(self) -> None:
        """拒绝同 revision、空覆盖和重复规则标识。"""
        for field_name, value in (
            ("baseline_revision", self.baseline_revision),
            ("counterfactual_revision", self.counterfactual_revision),
        ):
            if not value.strip() or value != value.strip():
                raise BattleEventAnalysisError(
                    f"{field_name} must be normalized non-empty text"
                )
        if self.baseline_revision == self.counterfactual_revision:
            raise BattleEventAnalysisError(
                "counterfactual analysis requires distinct revisions"
            )
        if not self.rule_overrides:
            raise BattleEventAnalysisError(
                "counterfactual analysis requires at least one rule override"
            )
        if len({item.identifier for item in self.rule_overrides}) != len(
            self.rule_overrides
        ):
            raise BattleEventAnalysisError(
                "counterfactual rule override identifiers must be unique"
            )
        if not isinstance(self.query, BattleEventQuery):
            raise BattleEventAnalysisError("query must be a BattleEventQuery")
        if not isinstance(self.observer, BattleSide):
            raise BattleEventAnalysisError("observer must be a BattleSide")


@dataclass(frozen=True, slots=True)
class CounterfactualInferenceRequest:
    """传给推演执行端的一次 revision 和规则覆盖请求。

    Args:
        calculation_revision: 本次独立推演必须返回的稳定 revision。
        rule_overrides: 本次推演应用的显式规则覆盖；基线请求为空。
    """

    calculation_revision: str
    rule_overrides: tuple[BattleRuleOverride, ...]

    def __post_init__(self) -> None:
        """校验 revision 规范化并拒绝重复规则覆盖。"""
        if (
            not self.calculation_revision.strip()
            or self.calculation_revision != self.calculation_revision.strip()
        ):
            raise BattleEventAnalysisError(
                "calculation_revision must be normalized non-empty text"
            )
        if any(
            not isinstance(override, BattleRuleOverride)
            for override in self.rule_overrides
        ):
            raise BattleEventAnalysisError(
                "rule_overrides must contain BattleRuleOverride values"
            )
        if len({item.identifier for item in self.rule_overrides}) != len(
            self.rule_overrides
        ):
            raise BattleEventAnalysisError(
                "counterfactual inference overrides must be unique"
            )


@runtime_checkable
class CounterfactualInferenceRunner(Protocol):
    """为基线和对照 revision 分别构建完整独立状态图。"""

    def run(
        self,
        request: CounterfactualInferenceRequest,
    ) -> BattleEventAnalysisArtifact:
        """执行一次独立推演并返回带唯一运行 ID 的完整图 artifact。

        Args:
            request: 稳定 revision 和本次独立推演的规则覆盖。

        Returns:
            revision 与请求一致、运行 ID 唯一的完整状态图 artifact。
        """


@dataclass(frozen=True, slots=True)
class CounterfactualComputationCost:
    """明确反事实分析必须执行两次推演和两次事件分析。

    Args:
        inference_run_count: 独立推演运行次数。
        graph_build_count: 完整状态图构建次数。
        exact_solver_run_count: 两个事件分析累计的精确图求解次数。
    """

    inference_run_count: int
    graph_build_count: int
    exact_solver_run_count: int

    def __post_init__(self) -> None:
        """校验反事实成本计数均为正整数。"""
        for field_name, value in (
            ("inference_run_count", self.inference_run_count),
            ("graph_build_count", self.graph_build_count),
            ("exact_solver_run_count", self.exact_solver_run_count),
        ):
            if isinstance(value, bool) or value <= 0:
                raise BattleEventAnalysisError(
                    f"{field_name} must be greater than 0"
                )


@dataclass(frozen=True, slots=True)
class CounterfactualBattleEventResult:
    """保存两个独立 revision 的结果及其差值，不把观察相关性表述为因果。

    Args:
        request: 原始反事实 revision 和规则覆盖请求。
        baseline: 基线 revision 的事件分析结果。
        counterfactual: 覆盖 revision 的事件分析结果。
        win_probability_delta: 对照减基线的观察方胜率差值。
        event_probability_delta: 对照减基线的事件概率差值。
        event_win_joint_probability_delta: 对照减基线的联合贡献差值。
        independent_revisions_verified: 是否确认 revision 与运行 ID 均独立。
        computation_cost: 两次推演和分析累计成本。
    """

    request: CounterfactualBattleEventRequest
    baseline: BattleEventAnalysisResult
    counterfactual: BattleEventAnalysisResult
    win_probability_delta: Fraction
    event_probability_delta: Fraction
    event_win_joint_probability_delta: Fraction
    independent_revisions_verified: bool
    computation_cost: CounterfactualComputationCost


@dataclass(frozen=True, slots=True)
class CounterfactualBattleEventAnalyzer:
    """调用两次独立推演，再分别分析事件并计算 revision 差值。

    Args:
        runner: 根据 revision 和规则覆盖构建完整独立状态图的执行端。
        analyzer: 复用的精确事件分析器。
    """

    runner: CounterfactualInferenceRunner
    analyzer: BattleEventAnalyzer = BattleEventAnalyzer()

    def __post_init__(self) -> None:
        """校验推演执行端和事件分析器协议。"""
        if not isinstance(self.runner, CounterfactualInferenceRunner):
            raise BattleEventAnalysisError(
                "runner must implement CounterfactualInferenceRunner"
            )
        if not isinstance(self.analyzer, BattleEventAnalyzer):
            raise BattleEventAnalysisError("analyzer must be BattleEventAnalyzer")

    def execute(
        self,
        request: CounterfactualBattleEventRequest,
    ) -> CounterfactualBattleEventResult:
        """执行基线和规则覆盖 revision，并返回独立重算差值。

        Args:
            request: 两个 revision、规则覆盖、事件查询和观察侧。

        Returns:
            两次独立结果、胜率/事件概率差值和显式计算成本。
        """
        if not isinstance(request, CounterfactualBattleEventRequest):
            raise BattleEventAnalysisError(
                "request must be a CounterfactualBattleEventRequest"
            )

        baseline_artifact = self.runner.run(
            CounterfactualInferenceRequest(
                calculation_revision=request.baseline_revision,
                rule_overrides=(),
            )
        )
        counterfactual_artifact = self.runner.run(
            CounterfactualInferenceRequest(
                calculation_revision=request.counterfactual_revision,
                rule_overrides=request.rule_overrides,
            )
        )
        if baseline_artifact.calculation_revision != request.baseline_revision:
            raise BattleEventAnalysisError(
                "baseline runner returned an unexpected revision"
            )
        if (
            counterfactual_artifact.calculation_revision
            != request.counterfactual_revision
        ):
            raise BattleEventAnalysisError(
                "counterfactual runner returned an unexpected revision"
            )
        if (
            baseline_artifact.inference_run_id
            == counterfactual_artifact.inference_run_id
        ):
            raise BattleEventAnalysisError(
                "counterfactual analysis requires two independent inference run IDs"
            )

        baseline = self.analyzer.analyze(
            baseline_artifact,
            request.query,
            request.observer,
        )
        counterfactual = self.analyzer.analyze(
            counterfactual_artifact,
            request.query,
            request.observer,
        )
        return CounterfactualBattleEventResult(
            request=request,
            baseline=baseline,
            counterfactual=counterfactual,
            win_probability_delta=(
                counterfactual.baseline_win_probability
                - baseline.baseline_win_probability
            ),
            event_probability_delta=(
                counterfactual.event_probability - baseline.event_probability
            ),
            event_win_joint_probability_delta=(
                counterfactual.event_win_joint_probability
                - baseline.event_win_joint_probability
            ),
            independent_revisions_verified=True,
            computation_cost=CounterfactualComputationCost(
                inference_run_count=2,
                graph_build_count=2,
                exact_solver_run_count=(
                    baseline.computation_cost.exact_solver_run_count
                    + counterfactual.computation_cost.exact_solver_run_count
                ),
            ),
        )


__all__ = [
    "BattleRuleOverride",
    "CounterfactualBattleEventAnalyzer",
    "CounterfactualBattleEventRequest",
    "CounterfactualBattleEventResult",
    "CounterfactualComputationCost",
    "CounterfactualInferenceRequest",
    "CounterfactualInferenceRunner",
]
