"""按配置对原始权重汇总战斗事件分析结果。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from .models import BattleEventAnalysisError, BattleEventAnalysisResult


@dataclass(frozen=True, slots=True)
class ConfigurationEventAnalysisGroup:
    """绑定一个配置对权重与其独立战斗事件分析结果。

    Args:
        configuration_id: 配置对的稳定唯一标识。
        configuration_weight: 该配置对在完整配置空间中的原始权重。
        analysis: 该配置内部按战斗随机概率计算的事件分析结果。
    """

    configuration_id: str
    configuration_weight: Fraction
    analysis: BattleEventAnalysisResult

    def __post_init__(self) -> None:
        """校验配置身份、正权重和分析结果类型。"""
        if not self.configuration_id.strip() or (
            self.configuration_id != self.configuration_id.strip()
        ):
            raise BattleEventAnalysisError(
                "configuration_id must be normalized non-empty text"
            )
        if not isinstance(self.configuration_weight, Fraction) or not (
            Fraction(0) < self.configuration_weight <= Fraction(1)
        ):
            raise BattleEventAnalysisError(
                "configuration_weight must be a Fraction in (0, 1]"
            )
        if not isinstance(self.analysis, BattleEventAnalysisResult):
            raise BattleEventAnalysisError(
                "analysis must be a BattleEventAnalysisResult"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationEventCoverage:
    """单独记录配置数量/权重覆盖，不冒充战斗随机概率。

    Args:
        total_configuration_count: 原始配置空间总配置对数量。
        analyzed_configuration_count: 成功完成事件分析的配置对数量。
        event_possible_configuration_count: ``P(E) > 0`` 的配置对数量。
        analyzed_configuration_weight: 已分析配置占原始配置分母的权重。
        event_possible_configuration_weight: 事件可能配置占原始分母的权重。
        unresolved_configuration_weight: 失败或截断配置仍占用的原始权重。
    """

    total_configuration_count: int
    analyzed_configuration_count: int
    event_possible_configuration_count: int
    analyzed_configuration_weight: Fraction
    event_possible_configuration_weight: Fraction
    unresolved_configuration_weight: Fraction

    def __post_init__(self) -> None:
        """校验配置数量关系和三类权重边界。"""
        if (
            isinstance(self.total_configuration_count, bool)
            or self.total_configuration_count <= 0
        ):
            raise BattleEventAnalysisError(
                "total_configuration_count must be greater than 0"
            )
        for field_name, value in (
            ("analyzed_configuration_count", self.analyzed_configuration_count),
            (
                "event_possible_configuration_count",
                self.event_possible_configuration_count,
            ),
        ):
            if isinstance(value, bool) or value < 0:
                raise BattleEventAnalysisError(
                    f"{field_name} must be a non-negative integer"
                )
        if self.analyzed_configuration_count > self.total_configuration_count:
            raise BattleEventAnalysisError(
                "analyzed configuration count cannot exceed total count"
            )
        if (
            self.event_possible_configuration_count
            > self.analyzed_configuration_count
        ):
            raise BattleEventAnalysisError(
                "event-possible count cannot exceed analyzed count"
            )
        for field_name, value in (
            ("analyzed_configuration_weight", self.analyzed_configuration_weight),
            (
                "event_possible_configuration_weight",
                self.event_possible_configuration_weight,
            ),
            (
                "unresolved_configuration_weight",
                self.unresolved_configuration_weight,
            ),
        ):
            if not isinstance(value, Fraction) or not Fraction(0) <= value <= 1:
                raise BattleEventAnalysisError(
                    f"{field_name} must be a Fraction in [0, 1]"
                )
        if (
            self.event_possible_configuration_weight
            > self.analyzed_configuration_weight
        ):
            raise BattleEventAnalysisError(
                "event-possible weight cannot exceed analyzed weight"
            )
        if (
            self.analyzed_configuration_weight
            + self.unresolved_configuration_weight
            != Fraction(1)
        ):
            raise BattleEventAnalysisError(
                "analyzed and unresolved configuration weights must sum to 1"
            )


@dataclass(frozen=True, slots=True)
class WeightedConfigurationEventMetrics:
    """按配置权重混合各配置内部战斗概率后的事件指标。

    Args:
        event_probability: 以完整配置空间为分母的加权 ``P(E)``。
        event_win_joint_probability: 以完整配置空间为分母的加权 ``P(E ∩ W)``。
    """

    event_probability: Fraction
    event_win_joint_probability: Fraction

    def __post_init__(self) -> None:
        """校验加权事件概率边界和联合概率从属关系。"""
        for field_name, value in (
            ("event_probability", self.event_probability),
            ("event_win_joint_probability", self.event_win_joint_probability),
        ):
            if not isinstance(value, Fraction) or not Fraction(0) <= value <= 1:
                raise BattleEventAnalysisError(
                    f"weighted {field_name} must be a Fraction in [0, 1]"
                )
        if self.event_win_joint_probability > self.event_probability:
            raise BattleEventAnalysisError(
                "weighted event-win joint probability cannot exceed event probability"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationEventAnalysisSummary:
    """保存配置层覆盖和战斗层事件概率两个互不混淆的结果区域。

    Args:
        groups: 每个已分析配置的原始权重和内部事件结果。
        coverage: 配置数量与配置权重覆盖。
        weighted_metrics: 配置权重混合后的战斗事件概率。
    """

    groups: tuple[ConfigurationEventAnalysisGroup, ...]
    coverage: ConfigurationEventCoverage
    weighted_metrics: WeightedConfigurationEventMetrics

    def __post_init__(self) -> None:
        """校验分组数量与覆盖摘要一致。"""
        if any(
            not isinstance(group, ConfigurationEventAnalysisGroup)
            for group in self.groups
        ):
            raise BattleEventAnalysisError(
                "groups must contain ConfigurationEventAnalysisGroup values"
            )
        if len(self.groups) != self.coverage.analyzed_configuration_count:
            raise BattleEventAnalysisError(
                "configuration groups must match analyzed coverage count"
            )


def aggregate_configuration_event_analyses(
    groups: Iterable[ConfigurationEventAnalysisGroup],
    *,
    total_configuration_count: int,
    unresolved_configuration_weight: Fraction = Fraction(0),
) -> ConfigurationEventAnalysisSummary:
    """按配置权重汇总事件指标，同时保留配置覆盖分母。

    Args:
        groups: 已成功独立推演并完成事件分析的配置组。
        total_configuration_count: 原始配置空间总配置对数量，包含失败或截断项。
        unresolved_configuration_weight: 失败或截断配置仍占用的原始配置权重。

    Returns:
        配置覆盖和配置权重混合战斗概率明确分离的摘要。
    """
    materialized = tuple(groups)
    if isinstance(total_configuration_count, bool) or total_configuration_count <= 0:
        raise BattleEventAnalysisError(
            "total_configuration_count must be greater than 0"
        )
    if len(materialized) > total_configuration_count:
        raise BattleEventAnalysisError(
            "analyzed configuration count cannot exceed total count"
        )
    if len({group.configuration_id for group in materialized}) != len(materialized):
        raise BattleEventAnalysisError("configuration IDs must be unique")
    if not isinstance(unresolved_configuration_weight, Fraction) or not (
        Fraction(0) <= unresolved_configuration_weight <= Fraction(1)
    ):
        raise BattleEventAnalysisError(
            "unresolved_configuration_weight must be a Fraction in [0, 1]"
        )
    if materialized:
        first = materialized[0].analysis
        for group in materialized[1:]:
            analysis = group.analysis
            if analysis.observer is not first.observer or analysis.query != first.query:
                raise BattleEventAnalysisError(
                    "configuration analyses must share observer and event query"
                )
    analyzed_weight = sum(
        (group.configuration_weight for group in materialized),
        start=Fraction(0),
    )
    if analyzed_weight + unresolved_configuration_weight != Fraction(1):
        raise BattleEventAnalysisError(
            "analyzed and unresolved configuration weights must sum exactly to 1"
        )
    event_possible = tuple(
        group for group in materialized if group.analysis.event_probability > 0
    )
    weighted_event_probability = sum(
        (
            group.configuration_weight * group.analysis.event_probability
            for group in materialized
        ),
        start=Fraction(0),
    )
    weighted_joint_probability = sum(
        (
            group.configuration_weight
            * group.analysis.event_win_joint_probability
            for group in materialized
        ),
        start=Fraction(0),
    )
    return ConfigurationEventAnalysisSummary(
        groups=materialized,
        coverage=ConfigurationEventCoverage(
            total_configuration_count=total_configuration_count,
            analyzed_configuration_count=len(materialized),
            event_possible_configuration_count=len(event_possible),
            analyzed_configuration_weight=analyzed_weight,
            event_possible_configuration_weight=sum(
                (group.configuration_weight for group in event_possible),
                start=Fraction(0),
            ),
            unresolved_configuration_weight=unresolved_configuration_weight,
        ),
        weighted_metrics=WeightedConfigurationEventMetrics(
            event_probability=weighted_event_probability,
            event_win_joint_probability=weighted_joint_probability,
        ),
    )


__all__ = [
    "ConfigurationEventAnalysisGroup",
    "ConfigurationEventAnalysisSummary",
    "ConfigurationEventCoverage",
    "WeightedConfigurationEventMetrics",
    "aggregate_configuration_event_analyses",
]
