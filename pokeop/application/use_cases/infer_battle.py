from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Generic, TypeVar

from pokeop.domain.battle.action_policy import ActionPolicy
from pokeop.domain.battle.inference_outcome import (
    BattleSide,
    TerminalOutcome,
    TerminationReason,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


ConfigurationT = TypeVar("ConfigurationT")
ActionT = TypeVar("ActionT")
PolicyActionT = TypeVar("PolicyActionT")


class InvalidBattleInferenceContract(ValueError):
    """表示 application 推演命令或结果 DTO 违反稳定合同。"""


@dataclass(frozen=True, slots=True)
class BattleInferenceCommand(Generic[ConfigurationT, ActionT]):
    """固定双方配置、规则和行动策略的一次 1v1 推演命令。

    配置类型保持泛型，等待状态模型 Issue 定义 `PokemonSpec` 后再具体化；这个边界避免
    当前合同提前发明另一套宝可梦配置对象。行动策略只接收后续回合内核提供的合法行动。
    """

    rules: BattleInferenceRules
    attacker_configuration: ConfigurationT
    defender_configuration: ConfigurationT
    attacker_policy: ActionPolicy[ActionT]
    defender_policy: ActionPolicy[ActionT]
    observer: BattleSide = BattleSide.ATTACKER

    def __post_init__(self) -> None:
        if not isinstance(self.rules, BattleInferenceRules):
            raise InvalidBattleInferenceContract(
                "rules must be a BattleInferenceRules instance"
            )
        if self.attacker_configuration is None or self.defender_configuration is None:
            raise InvalidBattleInferenceContract(
                "attacker and defender configurations are required"
            )
        if not isinstance(self.attacker_policy, ActionPolicy):
            raise InvalidBattleInferenceContract(
                "attacker_policy must implement ActionPolicy"
            )
        if not isinstance(self.defender_policy, ActionPolicy):
            raise InvalidBattleInferenceContract(
                "defender_policy must implement ActionPolicy"
            )
        if not isinstance(self.observer, BattleSide):
            raise InvalidBattleInferenceContract("observer must be a BattleSide")


@dataclass(frozen=True, slots=True)
class BattleProbability:
    """固定配置与固定行动策略下的精确战斗结果概率。"""

    value: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.value, Fraction):
            raise InvalidBattleInferenceContract(
                "battle probability must use fractions.Fraction"
            )
        if not 0 <= self.value <= 1:
            raise InvalidBattleInferenceContract(
                "battle probability must be in the interval [0, 1]"
            )


@dataclass(frozen=True, slots=True)
class ConfigurationCoverage:
    """本次枚举覆盖的配置数量比例，不代表真实环境胜率。"""

    covered_configurations: int
    total_configurations: int

    def __post_init__(self) -> None:
        if self.total_configurations <= 0:
            raise InvalidBattleInferenceContract(
                "total_configurations must be greater than 0"
            )
        if not 0 <= self.covered_configurations <= self.total_configurations:
            raise InvalidBattleInferenceContract(
                "covered_configurations must be between 0 and total_configurations"
            )

    @property
    def coverage_ratio(self) -> Fraction:
        """返回配置覆盖率；该值不得命名或解释为战斗胜率。"""
        return Fraction(self.covered_configurations, self.total_configurations)


class ConfigurationWeightSource(str, Enum):
    """跨配置汇总时权重的来源与解释边界。"""

    FIXED_CONFIGURATION = "fixed-configuration"
    UNIFORM_ENUMERATION = "uniform-enumeration"
    EXPLICIT_INPUT_WEIGHTS = "explicit-input-weights"
    EXTERNAL_USAGE_DATA = "external-usage-data"


@dataclass(frozen=True, slots=True)
class ConfigurationWeighting:
    """配置汇总权重的来源说明。"""

    source: ConfigurationWeightSource
    description: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, ConfigurationWeightSource):
            raise InvalidBattleInferenceContract(
                "configuration weighting source must be explicit"
            )
        if not self.description or self.description != self.description.strip():
            raise InvalidBattleInferenceContract(
                "configuration weighting description must be non-empty and normalized"
            )

    @property
    def represents_external_usage(self) -> bool:
        """只有显式外部使用率数据才可解释为真实环境权重。"""
        return self.source is ConfigurationWeightSource.EXTERNAL_USAGE_DATA


