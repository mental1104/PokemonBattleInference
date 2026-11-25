"""编排单边配置维度、行为归并和双方配置对权重计算。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import prod

from pokeop.application.configuration_space.models import (
    BattleConfiguration,
    ConfigurationCoverageStatistics,
    ConfigurationEquivalenceClass,
    ConfigurationSpace,
    ConfigurationSpaceError,
    ConfigurationSpaceStatistics,
    ConfigurationWeight,
    ConfigurationWeightAssumption,
    GenerateConfigurationSpaceCommand,
    MechanismCoverageRecord,
    PokemonBattleConfiguration,
    PokemonConfigurationProfile,
    PokemonSpaceCommand,
)
from pokeop.application.configuration_space.providers import (
    DEFAULT_DIMENSION_PROVIDERS,
    ConfigurationDimensionProvider,
    ConfigurationGenerationContext,
    PokemonConfigurationDraft,
)
from pokeop.domain.battle.effects.factories import BattleEffectAbstractFactory


@dataclass(frozen=True, slots=True)
class _PokemonConfigurationClass:
    """保存单边行为等价类代表配置和归并前成员数量。"""

    representative: PokemonBattleConfiguration
    member_count: int


@dataclass(frozen=True, slots=True)
class _PokemonConfigurationSpace:
    """保存单边配置枚举结果，供双方配置对生成阶段复用。"""

    equivalence_classes: tuple[_PokemonConfigurationClass, ...]
    raw_configuration_count: int
    coverage_records: tuple[MechanismCoverageRecord, ...]

    @property
    def unique_configuration_count(self) -> int:
        """返回单边行为等价类数量。"""
        return len(self.equivalence_classes)


@dataclass(frozen=True, slots=True)
class PokemonConfigurationGenerator:
    """通过可扩展维度 provider 生成并归并单只 Pokémon 的配置空间。

    Args:
        effect_factory: 当前 profile.ruleset_id 对应的具体 effect factory。
        providers: 按顺序应用的配置维度 provider。默认包含招式、能力、特性和道具；
            调用方可追加新 provider，主组合循环无需修改。
    """

    effect_factory: BattleEffectAbstractFactory
    providers: tuple[ConfigurationDimensionProvider, ...] = DEFAULT_DIMENSION_PROVIDERS

    def __post_init__(self) -> None:
        """校验 provider 键唯一，并保证至少存在一个配置维度。"""
        providers = tuple(self.providers)
        if not providers:
            raise ConfigurationSpaceError("providers must not be empty")
        keys = tuple(provider.dimension_key for provider in providers)
        if any(not key.strip() for key in keys):
            raise ConfigurationSpaceError("provider dimension_key must not be blank")
        if len(keys) != len(set(keys)):
            raise ConfigurationSpaceError("provider dimension_key values must be unique")
        object.__setattr__(self, "providers", providers)

    def generate(
        self,
        profile: PokemonConfigurationProfile,
        command: PokemonSpaceCommand,
        *,
        side: str,
    ) -> _PokemonConfigurationSpace:
        """生成单边合法配置，并按当前支持机制未来行为归并。

        Args:
            profile: #31 repository 或 fake repository 提供的 version-aware profile。
            command: 候选池、枚举模式、等级和单边运行保护。
            side: 覆盖报告使用的 ``attacker`` 或 ``defender`` 标识。

        Returns:
            包含原始组合数、行为等价类和完整覆盖记录的单边空间。

        Raises:
            ConfigurationSpaceError: 任一维度没有支持候选，或原始组合超过上限时抛出。
        """
        context = ConfigurationGenerationContext(
            profile=profile,
            command=command,
            effect_factory=self.effect_factory,
            side=side,
        )
        expansions = tuple(
            (provider, provider.expand(context)) for provider in self.providers
        )
        for provider, expansion in expansions:
            if not expansion.values:
                raise ConfigurationSpaceError(
                    f"dimension {provider.dimension_key!r} has no supported candidates "
                    f"for {profile.name}"
                )

        raw_configuration_count = prod(
            expansion.raw_member_count for _, expansion in expansions
        )
        if raw_configuration_count > command.max_raw_configurations:
            raise ConfigurationSpaceError(
                "raw single-Pokemon configuration count exceeds "
                "max_raw_configurations"
            )

        partials: tuple[tuple[PokemonConfigurationDraft, int], ...] = (
            (PokemonConfigurationDraft(profile=profile, level=command.level), 1),
        )
        for _, expansion in expansions:
            next_partials: list[tuple[PokemonConfigurationDraft, int]] = []
            for draft, current_member_count in partials:
                for value in expansion.values:
                    next_partials.append(
                        (
                            value.apply(draft),
                            current_member_count * value.member_count,
                        )
                    )
            partials = tuple(next_partials)

        grouped: dict[tuple[object, ...], _PokemonConfigurationClass] = {}
        for draft, member_count in partials:
            configuration = draft.finalize()
            signature = configuration.behavior_signature
            current = grouped.get(signature)
            if current is None:
                grouped[signature] = _PokemonConfigurationClass(
                    representative=configuration,
                    member_count=member_count,
                )
            else:
                grouped[signature] = _PokemonConfigurationClass(
                    representative=current.representative,
                    member_count=current.member_count + member_count,
                )

        # 原始成员总量必须在所有归并阶段保持守恒，否则覆盖权重会失真。
        if sum(value.member_count for value in grouped.values()) != raw_configuration_count:
            raise ConfigurationSpaceError(
                "configuration member counts changed during equivalence merging"
            )

        coverage_records = tuple(
            record
            for _, expansion in expansions
            for record in expansion.coverage_records
        )
        return _PokemonConfigurationSpace(
            equivalence_classes=tuple(
                sorted(
                    grouped.values(),
                    key=lambda value: repr(value.representative.behavior_signature),
                )
            ),
            raw_configuration_count=raw_configuration_count,
            coverage_records=coverage_records,
        )


@dataclass(frozen=True, slots=True)
class GenerateConfigurationSpaceUseCase:
    """编排双方单边生成器，并输出带权行为等价配置对。

    该用例不读取数据库、不执行状态图求解，也不把覆盖权重命名为真实天梯使用率。
    repository 调用属于更上层编排；本用例只消费已准备好的双方 profile。

    Args:
        attacker_generator: 使用攻击方 ruleset factory 的单边生成器。
        defender_generator: 使用防守方 ruleset factory 的单边生成器；同规则集时通常
            可以与 attacker_generator 共享同一个不可变实例。
    """

    attacker_generator: PokemonConfigurationGenerator
    defender_generator: PokemonConfigurationGenerator

    def execute(
        self,
        command: GenerateConfigurationSpaceCommand,
        *,
        attacker_profile: PokemonConfigurationProfile,
        defender_profile: PokemonConfigurationProfile,
    ) -> ConfigurationSpace:
        """生成双方配置空间、归并行为等价类并分配精确覆盖权重。

        Args:
            command: 双方候选池、枚举模式、权重假设和配置对上限。
            attacker_profile: 攻击方 version-aware 合法候选 profile。
            defender_profile: 防守方 version-aware 合法候选 profile。

        Returns:
            明确区分原始组合、唯一配置、覆盖记录和权重假设的 ``ConfigurationSpace``。

        Raises:
            ConfigurationSpaceError: 双方规则集不一致、候选为空或配置对超过上限时抛出。
        """
        if attacker_profile.ruleset_id != defender_profile.ruleset_id:
            raise ConfigurationSpaceError(
                "attacker and defender profiles must use the same ruleset_id"
            )
        if attacker_profile.version_group_id != defender_profile.version_group_id:
            raise ConfigurationSpaceError(
                "attacker and defender profiles must use the same version_group_id"
            )
        attacker_space = self.attacker_generator.generate(
            attacker_profile,
            command.attacker,
            side="attacker",
        )
        defender_space = self.defender_generator.generate(
            defender_profile,
            command.defender,
            side="defender",
        )

        raw_pair_count = (
            attacker_space.raw_configuration_count
            * defender_space.raw_configuration_count
        )
        if raw_pair_count > command.max_raw_configuration_pairs:
            raise ConfigurationSpaceError(
                "raw battle configuration pair count exceeds "
                "max_raw_configuration_pairs"
            )

        grouped_pairs: dict[
            tuple[object, object],
            tuple[BattleConfiguration, int],
        ] = {}
        for attacker_class in attacker_space.equivalence_classes:
            for defender_class in defender_space.equivalence_classes:
                configuration = BattleConfiguration(
                    attacker=attacker_class.representative,
                    defender=defender_class.representative,
                )
                member_count = (
                    attacker_class.member_count * defender_class.member_count
                )
                signature = configuration.behavior_signature
                current = grouped_pairs.get(signature)
                if current is None:
                    grouped_pairs[signature] = (configuration, member_count)
                else:
                    grouped_pairs[signature] = (
                        current[0],
                        current[1] + member_count,
                    )

        if sum(member_count for _, member_count in grouped_pairs.values()) != raw_pair_count:
            raise ConfigurationSpaceError(
                "battle configuration member counts changed during pair merging"
            )

        unique_count = len(grouped_pairs)
        if unique_count == 0:
            raise ConfigurationSpaceError("configuration space must not be empty")
        equivalence_classes = tuple(
            ConfigurationEquivalenceClass(
                representative=configuration,
                member_count=member_count,
                weight=self._weight(
                    command.weight_assumption,
                    member_count=member_count,
                    raw_count=raw_pair_count,
                    unique_count=unique_count,
                ),
            )
            for configuration, member_count in sorted(
                grouped_pairs.values(),
                key=lambda value: repr(value[0].behavior_signature),
            )
        )
        coverage_records = (
            attacker_space.coverage_records + defender_space.coverage_records
        )
        coverage_statistics = ConfigurationCoverageStatistics.from_records(
            coverage_records
        )
        result = ConfigurationSpace(
            equivalence_classes=equivalence_classes,
            statistics=ConfigurationSpaceStatistics(
                raw_configuration_count=raw_pair_count,
                unique_configuration_count=unique_count,
                attacker_raw_configuration_count=(
                    attacker_space.raw_configuration_count
                ),
                attacker_unique_configuration_count=(
                    attacker_space.unique_configuration_count
                ),
                defender_raw_configuration_count=(
                    defender_space.raw_configuration_count
                ),
                defender_unique_configuration_count=(
                    defender_space.unique_configuration_count
                ),
                unsupported_mechanism_count=(
                    coverage_statistics.unsupported_count
                ),
                partial_mechanism_count=coverage_statistics.partial_count,
            ),
            coverage_records=coverage_records,
            coverage_statistics=coverage_statistics,
        )
        if result.total_weight != Fraction(1):
            raise ConfigurationSpaceError(
                "configuration coverage weights must sum exactly to 1"
            )
        return result

    @staticmethod
    def _weight(
        assumption: ConfigurationWeightAssumption,
        *,
        member_count: int,
        raw_count: int,
        unique_count: int,
    ) -> ConfigurationWeight:
        """根据显式覆盖假设创建一个等价类的精确权重。

        Args:
            assumption: 按原始候选均匀或按等价类均匀的统计假设。
            member_count: 当前等价类包含的原始配置对数量。
            raw_count: 全空间原始配置对总量。
            unique_count: 全空间行为等价类数量。

        Returns:
            带有避免误读为真实使用率说明的 ``ConfigurationWeight``。
        """
        if assumption is ConfigurationWeightAssumption.UNIFORM_RAW_CONFIGURATION:
            return ConfigurationWeight(
                assumption=assumption,
                value=Fraction(member_count, raw_count),
                description=(
                    "Coverage weight under a uniform raw configuration assumption; "
                    "this is not ladder usage rate or empirical win probability."
                ),
            )
        return ConfigurationWeight(
            assumption=assumption,
            value=Fraction(1, unique_count),
            description=(
                "Coverage weight under a uniform equivalence-class assumption; "
                "this is not ladder usage rate or empirical win probability."
            ),
        )


__all__ = [
    "GenerateConfigurationSpaceUseCase",
    "PokemonConfigurationGenerator",
]
