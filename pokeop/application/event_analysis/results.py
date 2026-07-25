"""定义随机战斗事件分析的概率、覆盖和成本结果模型。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application.solver.models import StateGraphBuildResult
from pokeop.domain.battle.battle_events import BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEventType

from .query import (
    BattleEventAnalysisError,
    BattleEventQuery,
    ConditionalProbabilityStatus,
)


@dataclass(frozen=True, slots=True)
class ConditionalProbability:
    """保存一个条件概率或明确不可定义状态。

    Args:
        status: 条件概率是否已定义。
        value: 已定义时的精确概率；条件概率为零时必须为 None。
        condition_probability: 条件事件本身的精确概率。
    """

    status: ConditionalProbabilityStatus
    value: Fraction | None
    condition_probability: Fraction

    def __post_init__(self) -> None:
        """校验状态、条件质量和值的一致性。"""
        if not isinstance(self.status, ConditionalProbabilityStatus):
            raise BattleEventAnalysisError(
                "conditional probability status must be explicit"
            )
        if not isinstance(self.condition_probability, Fraction) or not (
            Fraction(0) <= self.condition_probability <= Fraction(1)
        ):
            raise BattleEventAnalysisError(
                "condition_probability must be a Fraction in [0, 1]"
            )
        if self.status is ConditionalProbabilityStatus.DEFINED:
            if self.condition_probability == 0:
                raise BattleEventAnalysisError(
                    "defined conditional probability requires positive condition mass"
                )
            if not isinstance(self.value, Fraction) or not (
                Fraction(0) <= self.value <= Fraction(1)
            ):
                raise BattleEventAnalysisError(
                    "defined conditional probability must carry a Fraction in [0, 1]"
                )
            return
        if self.condition_probability != 0 or self.value is not None:
            raise BattleEventAnalysisError(
                "undefined conditional probability requires zero mass and no value"
            )


@dataclass(frozen=True, slots=True)
class ProbabilityDistributionBucket:
    """保存首次发生回合或发生次数的一个精确概率桶。

    Args:
        key: 稳定桶标识，例如 ``count:2`` 或 ``first:never``。
        probability: 随机历史最终落入该桶的精确概率。
    """

    key: str
    probability: Fraction

    def __post_init__(self) -> None:
        """校验稳定桶键和非负精确概率。"""
        if not self.key.strip() or self.key != self.key.strip():
            raise BattleEventAnalysisError("distribution bucket key must be normalized")
        if not isinstance(self.probability, Fraction) or not (
            Fraction(0) <= self.probability <= Fraction(1)
        ):
            raise BattleEventAnalysisError(
                "distribution bucket probability must be a Fraction in [0, 1]"
            )


@dataclass(frozen=True, slots=True)
class EventPathGroupCoverage:
    """记录结构化事件元数据在正式图边路径组中的覆盖数量。

    这些字段是图元数据覆盖，不是样本频率，也不与战斗概率混为一谈。

    Args:
        total_edge_count: 原始状态图的正式边总数。
        matching_edge_count: 至少一条事件路径命中查询的边数。
        total_event_path_group_count: 全部正式边包含的替代事件路径组数量。
        matching_event_path_group_count: 至少一个事件命中查询的路径组数量。
    """

    total_edge_count: int
    matching_edge_count: int
    total_event_path_group_count: int
    matching_event_path_group_count: int

    def __post_init__(self) -> None:
        """校验边数和路径组数均非负且匹配数量不超过总量。"""
        for field_name, value in (
            ("total_edge_count", self.total_edge_count),
            ("matching_edge_count", self.matching_edge_count),
            ("total_event_path_group_count", self.total_event_path_group_count),
            (
                "matching_event_path_group_count",
                self.matching_event_path_group_count,
            ),
        ):
            if isinstance(value, bool) or value < 0:
                raise BattleEventAnalysisError(
                    f"{field_name} must be a non-negative integer"
                )
        if self.matching_edge_count > self.total_edge_count:
            raise BattleEventAnalysisError(
                "matching edge count cannot exceed total edge count"
            )
        if (
            self.matching_event_path_group_count
            > self.total_event_path_group_count
        ):
            raise BattleEventAnalysisError(
                "matching path group count cannot exceed total path group count"
            )


@dataclass(frozen=True, slots=True)
class KeyEventSummary:
    """汇总一个唯一类型化事件在多少图边路径组中出现。

    Args:
        event_type: 底层随机事件类别。
        battle_event_kind: 结构化业务事件类别；普通随机事件为 None。
        actor: 业务事件主体侧。
        target: 业务事件目标侧。
        move_id: 关联招式 ID。
        effect_identifier: 特性、道具、状态或效果来源标识。
        event_id: 原始类型化事件来源 ID。
        outcome_id: 原始类型化事件结果 ID。
        path_group_count: 包含该唯一事件的正式路径组数量。
    """

    event_type: TransitionEventType
    battle_event_kind: BattleEventKind | None
    actor: BattleSide | None
    target: BattleSide | None
    move_id: int | None
    effect_identifier: str | None
    event_id: str
    outcome_id: str
    path_group_count: int

    def __post_init__(self) -> None:
        """校验枚举、稳定标识和正路径组数量。"""
        if not isinstance(self.event_type, TransitionEventType):
            raise BattleEventAnalysisError(
                "key event type must be a TransitionEventType"
            )
        if self.battle_event_kind is not None and not isinstance(
            self.battle_event_kind,
            BattleEventKind,
        ):
            raise BattleEventAnalysisError(
                "battle_event_kind must be BattleEventKind or None"
            )
        for field_name, value in (
            ("event_id", self.event_id),
            ("outcome_id", self.outcome_id),
        ):
            if not value.strip():
                raise BattleEventAnalysisError(
                    f"key event {field_name} cannot be empty"
                )
        if isinstance(self.path_group_count, bool) or self.path_group_count <= 0:
            raise BattleEventAnalysisError(
                "key event path_group_count must be greater than 0"
            )


@dataclass(frozen=True, slots=True)
class BattleEventAnalysisComputationCost:
    """明确一次事件分析新增的有限产品图规模与精确求解次数。

    Args:
        original_node_count: 输入状态图的唯一节点数。
        original_edge_count: 输入状态图的正式边数。
        product_node_count: 事件历史乘积图的唯一节点数。
        product_edge_count: 事件历史乘积图的正式边数。
        exact_solver_run_count: 本次分析实际触发的精确图求解次数。
    """

    original_node_count: int
    original_edge_count: int
    product_node_count: int
    product_edge_count: int
    exact_solver_run_count: int

    def __post_init__(self) -> None:
        """校验图规模非负且精确求解至少执行一次。"""
        for field_name, value in (
            ("original_node_count", self.original_node_count),
            ("original_edge_count", self.original_edge_count),
            ("product_node_count", self.product_node_count),
            ("product_edge_count", self.product_edge_count),
        ):
            if isinstance(value, bool) or value < 0:
                raise BattleEventAnalysisError(
                    f"{field_name} must be a non-negative integer"
                )
        if (
            isinstance(self.exact_solver_run_count, bool)
            or self.exact_solver_run_count <= 0
        ):
            raise BattleEventAnalysisError(
                "exact_solver_run_count must be greater than 0"
            )


@dataclass(frozen=True, slots=True)
class BattleEventAnalysisArtifact:
    """把独立推演 revision、运行身份与完整状态图绑定为分析输入。

    Args:
        calculation_revision: 本次计算规则、数据和实现版本的稳定标识。
        inference_run_id: 一次独立图构建运行的唯一身份。
        graph: 已完成构建、SCC 分类且可由精确求解器消费的状态图。
    """

    calculation_revision: str
    inference_run_id: str
    graph: StateGraphBuildResult

    def __post_init__(self) -> None:
        """校验 revision、运行 ID 和完整图类型。"""
        for field_name, value in (
            ("calculation_revision", self.calculation_revision),
            ("inference_run_id", self.inference_run_id),
        ):
            if not value.strip() or value != value.strip():
                raise BattleEventAnalysisError(
                    f"{field_name} must be normalized non-empty text"
                )
        if not isinstance(self.graph, StateGraphBuildResult):
            raise BattleEventAnalysisError("graph must be a StateGraphBuildResult")


@dataclass(frozen=True, slots=True)
class BattleEventAnalysisResult:
    """保存事件 E 与观察方获胜 W 的精确联合和条件概率。

    Args:
        calculation_revision: 输入图的稳定计算 revision。
        inference_run_id: 输入图的独立推演运行 ID。
        observer: 获胜事件 W 使用的观察侧。
        query: 定义事件 E 的结构化查询。
        baseline_win_probability: 原图中观察方获胜概率。
        baseline_loss_probability: 原图中观察方失败概率。
        baseline_draw_probability: 原图中平局概率。
        event_probability: ``P(E)``。
        event_win_joint_probability: ``P(E ∩ W)``。
        win_given_event: ``P(W | E)`` 或零条件质量状态。
        win_given_not_event: ``P(W | ¬E)`` 或零条件质量状态。
        first_occurrence_distribution: 首次发生回合的完整精确分布。
        occurrence_count_distribution: 发生次数的完整精确分布。
        path_group_coverage: 类型化事件元数据在正式路径组中的覆盖。
        key_events: 命中查询的高频唯一结构化事件摘要。
        original_probability_preserved: 产品图是否严格保持原图结果概率。
        computation_cost: 产品图规模和精确求解次数。
    """

    calculation_revision: str
    inference_run_id: str
    observer: BattleSide
    query: BattleEventQuery
    baseline_win_probability: Fraction
    baseline_loss_probability: Fraction
    baseline_draw_probability: Fraction
    event_probability: Fraction
    event_win_joint_probability: Fraction
    win_given_event: ConditionalProbability
    win_given_not_event: ConditionalProbability
    first_occurrence_distribution: tuple[ProbabilityDistributionBucket, ...]
    occurrence_count_distribution: tuple[ProbabilityDistributionBucket, ...]
    path_group_coverage: EventPathGroupCoverage
    key_events: tuple[KeyEventSummary, ...]
    original_probability_preserved: bool
    computation_cost: BattleEventAnalysisComputationCost

    def __post_init__(self) -> None:
        """校验基线守恒、联合概率边界和分布总和。"""
        baseline_total = (
            self.baseline_win_probability
            + self.baseline_loss_probability
            + self.baseline_draw_probability
        )
        if baseline_total != Fraction(1):
            raise BattleEventAnalysisError(
                "baseline win, loss and draw probabilities must sum exactly to 1"
            )
        if not Fraction(0) <= self.event_probability <= Fraction(1):
            raise BattleEventAnalysisError("event_probability must be in [0, 1]")
        if not Fraction(0) <= self.event_win_joint_probability <= min(
            self.event_probability,
            self.baseline_win_probability,
        ):
            raise BattleEventAnalysisError(
                "event-win joint probability exceeds its marginals"
            )
        for distribution_name, buckets in (
            ("first occurrence", self.first_occurrence_distribution),
            ("occurrence count", self.occurrence_count_distribution),
        ):
            total = sum(
                (bucket.probability for bucket in buckets),
                start=Fraction(0),
            )
            if total != Fraction(1):
                raise BattleEventAnalysisError(
                    f"{distribution_name} distribution must sum exactly to 1"
                )
        if not self.original_probability_preserved:
            raise BattleEventAnalysisError(
                "event product graph changed original outcome probabilities"
            )


__all__ = [
    "BattleEventAnalysisArtifact",
    "BattleEventAnalysisComputationCost",
    "BattleEventAnalysisResult",
    "ConditionalProbability",
    "EventPathGroupCoverage",
    "KeyEventSummary",
    "ProbabilityDistributionBucket",
]