@dataclass(frozen=True, slots=True)
class PolicyDescriptor:
    """写入结果的行动策略标识与假设，不持有运行期策略对象。"""

    policy_id: str
    description: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("policy_id", self.policy_id),
            ("description", self.description),
        ):
            if not value or value != value.strip():
                raise InvalidBattleInferenceContract(
                    f"{field_name} must be non-empty and normalized"
                )

    @classmethod
    def from_policy(cls, policy: ActionPolicy[PolicyActionT]) -> PolicyDescriptor:
        """从结构化策略协议复制稳定结果元数据。"""
        return cls(policy_id=policy.policy_id, description=policy.description)


@dataclass(frozen=True, slots=True)
class MechanismCoverage:
    """本次推演明确纳入和暂未纳入的机制集合。"""

    included: tuple[str, ...]
    excluded: tuple[str, ...]

    def __post_init__(self) -> None:
        included = set(self.included)
        excluded = set(self.excluded)
        if len(included) != len(self.included) or len(excluded) != len(self.excluded):
            raise InvalidBattleInferenceContract(
                "mechanism coverage cannot contain duplicate entries"
            )
        if any(not item or item != item.strip() for item in (*self.included, *self.excluded)):
            raise InvalidBattleInferenceContract(
                "mechanism coverage entries must be non-empty and normalized"
            )
        overlap = included & excluded
        if overlap:
            raise InvalidBattleInferenceContract(
                "mechanisms cannot be both included and excluded: "
                + ", ".join(sorted(overlap))
            )


@dataclass(frozen=True, slots=True)
class RepresentativePathReference:
    """一条代表性胜、负或平局路径在状态图结果中的稳定引用。"""

    outcome: TerminalOutcome
    reference: str

    def __post_init__(self) -> None:
        if not self.reference or self.reference != self.reference.strip():
            raise InvalidBattleInferenceContract(
                "representative path reference must be non-empty and normalized"
            )


@dataclass(frozen=True, slots=True)
class OutcomeCounts:
    """按终局语义统计的已求解结果数量。"""

    attacker_wins: int
    defender_wins: int
    draws: int

    def __post_init__(self) -> None:
        if min(self.attacker_wins, self.defender_wins, self.draws) < 0:
            raise InvalidBattleInferenceContract("outcome counts cannot be negative")

    @property
    def total(self) -> int:
        return self.attacker_wins + self.defender_wins + self.draws


@dataclass(frozen=True, slots=True)
class TerminationCount:
    """一种终止原因对应的终局数量。"""

    reason: TerminationReason
    count: int

    def __post_init__(self) -> None:
        if self.count < 0:
            raise InvalidBattleInferenceContract("termination count cannot be negative")


@dataclass(frozen=True, slots=True)
class BattleInferenceResult:
    """固定观察方视角下的 1v1 推演结果合同。

    `win_probability` 与 `loss_probability` 相对 `observer`；代表性路径仍使用攻击方胜、
    防守方胜和平局的绝对终局语义。配置覆盖率和权重来源是独立字段，调用方不得把等权
    配置枚举结果包装成真实环境使用率胜率。
    """

    rules: BattleInferenceRules
    observer: BattleSide
    win_probability: BattleProbability
    loss_probability: BattleProbability
    draw_probability: BattleProbability
    expected_turns: Fraction | None
    attacker_policy: PolicyDescriptor
    defender_policy: PolicyDescriptor
    configuration_coverage: ConfigurationCoverage
    configuration_weighting: ConfigurationWeighting
    mechanism_coverage: MechanismCoverage
    representative_paths: tuple[RepresentativePathReference, ...] = ()
    outcome_counts: OutcomeCounts | None = None
    termination_counts: tuple[TerminationCount, ...] = ()

    def __post_init__(self) -> None:
        probability_total = (
            self.win_probability.value
            + self.loss_probability.value
            + self.draw_probability.value
        )
        if probability_total != Fraction(1, 1):
            raise InvalidBattleInferenceContract(
                "win, loss and draw probabilities must sum exactly to 1"
            )
        if self.expected_turns is not None:
            if not isinstance(self.expected_turns, Fraction):
                raise InvalidBattleInferenceContract(
                    "expected_turns must use fractions.Fraction when defined"
                )
            if self.expected_turns < 0:
                raise InvalidBattleInferenceContract(
                    "expected_turns cannot be negative"
                )
        if not isinstance(self.observer, BattleSide):
            raise InvalidBattleInferenceContract("observer must be a BattleSide")
        reasons = tuple(item.reason for item in self.termination_counts)
        if len(set(reasons)) != len(reasons):
            raise InvalidBattleInferenceContract(
                "termination_counts cannot repeat the same reason"
            )

    @property
    def probability_total(self) -> Fraction:
        """返回胜、负、平概率总和。"""
        return (
            self.win_probability.value
            + self.loss_probability.value
            + self.draw_probability.value
        )
