"""定义配置维度 provider 的共享协议、上下文、草稿和值对象。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Hashable, Protocol, runtime_checkable

from pokeop.application.configuration_space.models import (
    ConfiguredMove,
    ConfigurationSpaceError,
    MechanismCoverageRecord,
    MechanismSupportStatus,
    PokemonBattleConfiguration,
    PokemonConfigurationProfile,
    PokemonSpaceCommand,
)
from pokeop.domain.battle.effects.factories import BattleEffectAbstractFactory
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from pokeop.domain.battle.stats import StatProfile, StatValues


def _factory_support_status(
    status: EffectCoverageStatus,
) -> MechanismSupportStatus:
    """把 domain factory coverage 映射为 application 覆盖状态。

    不同机制迭代可能扩展 ``EffectCoverageStatus.PARTIAL``。这里基于稳定字符串值
    兼容未声明或已经声明 partial 的 domain 版本，使配置生成器保留该语义，并继续采用
    保守策略过滤尚未完整覆盖的机制。

    Args:
        status: 规则集 factory 返回的 domain 覆盖状态。

    Returns:
        application 用于统计和过滤的 supported、partial 或 unsupported 状态。
    """
    if status is EffectCoverageStatus.SUPPORTED:
        return MechanismSupportStatus.SUPPORTED
    if status.value == MechanismSupportStatus.PARTIAL.value:
        return MechanismSupportStatus.PARTIAL
    return MechanismSupportStatus.UNSUPPORTED


@dataclass(frozen=True, slots=True)
class PokemonConfigurationDraft:
    """保存维度 provider 逐步填充的单边不可变配置草稿。

    草稿只在 application 配置生成过程中存在。每个 provider 通过 ``apply`` 返回新对象，
    不共享可变字典，也不依赖主循环按字段名反射赋值。
    """

    profile: PokemonConfigurationProfile
    level: int
    moves: tuple[ConfiguredMove, ...] | None = None
    stats: StatValues | None = None
    stat_profile: StatProfile | None = None
    ability_identifier: str | None = None
    item_identifier: str | None = None
    dimension_labels: tuple[tuple[str, str], ...] = ()
    extra_dimensions: tuple[tuple[str, Hashable], ...] = ()

    def with_label(self, dimension_key: str, label: str) -> "PokemonConfigurationDraft":
        """返回追加一条维度解释标签的新草稿。

        Args:
            dimension_key: provider 的稳定维度标识。
            label: 当前代表值的简短可读说明。

        Returns:
            追加标签后的新草稿；原草稿保持不变。
        """
        return replace(
            self,
            dimension_labels=self.dimension_labels + ((dimension_key, label),),
        )

    def with_extra_dimension(
        self,
        dimension_key: str,
        signature: Hashable,
        label: str,
    ) -> "PokemonConfigurationDraft":
        """追加一个主循环未知但参与行为判等的扩展维度。

        Args:
            dimension_key: 新 provider 的稳定维度标识。
            signature: 当前扩展值的不可变、可哈希行为签名。
            label: 面向覆盖结果的代表值说明。

        Returns:
            同时追加解释标签和扩展签名的新草稿。
        """
        updated = replace(
            self,
            extra_dimensions=self.extra_dimensions + ((dimension_key, signature),),
        )
        return updated.with_label(dimension_key, label)

    def finalize(self) -> PokemonBattleConfiguration:
        """把已完整填充的草稿转换成可哈希单边配置。

        Returns:
            保留 representative 来源并按最终行为签名判等的配置对象。

        Raises:
            ConfigurationSpaceError: 任一标准维度尚未由 provider 填充时抛出。
        """
        missing: list[str] = []
        moves = self.moves
        stats = self.stats
        stat_profile = self.stat_profile
        ability_identifier = self.ability_identifier
        item_identifier = self.item_identifier
        if moves is None:
            missing.append("moves")
        if stats is None or stat_profile is None:
            missing.append("stats")
        if ability_identifier is None:
            missing.append("ability")
        if item_identifier is None:
            missing.append("item")
        if missing:
            raise ConfigurationSpaceError(
                "configuration draft is missing dimensions: " + ", ".join(missing)
            )
        if stats is None or stat_profile is None or moves is None:
            raise AssertionError("validated configuration dimensions were not narrowed")
        if ability_identifier is None or item_identifier is None:
            raise AssertionError("validated mechanism dimensions were not narrowed")

        return PokemonBattleConfiguration(
            ruleset_id=self.profile.ruleset_id,
            version_group_id=self.profile.version_group_id,
            pokemon_id=self.profile.pokemon_id,
            name=self.profile.name,
            level=self.level,
            types=self.profile.types,
            stats=stats,
            stat_profile=stat_profile,
            moves=moves,
            ability_identifier=ability_identifier,
            item_identifier=item_identifier,
            can_evolve=self.profile.can_evolve,
            dimension_labels=self.dimension_labels,
            extra_dimensions=self.extra_dimensions,
        )


@runtime_checkable
class ConfigurationDimensionValue(Protocol):
    """表示一个 provider 生成、可应用到配置草稿的不可变维度值。"""

    @property
    def member_count(self) -> int:
        """返回该代表值归并的原始候选数量。"""
        ...

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把当前维度值应用到草稿并返回新对象。"""
        ...


