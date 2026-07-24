"""定义通用 1v1 双方固定配置、候选技能池和规范化配置身份。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from typing import Iterator

from pokeop.application.configuration_space.one_on_one.model_base import (
    MAX_TOTAL_CANDIDATE_MOVES,
    MOVE_SET_SIZE,
    ONE_ON_ONE_CONTRACT_VERSION,
    ConfigurationDimensionMode,
    MechanismAdmissionPolicy,
    OneOnOneActionPolicy,
    OneOnOneConfigurationWeightAssumption,
    OneOnOneContractError,
    _is_integer,
    _is_positive_integer,
    _normalize_move_set,
    _require_configuration_id,
    _require_identity_text,
    _require_positive_integer,
    count_move_sets,
)


@dataclass(frozen=True, slots=True)
class OneOnOneDimensionModes:
    """冻结首版各配置维度的枚举方式。

    首版只允许招式使用候选池；Pokémon、形态、等级、能力值、特性和道具均固定，
    Mega、Z 招式、极巨化等特殊机制明确禁用。后续版本可以复用同一枚举扩展字段，
    但不得在 v1 命令中静默改变这些默认边界。
    """

    pokemon: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    form: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    level: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    stats: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    ability: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    item: ConfigurationDimensionMode = ConfigurationDimensionMode.FIXED
    moves: ConfigurationDimensionMode = ConfigurationDimensionMode.CANDIDATE_POOL
    special_mechanics: ConfigurationDimensionMode = ConfigurationDimensionMode.DISABLED

    def __post_init__(self) -> None:
        """校验 v1 维度模式没有被调用方静默扩张。

        Raises:
            OneOnOneContractError: 任一字段不是显式枚举，或首版维度模式被改变时抛出。
        """
        values = (
            self.pokemon,
            self.form,
            self.level,
            self.stats,
            self.ability,
            self.item,
            self.moves,
            self.special_mechanics,
        )
        if any(not isinstance(value, ConfigurationDimensionMode) for value in values):
            raise OneOnOneContractError("all dimension modes must be explicit enums")
        fixed_dimensions = (
            self.pokemon,
            self.form,
            self.level,
            self.stats,
            self.ability,
            self.item,
        )
        if any(value is not ConfigurationDimensionMode.FIXED for value in fixed_dimensions):
            raise OneOnOneContractError("v1 only allows fixed non-move dimensions")
        if self.moves is not ConfigurationDimensionMode.CANDIDATE_POOL:
            raise OneOnOneContractError("v1 requires moves to use candidate_pool mode")
        if self.special_mechanics is not ConfigurationDimensionMode.DISABLED:
            raise OneOnOneContractError("v1 requires special mechanics to be disabled")


@dataclass(frozen=True, slots=True)
class FixedPokemonConfiguration:
    """保存一侧不会参与首版组合枚举的固定战斗配置。

    Args:
        pokemon_id: PokeAPI Pokémon 稳定正整数 ID。
        form_id: 明确形态 ID；None 表示由 Pokémon ID 对应的默认形态解析。
        level: 战斗等级，必须位于 1 到 100。
        stat_profile_id: 能唯一还原最终能力值的 application 配置标识。
        ability_identifier: 当前 version group 下固定使用的特性标识。
        item_identifier: 固定道具标识；None 表示明确不携带道具。
    """

    pokemon_id: int
    form_id: int | None
    level: int
    stat_profile_id: str
    ability_identifier: str
    item_identifier: str | None

    def __post_init__(self) -> None:
        """校验固定配置足以稳定参与配置 ID 计算。

        Raises:
            OneOnOneContractError: ID、等级或身份字符串不合法时抛出。
        """
        _require_positive_integer("pokemon_id", self.pokemon_id)
        if self.form_id is not None:
            _require_positive_integer("form_id", self.form_id)
        if not _is_integer(self.level) or not 1 <= self.level <= 100:
            raise OneOnOneContractError("level must be an integer from 1 to 100")
        _require_identity_text("stat_profile_id", self.stat_profile_id)
        _require_identity_text("ability_identifier", self.ability_identifier)
        if self.item_identifier is not None:
            _require_identity_text("item_identifier", self.item_identifier)


@dataclass(frozen=True, slots=True)
class MoveCandidatePool:
    """保存一侧无序、去重且规范化的候选招式池。

    Args:
        candidate_move_ids: 当前 version group 下通过合法性和机制准入的招式 ID。
    """

    candidate_move_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """规范化候选顺序，并拒绝空池、重复或非法 ID。

        Raises:
            OneOnOneContractError: 候选池为空、包含重复项或非正整数时抛出。
        """
        move_ids = tuple(self.candidate_move_ids)
        if not move_ids:
            raise OneOnOneContractError("each side requires at least one candidate move")
        if any(not _is_positive_integer(move_id) for move_id in move_ids):
            raise OneOnOneContractError("candidate move ids must be positive integers")
        if len(move_ids) != len(set(move_ids)):
            raise OneOnOneContractError("candidate move ids must be unique")
        object.__setattr__(self, "candidate_move_ids", tuple(sorted(move_ids)))

    @property
    def move_set_count(self) -> int:
        """返回首版规则生成的无序技能组数量。

        候选数小于 4 时，池内全部招式构成唯一技能组；候选数至少 4 时，枚举恰好
        4 招的组合 ``C(n, 4)``。
        """
        return count_move_sets(len(self.candidate_move_ids))

    def iter_move_sets(self) -> Iterator[tuple[int, ...]]:
        """按字典序迭代规范化技能组，不为初始槽位排列生成重复配置。

        Returns:
            每个元素都是递增排序的一到四个招式 ID；迭代数量等于 ``move_set_count``。
        """
        if len(self.candidate_move_ids) < MOVE_SET_SIZE:
            yield self.candidate_move_ids
            return
        yield from combinations(self.candidate_move_ids, MOVE_SET_SIZE)


@dataclass(frozen=True, slots=True)
class PokemonMovePoolSelection:
    """组合一侧固定配置与候选招式 ID。

    字段名与共享 JSON/TypeScript fixture 保持一致，避免前后端分别发明 adapter
    专用结构。规范化后 ``candidate_move_ids`` 始终递增排序。

    Args:
        fixed: 首版不会参与枚举的 Pokémon、形态、等级、能力、特性和道具。
        candidate_move_ids: 当前 version group 下通过合法性与机制准入的招式 ID。
    """

    fixed: FixedPokemonConfiguration
    candidate_move_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """校验固定配置并规范化候选池。

        Raises:
            OneOnOneContractError: 固定配置或候选池违反公开合同时抛出。
        """
        if not isinstance(self.fixed, FixedPokemonConfiguration):
            raise OneOnOneContractError("fixed must be FixedPokemonConfiguration")
        pool = MoveCandidatePool(tuple(self.candidate_move_ids))
        object.__setattr__(self, "candidate_move_ids", pool.candidate_move_ids)

    @property
    def move_set_count(self) -> int:
        """返回该侧候选池生成的无序技能组数量。"""
        return count_move_sets(len(self.candidate_move_ids))

    def iter_move_sets(self) -> Iterator[tuple[int, ...]]:
        """按字典序迭代该侧规范化技能组。

        Returns:
            与 ``MoveCandidatePool.iter_move_sets`` 语义一致的技能组迭代器。
        """
        return MoveCandidatePool(self.candidate_move_ids).iter_move_sets()


@dataclass(frozen=True, slots=True)
class OneOnOneMovePoolCommand:
    """声明通用双方固定配置与候选招式池的批量推演输入。

    Args:
        ruleset_id: 规则集稳定标识。
        version_group_id: PokeAPI version group 正整数 ID。
        calculation_revision: 顶层计算和缓存语义的不兼容版本。
        attacker: 攻击方固定配置和候选招式池。
        defender: 防守方固定配置和候选招式池。
        dimensions: 首版各配置维度模式。
        weight_assumption: 配置对聚合权重假设。
        attacker_policy: 攻击方行动策略。
        defender_policy: 防守方行动策略。
        mechanism_admission: 候选机制准入规则。
        contract_version: DTO 与 fixture 的公开合同版本。
    """

    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    attacker: PokemonMovePoolSelection
    defender: PokemonMovePoolSelection
    dimensions: OneOnOneDimensionModes = OneOnOneDimensionModes()
    weight_assumption: OneOnOneConfigurationWeightAssumption = (
        OneOnOneConfigurationWeightAssumption.UNIFORM_CONFIGURATION_PAIR
    )
    attacker_policy: OneOnOneActionPolicy = (
        OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION
    )
    defender_policy: OneOnOneActionPolicy = (
        OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION
    )
    mechanism_admission: MechanismAdmissionPolicy = (
        MechanismAdmissionPolicy.SUPPORTED_ONLY
    )
    contract_version: str = ONE_ON_ONE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        """校验规则轴、总候选预算和所有显式策略字段。

        Raises:
            OneOnOneContractError: 合同版本、规则轴、类型或总候选数不合法时抛出。
        """
        if self.contract_version != ONE_ON_ONE_CONTRACT_VERSION:
            raise OneOnOneContractError("unsupported one-on-one contract version")
        _require_identity_text("ruleset_id", self.ruleset_id)
        _require_positive_integer("version_group_id", self.version_group_id)
        _require_identity_text("calculation_revision", self.calculation_revision)
        if not isinstance(self.attacker, PokemonMovePoolSelection):
            raise OneOnOneContractError("attacker must be PokemonMovePoolSelection")
        if not isinstance(self.defender, PokemonMovePoolSelection):
            raise OneOnOneContractError("defender must be PokemonMovePoolSelection")
        if not isinstance(self.dimensions, OneOnOneDimensionModes):
            raise OneOnOneContractError("dimensions must be OneOnOneDimensionModes")
        if not isinstance(
            self.weight_assumption, OneOnOneConfigurationWeightAssumption
        ):
            raise OneOnOneContractError("weight_assumption must be explicit")
        if not isinstance(self.attacker_policy, OneOnOneActionPolicy):
            raise OneOnOneContractError("attacker_policy must be explicit")
        if not isinstance(self.defender_policy, OneOnOneActionPolicy):
            raise OneOnOneContractError("defender_policy must be explicit")
        if not isinstance(self.mechanism_admission, MechanismAdmissionPolicy):
            raise OneOnOneContractError("mechanism_admission must be explicit")
        if self.total_candidate_move_count > MAX_TOTAL_CANDIDATE_MOVES:
            raise OneOnOneContractError(
                "attacker and defender candidate moves must total at most 20"
            )

    @property
    def total_candidate_move_count(self) -> int:
        """返回双方候选招式总数，用于前后端共享的 20 招预算。"""
        return len(self.attacker.candidate_move_ids) + len(self.defender.candidate_move_ids)

    @property
    def configuration_pair_count(self) -> int:
        """返回双方无序技能组的笛卡尔积数量。"""
        return self.attacker.move_set_count * self.defender.move_set_count

    def iter_configurations(self) -> Iterator[NormalizedOneOnOneConfiguration]:
        """按规范化顺序惰性生成全部配置对。

        Returns:
            不包含状态图或概率结果的规范化配置迭代器，最坏为 10+10 时的 44,100 项。
        """
        for attacker_move_ids in self.attacker.iter_move_sets():
            for defender_move_ids in self.defender.iter_move_sets():
                yield NormalizedOneOnOneConfiguration(
                    ruleset_id=self.ruleset_id,
                    version_group_id=self.version_group_id,
                    calculation_revision=self.calculation_revision,
                    attacker=self.attacker.fixed,
                    attacker_move_ids=attacker_move_ids,
                    defender=self.defender.fixed,
                    defender_move_ids=defender_move_ids,
                    contract_version=self.contract_version,
                )


@dataclass(frozen=True, slots=True)
class NormalizedOneOnOneConfiguration:
    """保存一个与用户点击顺序和初始招式槽排列无关的配置对。"""

    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    attacker: FixedPokemonConfiguration
    attacker_move_ids: tuple[int, ...]
    defender: FixedPokemonConfiguration
    defender_move_ids: tuple[int, ...]
    contract_version: str = ONE_ON_ONE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        """规范化双方技能组并校验配置身份字段。

        Raises:
            OneOnOneContractError: 身份字段、技能组大小、ID 或重复项不合法时抛出。
        """
        if self.contract_version != ONE_ON_ONE_CONTRACT_VERSION:
            raise OneOnOneContractError("unsupported one-on-one contract version")
        _require_identity_text("ruleset_id", self.ruleset_id)
        _require_positive_integer("version_group_id", self.version_group_id)
        _require_identity_text("calculation_revision", self.calculation_revision)
        if not isinstance(self.attacker, FixedPokemonConfiguration):
            raise OneOnOneContractError("attacker must be FixedPokemonConfiguration")
        if not isinstance(self.defender, FixedPokemonConfiguration):
            raise OneOnOneContractError("defender must be FixedPokemonConfiguration")
        object.__setattr__(
            self,
            "attacker_move_ids",
            _normalize_move_set("attacker_move_ids", self.attacker_move_ids),
        )
        object.__setattr__(
            self,
            "defender_move_ids",
            _normalize_move_set("defender_move_ids", self.defender_move_ids),
        )

    @property
    def configuration_id(self) -> str:
        """返回跨 Python/TypeScript 一致的规范化配置 ID。

        ID 显式绑定合同版本、规则轴、计算修订、双方固定配置和排序后的招式 ID。
        当前使用可读 canonical JSON，后续若改为摘要算法必须提升合同版本。
        """
        canonical = json.dumps(
            self._canonical_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return f"one-on-one-configuration:{canonical}"

    def _canonical_payload(self) -> list[object]:
        """构造禁止依赖对象键顺序的数组型 canonical payload。

        Returns:
            可直接交给标准 JSON 编码器的嵌套数组；字段位置属于 v1 合同的一部分。
        """
        return [
            self.contract_version,
            self.ruleset_id,
            self.version_group_id,
            self.calculation_revision,
            _pokemon_identity_payload(self.attacker, self.attacker_move_ids),
            _pokemon_identity_payload(self.defender, self.defender_move_ids),
        ]


def _pokemon_identity_payload(
    configuration: FixedPokemonConfiguration,
    move_ids: tuple[int, ...],
) -> list[object]:
    """把一侧固定配置和规范化技能组转换为位置稳定的身份数组。"""
    return [
        configuration.pokemon_id,
        configuration.form_id,
        configuration.level,
        configuration.stat_profile_id,
        configuration.ability_identifier,
        configuration.item_identifier,
        list(move_ids),
    ]


@dataclass(frozen=True, slots=True)
class ConfigurationReference:
    """保存结果列表展示所需的配置 ID 与双方技能组。

    Args:
        configuration_id: 绑定固定配置、规则轴和计算修订的规范化 ID。
        attacker_move_ids: 攻击方当前配置的规范化技能组。
        defender_move_ids: 防守方当前配置的规范化技能组。
    """

    configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        """规范化技能组并校验配置 ID。

        Raises:
            OneOnOneContractError: 配置 ID 或任一技能组不合法时抛出。
        """
        _require_configuration_id(self.configuration_id)
        object.__setattr__(
            self,
            "attacker_move_ids",
            _normalize_move_set("attacker_move_ids", self.attacker_move_ids),
        )
        object.__setattr__(
            self,
            "defender_move_ids",
            _normalize_move_set("defender_move_ids", self.defender_move_ids),
        )


__all__ = [
    "OneOnOneDimensionModes",
    "FixedPokemonConfiguration",
    "MoveCandidatePool",
    "PokemonMovePoolSelection",
    "OneOnOneMovePoolCommand",
    "NormalizedOneOnOneConfiguration",
    "ConfigurationReference",
]
