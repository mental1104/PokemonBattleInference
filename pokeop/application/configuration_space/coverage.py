"""定义机制覆盖、等价类权重和配置空间结果统计。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application.configuration_space.configurations import BattleConfiguration
from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    ConfigurationWeightAssumption,
    MechanismSupportStatus,
    _is_positive_integer,
)
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus


@dataclass(frozen=True, slots=True)
class MechanismCoverageRecord:
    """记录一个合法或受控候选是否进入配置空间及其原因。"""

    side: str
    dimension_key: str
    identifier: str
    support_status: MechanismSupportStatus
    included: bool
    reason: str
    factory_status: EffectCoverageStatus | None = None

    def __post_init__(self) -> None:
        """校验覆盖记录必须可定位到一方、一个维度和一个候选。"""
        if self.side not in {"attacker", "defender"}:
            raise ConfigurationSpaceError("coverage side must be attacker or defender")
        if not self.dimension_key.strip():
            raise ConfigurationSpaceError("dimension_key must not be blank")
        if not self.identifier.strip():
            raise ConfigurationSpaceError("coverage identifier must not be blank")
        if not isinstance(self.support_status, MechanismSupportStatus):
            raise ConfigurationSpaceError(
                "support_status must be a MechanismSupportStatus"
            )
        if self.factory_status is not None and not isinstance(
            self.factory_status, EffectCoverageStatus
        ):
            raise ConfigurationSpaceError(
                "factory_status must be an EffectCoverageStatus or None"
            )
        if not self.reason.strip():
            raise ConfigurationSpaceError("coverage reason must not be blank")


@dataclass(frozen=True, slots=True)
class ConfigurationCoverageStatistics:
    """聚合配置生成期间机制覆盖与命令过滤数量。"""

    supported_count: int
    partial_count: int
    unsupported_count: int
    included_count: int
    excluded_by_command_count: int

    @classmethod
    def from_records(
        cls,
        records: tuple[MechanismCoverageRecord, ...],
    ) -> "ConfigurationCoverageStatistics":
        """根据完整覆盖记录计算稳定计数。

        Args:
            records: 双方所有招式、特性和道具候选覆盖记录。

        Returns:
            区分 supported、partial、unsupported、已纳入和命令排除的统计快照。
        """
        return cls(
            supported_count=sum(
                record.support_status is MechanismSupportStatus.SUPPORTED
                for record in records
            ),
            partial_count=sum(
                record.support_status is MechanismSupportStatus.PARTIAL
                for record in records
            ),
            unsupported_count=sum(
                record.support_status is MechanismSupportStatus.UNSUPPORTED
                for record in records
            ),
            included_count=sum(record.included for record in records),
            excluded_by_command_count=sum(
                not record.included
                and record.support_status is MechanismSupportStatus.SUPPORTED
                and record.factory_status is None
                for record in records
            ),
        )

    @property
    def total_count(self) -> int:
        """返回 coverage records 中全部受控或合法机制候选数量。"""
        return self.supported_count + self.partial_count + self.unsupported_count

    @property
    def fully_supported_ratio(self) -> Fraction:
        """返回完整支持机制占全部已记录候选的精确比例。"""
        if self.total_count == 0:
            return Fraction(1)
        return Fraction(self.supported_count, self.total_count)

    @property
    def included_ratio(self) -> Fraction:
        """返回实际进入受控配置空间的候选占全部记录候选的精确比例。"""
        if self.total_count == 0:
            return Fraction(1)
        return Fraction(self.included_count, self.total_count)


@dataclass(frozen=True, slots=True)
class ConfigurationWeight:
    """保存一个等价类在显式覆盖假设下的精确统计权重。"""

    assumption: ConfigurationWeightAssumption
    value: Fraction
    description: str

    def __post_init__(self) -> None:
        """保证覆盖权重位于闭区间 [0, 1] 且说明不为空。"""
        if not isinstance(self.assumption, ConfigurationWeightAssumption):
            raise ConfigurationSpaceError(
                "weight assumption must be a ConfigurationWeightAssumption"
            )
        if not 0 <= self.value <= 1:
            raise ConfigurationSpaceError("configuration weight must be between 0 and 1")
        if not self.description.strip():
            raise ConfigurationSpaceError("weight description must not be blank")


@dataclass(frozen=True, slots=True)
class ConfigurationEquivalenceClass:
    """保存一个行为等价类的代表配置、原始成员数量和覆盖权重。"""

    representative: BattleConfiguration
    member_count: int
    weight: ConfigurationWeight

    def __post_init__(self) -> None:
        """拒绝没有原始成员的空等价类。"""
        if not _is_positive_integer(self.member_count):
            raise ConfigurationSpaceError("member_count must be a positive integer")


@dataclass(frozen=True, slots=True)
class ConfigurationSpaceStatistics:
    """记录归并前后配置对规模和机制覆盖数量。"""

    raw_configuration_count: int
    unique_configuration_count: int
    attacker_raw_configuration_count: int
    attacker_unique_configuration_count: int
    defender_raw_configuration_count: int
    defender_unique_configuration_count: int
    unsupported_mechanism_count: int
    partial_mechanism_count: int


@dataclass(frozen=True, slots=True)
class ConfigurationSpace:
    """保存一次双方合法配置枚举、归并、覆盖和权重结果。"""

    equivalence_classes: tuple[ConfigurationEquivalenceClass, ...]
    statistics: ConfigurationSpaceStatistics
    coverage_records: tuple[MechanismCoverageRecord, ...]
    coverage_statistics: ConfigurationCoverageStatistics

    @property
    def configurations(self) -> tuple[BattleConfiguration, ...]:
        """返回每个行为等价类的代表配置。"""
        return tuple(
            equivalence_class.representative
            for equivalence_class in self.equivalence_classes
        )

    @property
    def weight_assumption(self) -> ConfigurationWeightAssumption:
        """返回本次空间统一采用的覆盖权重假设。"""
        if not self.equivalence_classes:
            raise ConfigurationSpaceError("configuration space must not be empty")
        return self.equivalence_classes[0].weight.assumption

    @property
    def total_weight(self) -> Fraction:
        """返回全部等价类覆盖权重之和，完整空间应严格等于 1。"""
        return sum(
            (equivalence_class.weight.value for equivalence_class in self.equivalence_classes),
            start=Fraction(0),
        )


__all__ = [
    "ConfigurationCoverageStatistics",
    "ConfigurationEquivalenceClass",
    "ConfigurationSpace",
    "ConfigurationSpaceStatistics",
    "ConfigurationWeight",
    "MechanismCoverageRecord",
]
