"""定义通用 1v1 技能池合同共享枚举、精确比率和校验语义。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from math import comb

ONE_ON_ONE_CONTRACT_VERSION = "one-on-one-move-pool.v1"
MAX_TOTAL_CANDIDATE_MOVES = 20
MOVE_SET_SIZE = 4


class OneOnOneContractError(ValueError):
    """表示 1v1 技能池命令、结果或进度违反了公开合同。"""


class ConfigurationDimensionMode(str, Enum):
    """声明一个配置维度是固定、候选池枚举或明确禁用。"""

    FIXED = "fixed"
    CANDIDATE_POOL = "candidate_pool"
    DISABLED = "disabled"


class OneOnOneConfigurationWeightAssumption(str, Enum):
    """声明配置对聚合权重的来源，避免被误读为真实使用率。"""

    UNIFORM_CONFIGURATION_PAIR = "uniform_configuration_pair"


class OneOnOneActionPolicy(str, Enum):
    """声明批量推演使用的稳定行动选择语义。"""

    FIRST_LEGAL = "first-legal-action"
    UNIFORM_RANDOM_LEGAL_ACTION = "uniform-random"


class MechanismAdmissionPolicy(str, Enum):
    """声明候选机制进入精确推演前必须满足的覆盖门槛。"""

    SUPPORTED_ONLY = "supported_only"


class ConfigurationExecutionStatus(str, Enum):
    """描述一个规范化配置对的最终执行状态。"""

    SUCCESS = "success"
    FAILED = "failed"
    TRUNCATED = "truncated"


class ConfigurationTaskStatus(str, Enum):
    """描述配置空间后台任务的稳定生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ExactRatio:
    """使用最简分数表达概率或配置覆盖权重，避免静默降为浮点数。"""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        """约分并校验比率位于闭区间 [0, 1]。

        Raises:
            OneOnOneContractError: 分子分母不是整数、分母非正或比率越界时抛出。
        """
        if not _is_integer(self.numerator) or not _is_integer(self.denominator):
            raise OneOnOneContractError("exact ratios require integer numerator and denominator")
        if self.denominator <= 0:
            raise OneOnOneContractError("exact ratio denominator must be positive")
        value = Fraction(self.numerator, self.denominator)
        if not 0 <= value <= 1:
            raise OneOnOneContractError("exact ratio must be in the interval [0, 1]")
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    @classmethod
    def from_fraction(cls, value: Fraction) -> ExactRatio:
        """从精确 Fraction 创建可序列化比率。

        Args:
            value: 必须位于 [0, 1] 的精确分数。

        Returns:
            已约分且适合 DTO/fixture 序列化的比率。
        """
        if not isinstance(value, Fraction):
            raise OneOnOneContractError("value must be fractions.Fraction")
        return cls(value.numerator, value.denominator)

    @property
    def value(self) -> Fraction:
        """返回供 application 聚合使用的精确 Fraction。"""
        return Fraction(self.numerator, self.denominator)


def count_move_sets(candidate_count: int) -> int:
    """返回首版一侧候选池生成的无序技能组数量。

    Args:
        candidate_count: 一侧候选招式数量，必须为正整数。

    Returns:
        ``candidate_count < 4`` 时返回 1，否则返回 ``C(candidate_count, 4)``。

    Raises:
        OneOnOneContractError: 候选数量不是正整数时抛出。
    """
    _require_positive_integer("candidate_count", candidate_count)
    if candidate_count < MOVE_SET_SIZE:
        return 1
    return comb(candidate_count, MOVE_SET_SIZE)


def count_configuration_pairs(
    attacker_candidate_count: int,
    defender_candidate_count: int,
) -> int:
    """返回满足双方总候选预算的配置对数量。

    Args:
        attacker_candidate_count: 攻击方候选招式数量，至少为 1。
        defender_candidate_count: 防守方候选招式数量，至少为 1。

    Returns:
        双方技能组数量的笛卡尔积。

    Raises:
        OneOnOneContractError: 任一侧为空或双方总数超过 20 时抛出。
    """
    _require_positive_integer("attacker_candidate_count", attacker_candidate_count)
    _require_positive_integer("defender_candidate_count", defender_candidate_count)
    if attacker_candidate_count + defender_candidate_count > MAX_TOTAL_CANDIDATE_MOVES:
        raise OneOnOneContractError("candidate move counts must total at most 20")
    return count_move_sets(attacker_candidate_count) * count_move_sets(defender_candidate_count)


def _normalize_move_set(field_name: str, move_ids: tuple[int, ...]) -> tuple[int, ...]:
    """校验并排序一个已经选定的一到四招技能组。"""
    normalized = tuple(move_ids)
    if not 1 <= len(normalized) <= MOVE_SET_SIZE:
        raise OneOnOneContractError(f"{field_name} must contain one to four moves")
    if any(not _is_positive_integer(move_id) for move_id in normalized):
        raise OneOnOneContractError(f"{field_name} must contain positive integers")
    if len(normalized) != len(set(normalized)):
        raise OneOnOneContractError(f"{field_name} must not contain duplicate moves")
    return tuple(sorted(normalized))


def _require_configuration_id(value: str) -> None:
    """校验配置 ID 使用当前 canonical 前缀且没有首尾空白。"""
    _require_normalized_text("configuration_id", value)
    if not value.startswith("one-on-one-configuration:"):
        raise OneOnOneContractError("configuration_id must use the v1 canonical prefix")


def _require_identity_text(field_name: str, value: str) -> None:
    """校验参与稳定身份计算的字符串为 ASCII 非空规范化文本。"""
    _require_normalized_text(field_name, value)
    if not value.isascii():
        raise OneOnOneContractError(f"{field_name} must use a stable ASCII identifier")


def _require_normalized_text(field_name: str, value: str) -> None:
    """校验字符串非空且没有首尾空白。"""
    if not isinstance(value, str) or not value or value != value.strip():
        raise OneOnOneContractError(f"{field_name} must be non-empty and normalized")


def _require_positive_integer(field_name: str, value: int) -> None:
    """校验字段为排除 bool 的正整数。"""
    if not _is_positive_integer(value):
        raise OneOnOneContractError(f"{field_name} must be a positive integer")


def _is_positive_integer(value: object) -> bool:
    """返回 value 是否为排除 bool 的正整数。"""
    return _is_integer(value) and value > 0


def _is_integer(value: object) -> bool:
    """返回 value 是否为排除 bool 的整数。"""
    return isinstance(value, int) and not isinstance(value, bool)


__all__ = [
    "ONE_ON_ONE_CONTRACT_VERSION",
    "MAX_TOTAL_CANDIDATE_MOVES",
    "MOVE_SET_SIZE",
    "OneOnOneContractError",
    "ConfigurationDimensionMode",
    "OneOnOneConfigurationWeightAssumption",
    "OneOnOneActionPolicy",
    "MechanismAdmissionPolicy",
    "ConfigurationExecutionStatus",
    "ConfigurationTaskStatus",
    "ExactRatio",
    "count_move_sets",
    "count_configuration_pairs",
]
