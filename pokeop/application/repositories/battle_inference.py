"""定义 1v1 多回合推演使用的稳定 repository Protocol 与显式 projection。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


class MechanismSupportStatus(str, Enum):
    """描述合法战斗机制在当前 domain 实现中的覆盖程度。"""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    NO_EFFECT = "no_effect"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class MechanismCapability:
    """保存 persistence 边界识别出的稳定机制标识和覆盖结论。

    Args:
        source_kind: 机制来自招式、特性还是携带道具。
        identifier: 可交给 domain effect factory 的规范化稳定标识。
        status: 当前 domain 对该机制的支持程度；合法但未实现的机制必须显式保留。
        reason: 面向 application、诊断日志和覆盖报告的简短原因。
    """

    source_kind: EffectSourceKind
    identifier: str
    status: MechanismSupportStatus
    reason: str

    def __post_init__(self) -> None:
        """校验覆盖记录具有规范化标识、明确状态和可读原因。

        Raises:
            ValueError: 来源类型、稳定标识、支持状态或原因不满足读取合同时抛出。
        """
        if not isinstance(self.source_kind, EffectSourceKind):
            raise ValueError("source_kind must be an EffectSourceKind")
        if not self.identifier or self.identifier != self.identifier.strip():
            raise ValueError("capability identifier must be non-empty and normalized")
        if not isinstance(self.status, MechanismSupportStatus):
            raise ValueError("capability status must be explicit")
        if not self.reason or self.reason != self.reason.strip():
            raise ValueError("capability reason must be non-empty and normalized")


@dataclass(frozen=True, slots=True)
class BattleInferenceRulesetContext:
    """表示一次 version-aware 战斗读取使用的规则集上下文。

    Args:
        ruleset_id: 面向 application 和调用方的稳定规则集标识。
        ruleset_name: 规则集展示名称。
        generation_id: 规则集所属世代，用于解释历史属性和历史特性。
        version_group_id: 招式学习表、move changelog 和版本数据使用的主查询轴。
        version_group_identifier: PokeAPI 对应 version group 的稳定 identifier。
    """

    ruleset_id: str
    ruleset_name: str
    generation_id: int
    version_group_id: int
    version_group_identifier: str


@dataclass(frozen=True, slots=True)
class BattleInferenceTypeProfile:
    """表示已经从 PokeAPI 标识转换完成的战斗属性读取模型。

    Args:
        type_id: PokeAPI 中的属性稳定整数 ID。
        identifier: PokeAPI 属性 identifier。
        display_name: 当前规则集语言下的展示名称；缺失时回退到 identifier。
        domain_type: domain 伤害计算和状态模型使用的显式 ``Type`` 枚举。
    """

    type_id: int
    identifier: str
    display_name: str
    domain_type: Type


@dataclass(frozen=True, slots=True)
class BattleInferenceAbilityProfile:
    """表示一只宝可梦在指定 version group 下合法的一项特性。

    Args:
        ability_id: PokeAPI 中的特性稳定整数 ID。
        identifier: 可跨语言使用的特性 identifier。
        display_name: 当前规则集语言下的展示名称；缺失时回退到 identifier。
        slot: PokeAPI 特性槽位，用于区分同一宝可梦的普通与替代特性。
        is_hidden: 是否为隐藏特性。
        effect_identifier: 交给 domain effect factory 的稳定特性标识。
        capability: 当前 domain 对该合法特性的覆盖结论。
    """

    ability_id: int
    identifier: str
    display_name: str
    slot: int
    is_hidden: bool
    effect_identifier: str
    capability: MechanismCapability


@dataclass(frozen=True, slots=True)
class BattleInferenceMoveProfile:
    """表示指定 version group 下可供多回合推演消费的完整招式资料。

    Args:
        move_id: PokeAPI 中的招式稳定整数 ID。
        identifier: 可跨语言使用的招式 identifier。
        display_name: 当前规则集语言下的展示名称；缺失时回退到 identifier。
        type: 已转换为 domain ``Type`` 的属性读取模型。
        category: 物理、特殊或变化招式分类。
        power: 当前 version group 的基础威力；变化威力或变化招式使用 None。
        pp: 当前 version group 的基础最大 PP，未应用 PP Max。
        accuracy: 百分制基础命中率；必中特殊语义使用 None。
        priority: 当前 version group 的行动优先级。
        target_id: PokeAPI 中的招式目标稳定整数 ID。
        target_identifier: 招式目标的稳定 identifier。
        effect_id: PokeAPI move effect ID，仅用于追踪和映射边界，不进入 domain。
        effect_chance: 百分制附加效果概率；没有独立概率字段时使用 None。
        effect_identifier: 可交给 domain effect factory 的稳定招式机制标识；纯基础伤害为 None。
        capability: 当前 domain 对该合法招式机制的覆盖结论。
    """

    move_id: int
    identifier: str
    display_name: str
    type: BattleInferenceTypeProfile
    category: MoveCategory
    power: int | None
    pp: int
    accuracy: int | None
    priority: int
    target_id: int
    target_identifier: str
    effect_id: int | None
    effect_chance: int | None
    effect_identifier: str | None
    capability: MechanismCapability

    def __post_init__(self) -> None:
        """校验回合推进依赖的 PP、命中率、优先级和效果概率边界。

        Raises:
            ValueError: PP 非正、命中率或效果概率越界、优先级类型非法时抛出。
        """
        if isinstance(self.pp, bool) or self.pp <= 0:
            raise ValueError("move pp must be greater than 0")
        if self.accuracy is not None and (
            isinstance(self.accuracy, bool) or not 1 <= self.accuracy <= 100
        ):
            raise ValueError("move accuracy must be between 1 and 100 or None")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise ValueError("move priority must be an integer")
        if self.effect_chance is not None and (
            isinstance(self.effect_chance, bool) or not 1 <= self.effect_chance <= 100
        ):
            raise ValueError("effect chance must be between 1 and 100 or None")


@dataclass(frozen=True, slots=True)
class BattleInferenceItemProfile:
    """表示本轮配置枚举允许选择的一项受控携带道具。

    Args:
        item_id: PokeAPI 中的道具 ID；不携带道具的合成候选使用 None。
        identifier: 跨语言稳定 identifier；不携带道具固定使用 ``none``。
        display_name: 当前规则集语言下的展示名称。
        effect_identifier: 交给 domain effect factory 的稳定道具标识；不携带时为 None。
        capability: 当前 domain 对该候选道具的覆盖结论。
    """

    item_id: int | None
    identifier: str
    display_name: str
    effect_identifier: str | None
    capability: MechanismCapability


@dataclass(frozen=True, slots=True)
class BattleInferencePokemonProfile:
    """表示指定规则集和 version group 下的一只完整推演 Pokémon profile。

    Args:
        pokemon_id: PokeAPI 中的 Pokémon 稳定整数 ID。
        identifier: Pokémon 或具体形态的稳定 identifier。
        display_name: 当前规则集语言下的展示名称。
        species_id: 对应物种稳定整数 ID。
        species_identifier: 对应物种稳定 identifier。
        form_identifier: 默认形态 identifier；无法识别时为 None。
        is_default_form: 是否为该 Pokémon 的默认形态。
        is_battle_only_form: 是否仅在战斗中存在。
        is_mega_form: 是否为 Mega 形态。
        types: 当前 generation 已还原历史差异的一到两个属性。
        base_stats: 六项种族值；实际能力值仍由 application/domain 配置生成器计算。
        can_evolve: 当前物种是否存在直接进化后继，供进化奇石等规则使用。
        abilities: 当前 generation 已还原历史差异的全部合法特性；无特性世代允许为空。
        moves: 当前 version group 中全部合法招式，不静默过滤未支持机制。
    """

    pokemon_id: int
    identifier: str
    display_name: str
    species_id: int
    species_identifier: str
    form_identifier: str | None
    is_default_form: bool
    is_battle_only_form: bool
    is_mega_form: bool
    types: tuple[BattleInferenceTypeProfile, ...]
    base_stats: StatValues
    can_evolve: bool
    abilities: tuple[BattleInferenceAbilityProfile, ...]
    moves: tuple[BattleInferenceMoveProfile, ...]

    def __post_init__(self) -> None:
        """校验完整 profile 至少包含一个属性和一个合法招式。

        Raises:
            ValueError: persistence 返回不完整或存在重复稳定 ID 的 profile 时抛出。
        """
        if not 1 <= len(self.types) <= 2:
            raise ValueError("pokemon profile must contain one or two types")
        if not self.moves:
            raise ValueError("pokemon profile must contain at least one legal move")
        ability_ids = tuple(ability.ability_id for ability in self.abilities)
        move_ids = tuple(move.move_id for move in self.moves)
        if len(ability_ids) != len(set(ability_ids)):
            raise ValueError("pokemon profile ability ids must be unique")
        if len(move_ids) != len(set(move_ids)):
            raise ValueError("pokemon profile move ids must be unique")


@runtime_checkable
class BattleInferenceRepository(Protocol):
    """application 读取完整 1v1 推演资料所依赖的持久化端口。

    实现负责 SQL、session、物化视图和 PokeAPI 历史语义；application 只消费稳定、
    显式、可由 fake repository 替换的 projection。
    """

    def get_ruleset_context(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> BattleInferenceRulesetContext | None:
        """按完整规则轴读取上下文。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 必须与规则集上下文一致的 version group ID。

        Returns:
            找到精确组合时返回规则集上下文；不存在时返回 None。
        """
        ...

    def get_pokemon_profile(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
        pokemon_id: int,
    ) -> BattleInferencePokemonProfile | None:
        """读取指定规则轴下的一只完整 Pokémon profile。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 招式合法性和历史数据还原使用的 version group ID。
            pokemon_id: 需要加载的 Pokémon 稳定整数 ID。

        Returns:
            找到时返回完整 profile；规则轴或 Pokémon 不存在时返回 None。
        """
        ...

    def list_item_candidates(
        self,
        *,
        ruleset_id: str,
        version_group_id: int,
    ) -> tuple[BattleInferenceItemProfile, ...]:
        """列出本轮配置枚举允许使用的受控道具候选。

        Args:
            ruleset_id: 调用方请求的稳定规则集标识。
            version_group_id: 用于确定 generation 和道具在该世代是否已经存在。

        Returns:
            包含不携带道具候选的稳定有序元组；未知或不匹配规则轴返回空元组。
        """
        ...


__all__ = [
    "BattleInferenceAbilityProfile",
    "BattleInferenceItemProfile",
    "BattleInferenceMoveProfile",
    "BattleInferencePokemonProfile",
    "BattleInferenceRepository",
    "BattleInferenceRulesetContext",
    "BattleInferenceTypeProfile",
    "MechanismCapability",
    "MechanismSupportStatus",
]