@dataclass(frozen=True, slots=True)
class DimensionExpansion:
    """保存一个维度的唯一代表值和完整机制覆盖记录。"""

    values: tuple[ConfigurationDimensionValue, ...]
    coverage_records: tuple[MechanismCoverageRecord, ...] = ()

    @property
    def raw_member_count(self) -> int:
        """返回该维度归并前包含的原始候选数量。"""
        return sum(value.member_count for value in self.values)


@dataclass(frozen=True, slots=True)
class ConfigurationGenerationContext:
    """向每个维度 provider 提供相同的 profile、command、factory 和阵营信息。"""

    profile: PokemonConfigurationProfile
    command: PokemonSpaceCommand
    effect_factory: BattleEffectAbstractFactory
    side: str

    def __post_init__(self) -> None:
        """保证覆盖记录使用稳定的 attacker/defender 标识。"""
        if self.side not in {"attacker", "defender"}:
            raise ConfigurationSpaceError("side must be attacker or defender")
        if self.profile.ruleset_id != self.effect_factory.ruleset_id:
            raise ConfigurationSpaceError(
                "profile ruleset_id does not match the injected effect factory"
            )


@runtime_checkable
class ConfigurationDimensionProvider(Protocol):
    """把一个独立配置维度展开成可组合代表值和覆盖记录。"""

    @property
    def dimension_key(self) -> str:
        """返回维度在解释标签和覆盖报告中的稳定标识。"""
        ...

    def expand(self, context: ConfigurationGenerationContext) -> DimensionExpansion:
        """根据当前 profile 和显式 command 生成当前维度候选。"""
        ...


@dataclass(frozen=True, slots=True)
class _MoveOption:
    """保存已通过 repository 与 factory 双重校验的单招式候选。"""

    configured_move: ConfiguredMove
    member_count: int


@dataclass(frozen=True, slots=True)
class MoveSetDimensionValue:
    """表示一个不含重复槽位的稳定招式组合代表值。"""

    moves: tuple[ConfiguredMove, ...]
    member_count: int = 1

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把稳定排序后的招式组合写入草稿。"""
        move_ids = ",".join(str(move.move_spec.move_id) for move in self.moves)
        return replace(draft, moves=self.moves).with_label("moves", move_ids)


@dataclass(frozen=True, slots=True)
class StatDimensionValue:
    """表示按最终实际能力值归并后的能力配置代表值。"""

    stat_profile: StatProfile
    actual_stats: StatValues
    label: str
    member_count: int = 1

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把 representative 的 StatProfile 和最终能力值写入草稿。"""
        return replace(
            draft,
            stat_profile=self.stat_profile,
            stats=self.actual_stats,
        ).with_label("stats", self.label)


@dataclass(frozen=True, slots=True)
class AbilityDimensionValue:
    """表示当前规则集 factory 已确认支持的特性标识。"""

    identifier: str
    member_count: int = 1

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把规范化特性标识写入草稿。"""
        return replace(draft, ability_identifier=self.identifier).with_label(
            "ability",
            self.identifier,
        )


@dataclass(frozen=True, slots=True)
class ItemDimensionValue:
    """表示当前规则集 factory 已确认支持的道具或明确无道具状态。"""

    identifier: str
    member_count: int = 1

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把规范化道具标识写入草稿。"""
        return replace(draft, item_identifier=self.identifier).with_label(
            "item",
            self.identifier,
        )


@dataclass(frozen=True, slots=True)
class OpaqueDimensionValue:
    """为未来维度 provider 提供无需修改主循环的通用扩展值。

    Args:
        dimension_key: 新配置维度的稳定键。
        signature: 影响未来战斗行为的不可变、可哈希签名。
        label: representative 的可读说明。
        member_count: 当前 representative 归并的原始候选数量。
    """

    dimension_key: str
    signature: Hashable
    label: str
    member_count: int = 1

    def __post_init__(self) -> None:
        """校验扩展维度标识、标签和原始成员数量。"""
        if not self.dimension_key.strip():
            raise ConfigurationSpaceError("dimension_key must not be blank")
        if not self.label.strip():
            raise ConfigurationSpaceError("label must not be blank")
        if isinstance(self.member_count, bool) or self.member_count <= 0:
            raise ConfigurationSpaceError("member_count must be greater than 0")
        hash(self.signature)

    def apply(self, draft: PokemonConfigurationDraft) -> PokemonConfigurationDraft:
        """把未知于主循环的行为签名和解释标签追加到草稿。"""
        return draft.with_extra_dimension(
            self.dimension_key,
            self.signature,
            self.label,
        )




__all__ = [
    "AbilityDimensionValue",
    "ConfigurationDimensionProvider",
    "ConfigurationDimensionValue",
    "ConfigurationGenerationContext",
    "DimensionExpansion",
    "ItemDimensionValue",
    "MoveSetDimensionValue",
    "OpaqueDimensionValue",
    "PokemonConfigurationDraft",
    "StatDimensionValue",
]
