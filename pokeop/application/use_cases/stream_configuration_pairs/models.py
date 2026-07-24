"""定义配置对流式执行的命令、结果和可替换端口。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Protocol, runtime_checkable

from pokeop.application.configuration_space import (
    BattleConfiguration,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    ExpectedTurnsStatus,
)
from pokeop.application.solver.models import StateGraphBuildResult, StateGraphLimits
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules


class ConfigurationPairStreamError(ValueError):
    """表示流式执行命令或精确聚合结果违反稳定合同。"""


class ConfigurationPairExecutionStatus(str, Enum):
    """表示一个配置对的成功、截断或失败状态。"""

    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    FAILED = "failed"


class ConfigurationPairStopReason(str, Enum):
    """表示流式执行停止领取新配置对的稳定原因。"""

    COMPLETED = "completed"
    CONFIGURATION_PAIR_LIMIT = "configuration-pair-limit"
    CUMULATIVE_NODE_LIMIT = "cumulative-node-limit"
    CUMULATIVE_EDGE_LIMIT = "cumulative-edge-limit"
    MAX_FAILURES = "max-failures"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class NormalizedBattleConfiguration:
    """保存一侧已完成合法性与行为归并的配置候选。

    Args:
        configuration_id: 调用方提供的稳定配置 ID，用于组成幂等配置对 ID。
        configuration: 已完成 version-aware 读取和机制准入的单边配置。
        weight: 当前配置在本侧候选空间中的精确权重。
    """

    configuration_id: str
    configuration: PokemonBattleConfiguration
    weight: Fraction

    def __post_init__(self) -> None:
        """校验 ID、配置对象和精确权重可安全参与笛卡尔积。"""
        if (
            not isinstance(self.configuration_id, str)
            or not self.configuration_id
            or self.configuration_id != self.configuration_id.strip()
        ):
            raise ConfigurationPairStreamError(
                "configuration_id must be non-empty and normalized"
            )
        if not isinstance(self.configuration, PokemonBattleConfiguration):
            raise ConfigurationPairStreamError(
                "configuration must be PokemonBattleConfiguration"
            )
        if not isinstance(self.weight, Fraction) or not 0 < self.weight <= 1:
            raise ConfigurationPairStreamError(
                "configuration weight must be a Fraction in (0, 1]"
            )


def equally_weighted_configurations(
    configurations: tuple[tuple[str, PokemonBattleConfiguration], ...],
) -> tuple[NormalizedBattleConfiguration, ...]:
    """把已规范化配置集合转换为配置层等权候选。

    Args:
        configurations: ``(稳定配置 ID, 单边配置)`` 元组；集合不能为空。

    Returns:
        每项权重严格为 ``1 / 配置数`` 的规范化候选元组。

    Raises:
        ConfigurationPairStreamError: 输入为空时抛出。
    """
    if not configurations:
        raise ConfigurationPairStreamError("configurations must not be empty")
    weight = Fraction(1, len(configurations))
    return tuple(
        NormalizedBattleConfiguration(
            configuration_id=configuration_id,
            configuration=configuration,
            weight=weight,
        )
        for configuration_id, configuration in configurations
    )


@dataclass(frozen=True, slots=True)
class ConfigurationPairWorkItem:
    """保存惰性生成后交给单配置图执行器的稳定工作项。

    Args:
        pair_id: 由双方配置 ID 计算得到的稳定幂等标识。
        attacker_configuration_id: 攻击方单边配置 ID。
        defender_configuration_id: 防守方单边配置 ID。
        configuration_weight: 双方配置权重乘积，不包含战斗随机概率。
        configuration: 可直接构建初始战斗状态的双方配置。
    """

    pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    configuration_weight: Fraction
    configuration: BattleConfiguration


@dataclass(frozen=True, slots=True)
class StreamConfigurationPairsCommand:
    """声明一次同步、可组合的配置对流式精确执行。

    Args:
        rules: 全部配置共享的规则集、version group、等级和回合语义。
        attacker_configurations: 攻击方规范化配置；输入顺序不影响结果。
        defender_configurations: 防守方规范化配置；输入顺序不影响结果。
        attacker_policy: 全部配置对共享的攻击方行动策略。
        defender_policy: 全部配置对共享的防守方行动策略。
        observer: 胜负概率采用的固定观察方。
        graph_limits: 每个配置对独立应用的节点、边和回合上限。
        max_configuration_pairs: 最多执行配置对数量；None 表示不限制。
        cumulative_node_limit: 累计节点达到该值后停止领取新配置。
        cumulative_edge_limit: 累计边达到该值后停止领取新配置。
        max_failures: 失败结果达到该数量后停止领取新配置。
        top_k: 每类 Top-K 指标保留的轻量条目数量。
    """

    rules: BattleInferenceRules
    attacker_configurations: tuple[NormalizedBattleConfiguration, ...]
    defender_configurations: tuple[NormalizedBattleConfiguration, ...]
    attacker_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    defender_policy: BattleActionPolicyKind = BattleActionPolicyKind.FIRST_LEGAL
    observer: BattleSide = BattleSide.ATTACKER
    graph_limits: StateGraphLimits = StateGraphLimits(
        max_nodes=20_000,
        max_edges=80_000,
    )
    max_configuration_pairs: int | None = None
    cumulative_node_limit: int | None = None
    cumulative_edge_limit: int | None = None
    max_failures: int | None = None
    top_k: int = 10

    def __post_init__(self) -> None:
        """校验批量合同，并按配置 ID 固定双方执行顺序。"""
        if not isinstance(self.rules, BattleInferenceRules):
            raise ConfigurationPairStreamError("rules must be BattleInferenceRules")
        if not self.attacker_configurations or not self.defender_configurations:
            raise ConfigurationPairStreamError(
                "attacker and defender configurations must not be empty"
            )
        if not isinstance(self.attacker_policy, BattleActionPolicyKind):
            raise ConfigurationPairStreamError("attacker_policy must be explicit")
        if not isinstance(self.defender_policy, BattleActionPolicyKind):
            raise ConfigurationPairStreamError("defender_policy must be explicit")
        if not isinstance(self.observer, BattleSide):
            raise ConfigurationPairStreamError("observer must be BattleSide")
        if not isinstance(self.graph_limits, StateGraphLimits):
            raise ConfigurationPairStreamError("graph_limits must be StateGraphLimits")

        object.__setattr__(
            self,
            "attacker_configurations",
            _validate_configuration_side(
                "attacker",
                self.attacker_configurations,
                self.rules,
            ),
        )
        object.__setattr__(
            self,
            "defender_configurations",
            _validate_configuration_side(
                "defender",
                self.defender_configurations,
                self.rules,
            ),
        )
        for field_name, value in (
            ("max_configuration_pairs", self.max_configuration_pairs),
            ("cumulative_node_limit", self.cumulative_node_limit),
            ("cumulative_edge_limit", self.cumulative_edge_limit),
            ("max_failures", self.max_failures),
        ):
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise ConfigurationPairStreamError(
                    f"{field_name} must be greater than 0"
                )
        if isinstance(self.top_k, bool) or self.top_k <= 0:
            raise ConfigurationPairStreamError("top_k must be greater than 0")

    @property
    def total_pair_count(self) -> int:
        """返回完整候选笛卡尔积包含的配置对数量。"""
        return len(self.attacker_configurations) * len(self.defender_configurations)


@dataclass(frozen=True, slots=True)
class ConfigurationPairGraphArtifact:
    """暂时持有单配置完整状态图和求解结果。

    该对象只允许存在于单次配置求解调用栈内。sink 和最终聚合不得持有 graph。

    Args:
        graph: 本配置对的完整或显式截断状态图。
        solve_result: 精确 solver 返回的成功或类型化未完成结果。
    """

    graph: StateGraphBuildResult
    solve_result: BattleGraphSolveResult


@runtime_checkable
class ConfigurationPairGraphExecutor(Protocol):
    """把一个规范化配置对构建并求解为短生命周期图 artifact。"""

    def execute(
        self,
        work_item: ConfigurationPairWorkItem,
        *,
        rules: BattleInferenceRules,
        attacker_policy: BattleActionPolicyKind,
        defender_policy: BattleActionPolicyKind,
        observer: BattleSide,
        graph_limits: StateGraphLimits,
    ) -> ConfigurationPairGraphArtifact:
        """构建并求解一个配置对。

        Args:
            work_item: 当前待执行的稳定配置对工作项。
            rules: 当前规则轴。
            attacker_policy: 攻击方行动策略。
            defender_policy: 防守方行动策略。
            observer: 胜负概率观察方。
            graph_limits: 当前配置对独立使用的图运行保护。

        Returns:
            只在调用方提取摘要前保留完整图的短生命周期 artifact。
        """


@dataclass(frozen=True, slots=True)
class ConfigurationPairExecutionResult:
    """保存 sink 可持续写出的单配置轻量结果。

    配置权重与战斗随机概率分别存储；失败和截断结果不得暴露部分概率。
    """

    pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]
    configuration_weight: Fraction
    status: ConfigurationPairExecutionStatus
    win_probability: Fraction | None
    loss_probability: Fraction | None
    draw_probability: Fraction | None
    expected_turns: Fraction | None
    expected_turns_status: ExpectedTurnsStatus
    node_count: int
    edge_count: int
    scc_count: int
    max_turn_number: int
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """保证成功概率守恒，未完成结果不伪造部分概率。"""
        if not isinstance(self.status, ConfigurationPairExecutionStatus):
            raise ConfigurationPairStreamError("pair status must be explicit")
        if not isinstance(self.configuration_weight, Fraction) or not (
            0 < self.configuration_weight <= 1
        ):
            raise ConfigurationPairStreamError(
                "configuration_weight must be a Fraction in (0, 1]"
            )
        if not isinstance(self.expected_turns_status, ExpectedTurnsStatus):
            raise ConfigurationPairStreamError(
                "expected_turns_status must be explicit"
            )
        if self.status is ConfigurationPairExecutionStatus.SUCCEEDED:
            self._validate_success()
        else:
            self._validate_unfinished()
        if any(
            isinstance(value, bool) or value < 0
            for value in (
                self.node_count,
                self.edge_count,
                self.scc_count,
                self.max_turn_number,
            )
        ):
            raise ConfigurationPairStreamError("graph counts must be non-negative")

    def _validate_success(self) -> None:
        """校验成功结果的概率和期望回合语义。"""
        probabilities = (
            self.win_probability,
            self.loss_probability,
            self.draw_probability,
        )
        if any(not isinstance(value, Fraction) for value in probabilities):
            raise ConfigurationPairStreamError(
                "successful pair result requires exact probabilities"
            )
        typed = tuple(value for value in probabilities if value is not None)
        if any(value < 0 or value > 1 for value in typed):
            raise ConfigurationPairStreamError(
                "successful pair probabilities must be in [0, 1]"
            )
        if sum(typed, start=Fraction(0)) != Fraction(1):
            raise ConfigurationPairStreamError(
                "successful pair probabilities must sum exactly to 1"
            )
        if self.expected_turns_status is ExpectedTurnsStatus.FINITE:
            if not isinstance(self.expected_turns, Fraction) or self.expected_turns < 0:
                raise ConfigurationPairStreamError(
                    "finite expected turns must be a non-negative Fraction"
                )
        elif self.expected_turns_status is ExpectedTurnsStatus.INFINITE:
            if self.expected_turns is not None:
                raise ConfigurationPairStreamError(
                    "infinite expected turns cannot carry a value"
                )
        else:
            raise ConfigurationPairStreamError(
                "successful pair result cannot have unavailable expected turns"
            )

    def _validate_unfinished(self) -> None:
        """校验失败或截断结果没有泄漏不可信部分概率。"""
        if any(
            value is not None
            for value in (
                self.win_probability,
                self.loss_probability,
                self.draw_probability,
                self.expected_turns,
            )
        ):
            raise ConfigurationPairStreamError(
                "unfinished pair result cannot expose partial probabilities"
            )
        if self.expected_turns_status is not ExpectedTurnsStatus.UNAVAILABLE:
            raise ConfigurationPairStreamError(
                "unfinished pair result requires unavailable expected turns"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationPairProgress:
    """记录配置数量和累计图资源两条独立进度轴。"""

    processed_pair_count: int
    total_pair_count: int
    succeeded_count: int
    truncated_count: int
    failed_count: int
    attempted_weight: Fraction
    completed_weight: Fraction
    cumulative_node_count: int
    cumulative_edge_count: int


@dataclass(frozen=True, slots=True)
class ConfigurationPairRankingEntry:
    """保存 Top-K 指标所需且不引用完整状态图的成功配置摘要。"""

    pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]
    win_probability: Fraction
    loss_probability: Fraction
    draw_probability: Fraction
    expected_turns: Fraction | None
    node_count: int
    edge_count: int


@dataclass(frozen=True, slots=True)
class FractionComplexitySummary:
    """记录流式 Fraction 聚合期间分子和分母的位数增长。"""

    observed_fraction_count: int
    max_numerator_bits: int
    max_denominator_bits: int
    final_win_numerator_bits: int
    final_win_denominator_bits: int
    final_loss_numerator_bits: int
    final_loss_denominator_bits: int
    final_draw_numerator_bits: int
    final_draw_denominator_bits: int


@dataclass(frozen=True, slots=True)
class ConfigurationPairAggregate:
    """保存一次流式批量执行的精确覆盖和资源聚合结果。

    概率字段以完整配置空间为分母。失败、截断和未执行权重不会被重新归一化，
    因此胜负平加总严格等于 ``completed_weight``。
    """

    stop_reason: ConfigurationPairStopReason
    total_pair_count: int
    processed_pair_count: int
    unprocessed_pair_count: int
    succeeded_count: int
    truncated_count: int
    failed_count: int
    attempted_weight: Fraction
    completed_weight: Fraction
    weighted_win_probability: Fraction
    weighted_loss_probability: Fraction
    weighted_draw_probability: Fraction
    cumulative_node_count: int
    cumulative_edge_count: int
    top_win_probability: tuple[ConfigurationPairRankingEntry, ...]
    top_expected_turns: tuple[ConfigurationPairRankingEntry, ...]
    top_node_count: tuple[ConfigurationPairRankingEntry, ...]
    fraction_complexity: FractionComplexitySummary

    def __post_init__(self) -> None:
        """校验配置计数、覆盖权重和未归一化概率严格一致。"""
        if self.processed_pair_count + self.unprocessed_pair_count != self.total_pair_count:
            raise ConfigurationPairStreamError("pair counts must cover the full space")
        if (
            self.succeeded_count + self.truncated_count + self.failed_count
            != self.processed_pair_count
        ):
            raise ConfigurationPairStreamError(
                "pair statuses must sum to processed_pair_count"
            )
        probability_total = (
            self.weighted_win_probability
            + self.weighted_loss_probability
            + self.weighted_draw_probability
        )
        if probability_total != self.completed_weight:
            raise ConfigurationPairStreamError(
                "weighted probabilities must sum exactly to completed_weight"
            )
        if not 0 <= self.completed_weight <= self.attempted_weight <= 1:
            raise ConfigurationPairStreamError(
                "coverage weights must satisfy completed <= attempted <= 1"
            )


@runtime_checkable
class ConfigurationPairResultSink(Protocol):
    """持续接收单配置结果，并在执行结束时接收最终聚合。"""

    def write_result(self, result: ConfigurationPairExecutionResult) -> None:
        """写入一个成功、截断或失败结果。"""

    def write_final(self, aggregate: ConfigurationPairAggregate) -> None:
        """写入当前批次的最终部分或完整聚合。"""


@runtime_checkable
class ProgressSink(Protocol):
    """接收配置数量与累计节点、边资源进度。"""

    def write_progress(self, progress: ConfigurationPairProgress) -> None:
        """写入完成一个配置对后的最新进度快照。"""


@runtime_checkable
class CancellationToken(Protocol):
    """在领取下一个配置对前提供同步取消检查。"""

    def is_cancelled(self) -> bool:
        """返回调用方是否已经请求停止领取新配置。"""


@dataclass(frozen=True, slots=True)
class DiscardConfigurationPairResultSink:
    """丢弃逐项结果和最终聚合的默认 sink。"""

    def write_result(self, result: ConfigurationPairExecutionResult) -> None:
        """接收但不保存单配置结果。"""

    def write_final(self, aggregate: ConfigurationPairAggregate) -> None:
        """接收但不保存最终聚合。"""


@dataclass(frozen=True, slots=True)
class DiscardProgressSink:
    """丢弃进度快照的默认 sink。"""

    def write_progress(self, progress: ConfigurationPairProgress) -> None:
        """接收但不保存进度快照。"""


@dataclass(frozen=True, slots=True)
class NeverCancelledToken:
    """表示同步任务不会由外部请求取消的默认 token。"""

    def is_cancelled(self) -> bool:
        """固定返回 False。"""
        return False


def _validate_configuration_side(
    side: str,
    configurations: tuple[NormalizedBattleConfiguration, ...],
    rules: BattleInferenceRules,
) -> tuple[NormalizedBattleConfiguration, ...]:
    """校验同侧配置规则轴、ID 和权重，并返回稳定排序结果。

    Args:
        side: 用于错误诊断的 attacker 或 defender 标识。
        configurations: 待校验的一侧规范化配置。
        rules: 全批次共享规则轴。

    Returns:
        按稳定配置 ID 升序排列的不可变配置元组。
    """
    if any(not isinstance(item, NormalizedBattleConfiguration) for item in configurations):
        raise ConfigurationPairStreamError(
            f"{side} configurations must be NormalizedBattleConfiguration"
        )
    for item in configurations:
        configuration = item.configuration
        if (
            configuration.ruleset_id != rules.ruleset_id
            or configuration.version_group_id != rules.version_group_id
            or configuration.level != rules.level
        ):
            raise ConfigurationPairStreamError(
                f"{side} configuration {item.configuration_id!r} does not match rules"
            )
    identifiers = tuple(item.configuration_id for item in configurations)
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationPairStreamError(f"{side} configuration ids must be unique")
    total_weight = sum((item.weight for item in configurations), start=Fraction(0))
    if total_weight != Fraction(1):
        raise ConfigurationPairStreamError(
            f"{side} configuration weights must sum exactly to 1"
        )
    return tuple(sorted(configurations, key=lambda item: item.configuration_id))


__all__ = [
    "CancellationToken",
    "ConfigurationPairAggregate",
    "ConfigurationPairExecutionResult",
    "ConfigurationPairExecutionStatus",
    "ConfigurationPairGraphArtifact",
    "ConfigurationPairGraphExecutor",
    "ConfigurationPairProgress",
    "ConfigurationPairRankingEntry",
    "ConfigurationPairResultSink",
    "ConfigurationPairStopReason",
    "ConfigurationPairStreamError",
    "ConfigurationPairWorkItem",
    "DiscardConfigurationPairResultSink",
    "DiscardProgressSink",
    "FractionComplexitySummary",
    "NeverCancelledToken",
    "NormalizedBattleConfiguration",
    "ProgressSink",
    "StreamConfigurationPairsCommand",
    "equally_weighted_configurations",
]
