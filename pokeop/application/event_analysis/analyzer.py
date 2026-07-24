"""编排单个完整状态图的随机战斗事件精确分析。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    BattleGraphSolver,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import GraphNodeOutcome
from pokeop.domain.battle.inference_outcome import BattleSide

from .models import (
    BattleEventAnalysisArtifact,
    BattleEventAnalysisComputationCost,
    BattleEventAnalysisError,
    BattleEventAnalysisResult,
    BattleEventQuery,
    ConditionalProbability,
    ConditionalProbabilityStatus,
)
from .product_graph import (
    _build_event_product_graph,
    _event_metadata_coverage,
    _first_occurrence_distribution,
    _occurrence_count_distribution,
    _query_satisfied,
    _require_solved,
    _required_probability,
    _solve_product_property,
)


@dataclass(frozen=True, slots=True)
class BattleEventAnalyzer:
    """在完整有限状态图之上构造事件历史乘积图并执行精确求解。

    Args:
        solver: 复用现有 SCC/线性方程语义的精确状态图求解器。
    """

    solver: BattleGraphSolver = PurePythonBattleGraphSolver()

    def __post_init__(self) -> None:
        """校验求解器实现稳定 ``BattleGraphSolver`` 协议。"""
        if not isinstance(self.solver, BattleGraphSolver):
            raise BattleEventAnalysisError("solver must implement BattleGraphSolver")

    def analyze(
        self,
        artifact: BattleEventAnalysisArtifact,
        query: BattleEventQuery,
        observer: BattleSide = BattleSide.ATTACKER,
    ) -> BattleEventAnalysisResult:
        """计算事件发生、条件胜率、联合贡献和有限分布。

        Args:
            artifact: 一次独立 revision 推演产生的完整状态图。
            query: 类型化事件 E 的过滤、次数和回合语义。
            observer: 获胜结果 W 所采用的观察侧。

        Returns:
            精确事件指标、分布、元数据覆盖和计算成本。

        Raises:
            BattleEventAnalysisError: 图不完整、基线无法求解、产品图不守恒或参数非法。
        """
        if not isinstance(artifact, BattleEventAnalysisArtifact):
            raise BattleEventAnalysisError(
                "artifact must be a BattleEventAnalysisArtifact"
            )
        if not isinstance(query, BattleEventQuery):
            raise BattleEventAnalysisError("query must be a BattleEventQuery")
        if not isinstance(observer, BattleSide):
            raise BattleEventAnalysisError("observer must be a BattleSide")

        baseline = self.solver.solve(artifact.graph, observer)
        _require_solved("baseline", baseline)
        product = _build_event_product_graph(artifact.graph, query)
        preserved = self.solver.solve(product.graph, observer)
        _require_solved("product preservation", preserved)
        original_probability_preserved = _same_outcome_probabilities(
            baseline,
            preserved,
        )
        if not original_probability_preserved:
            raise BattleEventAnalysisError(
                "event product graph changed original win/loss/draw probabilities"
            )

        event_probability = _solve_product_property(
            product,
            self.solver,
            lambda tracker, _outcome, _closed: _query_satisfied(
                tracker,
                query,
                product,
            ),
        )
        observer_outcome = (
            GraphNodeOutcome.ATTACKER_WIN
            if observer is BattleSide.ATTACKER
            else GraphNodeOutcome.DEFENDER_WIN
        )
        event_win_joint_probability = _solve_product_property(
            product,
            self.solver,
            lambda tracker, outcome, closed: (
                not closed
                and outcome is observer_outcome
                and _query_satisfied(tracker, query, product)
            ),
        )

        baseline_win = _required_probability("baseline win", baseline.win_probability)
        baseline_loss = _required_probability(
            "baseline loss",
            baseline.loss_probability,
        )
        baseline_draw = _required_probability(
            "baseline draw",
            baseline.draw_probability,
        )
        event_complement = Fraction(1) - event_probability
        not_event_win_joint = baseline_win - event_win_joint_probability
        win_given_event = _conditional_probability(
            event_win_joint_probability,
            event_probability,
        )
        win_given_not_event = _conditional_probability(
            not_event_win_joint,
            event_complement,
        )

        count_distribution, count_solver_runs = _occurrence_count_distribution(
            product,
            query,
            self.solver,
        )
        first_distribution, first_solver_runs = _first_occurrence_distribution(
            product,
            query,
            self.solver,
        )
        coverage, key_events = _event_metadata_coverage(artifact.graph, query)
        exact_solver_run_count = 4 + count_solver_runs + first_solver_runs
        return BattleEventAnalysisResult(
            calculation_revision=artifact.calculation_revision,
            inference_run_id=artifact.inference_run_id,
            observer=observer,
            query=query,
            baseline_win_probability=baseline_win,
            baseline_loss_probability=baseline_loss,
            baseline_draw_probability=baseline_draw,
            event_probability=event_probability,
            event_win_joint_probability=event_win_joint_probability,
            win_given_event=win_given_event,
            win_given_not_event=win_given_not_event,
            first_occurrence_distribution=first_distribution,
            occurrence_count_distribution=count_distribution,
            path_group_coverage=coverage,
            key_events=key_events,
            original_probability_preserved=original_probability_preserved,
            computation_cost=BattleEventAnalysisComputationCost(
                original_node_count=len(artifact.graph.nodes),
                original_edge_count=len(artifact.graph.edges),
                product_node_count=len(product.graph.nodes),
                product_edge_count=len(product.graph.edges),
                exact_solver_run_count=exact_solver_run_count,
            ),
        )


def _same_outcome_probabilities(
    baseline: BattleGraphSolveResult,
    product: BattleGraphSolveResult,
) -> bool:
    """比较分析前后胜、负、平与封闭循环概率是否完全一致。

    Args:
        baseline: 原始状态图的精确求解结果。
        product: 事件历史乘积图忽略分析属性后的精确求解结果。

    Returns:
        四类结果概率全部严格相等时返回 True。
    """
    return (
        baseline.win_probability == product.win_probability
        and baseline.loss_probability == product.loss_probability
        and baseline.draw_probability == product.draw_probability
        and baseline.closed_cycle_probability == product.closed_cycle_probability
    )


def _conditional_probability(
    joint_probability: Fraction,
    condition_probability: Fraction,
) -> ConditionalProbability:
    """按联合概率和条件质量构造可解释条件概率。

    Args:
        joint_probability: ``P(W ∩ E)`` 等联合概率。
        condition_probability: ``P(E)`` 等条件事件概率。

    Returns:
        条件质量为零时返回不可定义状态，否则返回精确商。
    """
    if condition_probability == 0:
        return ConditionalProbability(
            status=ConditionalProbabilityStatus.UNDEFINED_ZERO_CONDITION,
            value=None,
            condition_probability=Fraction(0),
        )
    return ConditionalProbability(
        status=ConditionalProbabilityStatus.DEFINED,
        value=joint_probability / condition_probability,
        condition_probability=condition_probability,
    )


__all__ = ["BattleEventAnalyzer"]
