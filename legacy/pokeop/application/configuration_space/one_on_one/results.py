"""定义通用 1v1 批量摘要、失败截断详情、进度和按需完整图边界。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Generic, TypeAlias, TypeVar

from pokeop.application.configuration_space.one_on_one.commands import (
    ConfigurationReference,
)
from pokeop.application.configuration_space.one_on_one.model_base import (
    ONE_ON_ONE_CONTRACT_VERSION,
    ConfigurationExecutionStatus,
    ConfigurationTaskStatus,
    ExactRatio,
    OneOnOneActionPolicy,
    OneOnOneConfigurationWeightAssumption,
    OneOnOneContractError,
    _is_integer,
    _require_configuration_id,
    _require_identity_text,
    _require_normalized_text,
    _require_positive_integer,
)


@dataclass(frozen=True, slots=True)
class GraphStatisticsSummary:
    """保存失败、截断或成功配置的轻量图规模，不包含完整状态图。"""

    node_count: int
    edge_count: int
    max_turn_number: int

    def __post_init__(self) -> None:
        """校验图规模统计均为非负整数。"""
        for field_name, value in (
            ("node_count", self.node_count),
            ("edge_count", self.edge_count),
            ("max_turn_number", self.max_turn_number),
        ):
            if not _is_integer(value) or value < 0:
                raise OneOnOneContractError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class SuccessfulConfigurationSummary:
    """保存一个成功配置的精确概率摘要，不持有完整状态图。"""

    configuration: ConfigurationReference
    configuration_weight: ExactRatio
    win_probability: ExactRatio
    loss_probability: ExactRatio
    draw_probability: ExactRatio
    graph_statistics: GraphStatisticsSummary
    status: ConfigurationExecutionStatus = ConfigurationExecutionStatus.SUCCESS

    def __post_init__(self) -> None:
        """校验成功状态和战斗概率总和。"""
        if not isinstance(self.configuration, ConfigurationReference):
            raise OneOnOneContractError(
                "successful summary requires ConfigurationReference"
            )
        if self.status is not ConfigurationExecutionStatus.SUCCESS:
            raise OneOnOneContractError("successful summary must use success status")
        total = (
            self.win_probability.value
            + self.loss_probability.value
            + self.draw_probability.value
        )
        if total != Fraction(1):
            raise OneOnOneContractError("successful battle probabilities must sum exactly to 1")


@dataclass(frozen=True, slots=True)
class FailedConfigurationDetail:
    """保存一个失败配置的可分页诊断，不让该配置从聚合分母中消失。"""

    configuration: ConfigurationReference
    configuration_weight: ExactRatio
    reason_code: str
    message: str
    graph_statistics: GraphStatisticsSummary | None = None
    status: ConfigurationExecutionStatus = ConfigurationExecutionStatus.FAILED

    def __post_init__(self) -> None:
        """校验失败状态和稳定诊断文本。"""
        if not isinstance(self.configuration, ConfigurationReference):
            raise OneOnOneContractError("failed detail requires ConfigurationReference")
        if self.status is not ConfigurationExecutionStatus.FAILED:
            raise OneOnOneContractError("failed detail must use failed status")
        _require_identity_text("reason_code", self.reason_code)
        _require_normalized_text("message", self.message)


@dataclass(frozen=True, slots=True)
class TruncatedConfigurationDetail:
    """保存触发运行保护的配置及轻量图统计，不把截断伪装为成功结果。"""

    configuration: ConfigurationReference
    configuration_weight: ExactRatio
    reason_codes: tuple[str, ...]
    graph_statistics: GraphStatisticsSummary
    status: ConfigurationExecutionStatus = ConfigurationExecutionStatus.TRUNCATED

    def __post_init__(self) -> None:
        """校验截断状态、原因集合和去重语义。"""
        if not isinstance(self.configuration, ConfigurationReference):
            raise OneOnOneContractError(
                "truncated detail requires ConfigurationReference"
            )
        if self.status is not ConfigurationExecutionStatus.TRUNCATED:
            raise OneOnOneContractError("truncated detail must use truncated status")
        reasons = tuple(self.reason_codes)
        if not reasons:
            raise OneOnOneContractError("truncated detail requires at least one reason code")
        if len(reasons) != len(set(reasons)):
            raise OneOnOneContractError("truncation reason codes must be unique")
        for reason in reasons:
            _require_identity_text("truncation reason code", reason)
        object.__setattr__(self, "reason_codes", tuple(sorted(reasons)))


ConfigurationExecutionResult: TypeAlias = (
    SuccessfulConfigurationSummary
    | FailedConfigurationDetail
    | TruncatedConfigurationDetail
)


@dataclass(frozen=True, slots=True)
class ConfigurationCoverageSummary:
    """分别记录成功、失败和截断配置的数量与权重覆盖。"""

    total_configuration_count: int
    success_count: int
    failed_count: int
    truncated_count: int
    success_weight: ExactRatio
    failed_weight: ExactRatio
    truncated_weight: ExactRatio

    def __post_init__(self) -> None:
        """校验最终数量守恒和配置权重总和为 1。"""
        _require_positive_integer("total_configuration_count", self.total_configuration_count)
        for field_name, value in (
            ("success_count", self.success_count),
            ("failed_count", self.failed_count),
            ("truncated_count", self.truncated_count),
        ):
            if not _is_integer(value) or value < 0:
                raise OneOnOneContractError(f"{field_name} must be a non-negative integer")
        terminal_count = self.success_count + self.failed_count + self.truncated_count
        if terminal_count != self.total_configuration_count:
            raise OneOnOneContractError(
                "configuration result counts must preserve the full denominator"
            )
        total_weight = (
            self.success_weight.value
            + self.failed_weight.value
            + self.truncated_weight.value
        )
        if total_weight != Fraction(1):
            raise OneOnOneContractError(
                "configuration result weights must sum exactly to 1"
            )
        expected_weights = (
            Fraction(self.success_count, self.total_configuration_count),
            Fraction(self.failed_count, self.total_configuration_count),
            Fraction(self.truncated_count, self.total_configuration_count),
        )
        actual_weights = (
            self.success_weight.value,
            self.failed_weight.value,
            self.truncated_weight.value,
        )
        if actual_weights != expected_weights:
            raise OneOnOneContractError(
                "uniform configuration-pair weights must match result counts"
            )


@dataclass(frozen=True, slots=True)
class BatchProbabilitySummary:
    """按原始配置总权重聚合胜、负、平与未解析质量。

    ``win_probability``、``loss_probability`` 和 ``draw_probability`` 不会在失败或截断后
    对成功子集重新归一化；四个字段始终以完整配置空间为分母并精确相加为 1。
    """

    win_probability: ExactRatio
    loss_probability: ExactRatio
    draw_probability: ExactRatio
    unresolved_configuration_weight: ExactRatio

    def __post_init__(self) -> None:
        """校验战斗概率与未解析配置权重共同守恒。"""
        total = (
            self.win_probability.value
            + self.loss_probability.value
            + self.draw_probability.value
            + self.unresolved_configuration_weight.value
        )
        if total != Fraction(1):
            raise OneOnOneContractError("batch probabilities and unresolved weight must sum to 1")


@dataclass(frozen=True, slots=True)
class MechanismCoverageSummary:
    """记录精确任务中被纳入、部分支持和不支持的机制标识。"""

    included: tuple[str, ...]
    excluded_partial: tuple[str, ...]
    excluded_unsupported: tuple[str, ...]

    def __post_init__(self) -> None:
        """规范化三个互斥机制集合并拒绝重复或交叉分类。"""
        normalized_groups: list[tuple[str, ...]] = []
        for field_name, values in (
            ("included", self.included),
            ("excluded_partial", self.excluded_partial),
            ("excluded_unsupported", self.excluded_unsupported),
        ):
            items = tuple(values)
            if len(items) != len(set(items)):
                raise OneOnOneContractError(f"{field_name} cannot contain duplicates")
            for item in items:
                _require_identity_text(field_name, item)
            normalized_groups.append(tuple(sorted(items)))
        included, partial, unsupported = (set(group) for group in normalized_groups)
        if included & partial or included & unsupported or partial & unsupported:
            raise OneOnOneContractError("mechanism coverage groups must be disjoint")
        object.__setattr__(self, "included", normalized_groups[0])
        object.__setattr__(self, "excluded_partial", normalized_groups[1])
        object.__setattr__(self, "excluded_unsupported", normalized_groups[2])


@dataclass(frozen=True, slots=True)
class OneOnOneBatchSummary:
    """保存批量任务的全局摘要，并明确不包含任何完整状态图。"""

    task_id: str
    contract_version: str
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    weight_assumption: OneOnOneConfigurationWeightAssumption
    attacker_policy: OneOnOneActionPolicy
    defender_policy: OneOnOneActionPolicy
    coverage: ConfigurationCoverageSummary
    probabilities: BatchProbabilitySummary
    mechanism_coverage: MechanismCoverageSummary
    top_configurations: tuple[SuccessfulConfigurationSummary, ...] = ()

    def __post_init__(self) -> None:
        """校验摘要身份、策略和未解析权重与覆盖字段一致。"""
        _require_identity_text("task_id", self.task_id)
        if self.contract_version != ONE_ON_ONE_CONTRACT_VERSION:
            raise OneOnOneContractError("unsupported one-on-one contract version")
        _require_identity_text("ruleset_id", self.ruleset_id)
        _require_positive_integer("version_group_id", self.version_group_id)
        _require_identity_text("calculation_revision", self.calculation_revision)
        if not isinstance(
            self.weight_assumption, OneOnOneConfigurationWeightAssumption
        ):
            raise OneOnOneContractError("weight_assumption must be explicit")
        if not isinstance(self.attacker_policy, OneOnOneActionPolicy):
            raise OneOnOneContractError("attacker_policy must be explicit")
        if not isinstance(self.defender_policy, OneOnOneActionPolicy):
            raise OneOnOneContractError("defender_policy must be explicit")
        unresolved = self.coverage.failed_weight.value + self.coverage.truncated_weight.value
        if self.probabilities.unresolved_configuration_weight.value != unresolved:
            raise OneOnOneContractError(
                "unresolved probability weight must equal failed plus truncated coverage"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationIssuePage:
    """保存失败与截断配置的分页结果，不携带完整状态图。"""

    task_id: str
    offset: int
    limit: int
    total: int
    items: tuple[FailedConfigurationDetail | TruncatedConfigurationDetail, ...]

    def __post_init__(self) -> None:
        """校验分页边界和条目类型。"""
        _require_identity_text("task_id", self.task_id)
        if not _is_integer(self.offset) or self.offset < 0:
            raise OneOnOneContractError("offset must be a non-negative integer")
        _require_positive_integer("limit", self.limit)
        if not _is_integer(self.total) or self.total < 0:
            raise OneOnOneContractError("total must be a non-negative integer")
        if len(self.items) > self.limit:
            raise OneOnOneContractError("issue page cannot contain more items than limit")
        if any(
            not isinstance(item, (FailedConfigurationDetail, TruncatedConfigurationDetail))
            for item in self.items
        ):
            raise OneOnOneContractError("issue page only accepts failed or truncated details")


@dataclass(frozen=True, slots=True)
class ConfigurationTaskProgress:
    """保存后台任务可轮询的数量进度和取消状态。"""

    task_id: str
    status: ConfigurationTaskStatus
    total_configuration_count: int
    processed_count: int
    success_count: int
    failed_count: int
    truncated_count: int
    cancellation_requested: bool = False

    def __post_init__(self) -> None:
        """校验进度数量守恒以及终态任务已处理完整分母。"""
        _require_identity_text("task_id", self.task_id)
        if not isinstance(self.status, ConfigurationTaskStatus):
            raise OneOnOneContractError("task status must be explicit")
        _require_positive_integer("total_configuration_count", self.total_configuration_count)
        for field_name, value in (
            ("processed_count", self.processed_count),
            ("success_count", self.success_count),
            ("failed_count", self.failed_count),
            ("truncated_count", self.truncated_count),
        ):
            if not _is_integer(value) or value < 0:
                raise OneOnOneContractError(f"{field_name} must be a non-negative integer")
        if self.success_count + self.failed_count + self.truncated_count != self.processed_count:
            raise OneOnOneContractError("processed_count must equal all terminal result counts")
        if self.processed_count > self.total_configuration_count:
            raise OneOnOneContractError("processed_count cannot exceed total_configuration_count")
        if not isinstance(self.cancellation_requested, bool):
            raise OneOnOneContractError("cancellation_requested must be bool")
        if (
            self.status is ConfigurationTaskStatus.COMPLETED
            and self.processed_count != self.total_configuration_count
        ):
            raise OneOnOneContractError(
                "completed tasks must process the full configuration denominator"
            )

    @property
    def progress(self) -> ExactRatio:
        """返回已处理配置占完整配置空间的精确比例。"""
        return ExactRatio(self.processed_count, self.total_configuration_count)


GraphArtifactT = TypeVar("GraphArtifactT")


@dataclass(frozen=True, slots=True)
class OnDemandGraphResult(Generic[GraphArtifactT]):
    """保存按需重算返回的完整图，并与轻量批量摘要隔离。

    Args:
        configuration_id: 与批量结果一致的规范化配置 ID。
        calculation_revision: 生成图时使用的计算修订。
        root_node_id: 完整图的根节点 ID，必须为非负整数。
        graph_artifact: 仅按需结果持有的完整状态图对象。
    """

    configuration_id: str
    calculation_revision: str
    root_node_id: int
    graph_artifact: GraphArtifactT

    def __post_init__(self) -> None:
        """校验完整图结果可以绑定到唯一配置和计算修订。

        Raises:
            OneOnOneContractError: 身份、根节点或图对象不合法时抛出。
        """
        _require_configuration_id(self.configuration_id)
        _require_identity_text("calculation_revision", self.calculation_revision)
        if not _is_integer(self.root_node_id) or self.root_node_id < 0:
            raise OneOnOneContractError("root_node_id must be a non-negative integer")
        if self.graph_artifact is None:
            raise OneOnOneContractError("on-demand graph result requires graph_artifact")


@dataclass(frozen=True, slots=True)
class OnDemandGraphRequest:
    """声明从批量结果进入单配置完整状态图的按需重算请求。"""

    task_id: str
    configuration_id: str
    calculation_revision: str
    max_nodes: int
    max_edges: int
    max_turns: int

    def __post_init__(self) -> None:
        """校验请求可以定位相同计算修订下的单配置并应用显式运行保护。"""
        _require_identity_text("task_id", self.task_id)
        _require_configuration_id(self.configuration_id)
        _require_identity_text("calculation_revision", self.calculation_revision)
        _require_positive_integer("max_nodes", self.max_nodes)
        _require_positive_integer("max_edges", self.max_edges)
        _require_positive_integer("max_turns", self.max_turns)


__all__ = [
    "ConfigurationExecutionResult",
    "GraphStatisticsSummary",
    "SuccessfulConfigurationSummary",
    "FailedConfigurationDetail",
    "TruncatedConfigurationDetail",
    "ConfigurationCoverageSummary",
    "BatchProbabilitySummary",
    "MechanismCoverageSummary",
    "OneOnOneBatchSummary",
    "ConfigurationIssuePage",
    "ConfigurationTaskProgress",
    "OnDemandGraphResult",
    "OnDemandGraphRequest",
]
