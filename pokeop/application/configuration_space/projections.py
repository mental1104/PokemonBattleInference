"""定义配置空间生成器消费的 version-aware 候选 projection。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    MechanismSupportStatus,
    _is_positive_integer,
)
from pokeop.domain.battle.effects.registry import normalize_effect_identifier
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


@dataclass(frozen=True, slots=True)
class MoveConfigurationCandidate:
    """表示 repository 提供的一条合法且 version-aware 的招式候选。

    Args:
        move_spec: 已解析为 domain ``MoveSpec`` 的稳定战斗字段。
        effect_identifier: 交给规则集 effect factory 的招式机制标识；None 表示该招式
            只依赖基础伤害、命中、优先级和 PP 等已有通用行为。
        support_status: repository 对该候选当前机制覆盖程度的声明。
        support_reason: 对 partial/unsupported 或特殊 supported 映射的解释。
    """

    move_spec: MoveSpec
    effect_identifier: str | None = None
    support_status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED
    support_reason: str = "Repository projection marks this move candidate as supported."

    def __post_init__(self) -> None:
        """校验候选并兼容 effect 标识位于 projection 或 MoveSpec 的两种形状。"""
        if not isinstance(self.move_spec, MoveSpec):
            raise ConfigurationSpaceError("move_spec must be a MoveSpec")
        if self.effect_identifier is not None and not isinstance(
            self.effect_identifier,
            str,
        ):
            raise ConfigurationSpaceError(
                "effect_identifier must be a string or None"
            )
        candidate_identifier = (
            normalize_effect_identifier(self.effect_identifier)
            if self.effect_identifier is not None
            else ""
        )
        move_spec_identifier = getattr(self.move_spec, "effect_identifier", None)
        if move_spec_identifier is not None and not isinstance(move_spec_identifier, str):
            raise ConfigurationSpaceError(
                "MoveSpec effect_identifier must be a string or None"
            )
        normalized_move_spec_identifier = (
            normalize_effect_identifier(move_spec_identifier)
            if move_spec_identifier is not None
            else ""
        )
        if (
            candidate_identifier
            and normalized_move_spec_identifier
            and candidate_identifier != normalized_move_spec_identifier
        ):
            raise ConfigurationSpaceError(
                "candidate and MoveSpec effect identifiers must describe the same behavior"
            )
        object.__setattr__(
            self,
            "effect_identifier",
            candidate_identifier or normalized_move_spec_identifier or None,
        )
        if not isinstance(self.support_status, MechanismSupportStatus):
            raise ConfigurationSpaceError(
                "support_status must be a MechanismSupportStatus"
            )
        if not isinstance(self.support_reason, str) or not self.support_reason.strip():
            raise ConfigurationSpaceError(
                "support_reason must be a non-blank string"
            )

    @property
    def identifier(self) -> str:
        """返回覆盖报告使用的稳定招式标识。"""
        return str(self.move_spec.move_id)


@dataclass(frozen=True, slots=True)
class AbilityConfigurationCandidate:
    """表示 repository 提供的一项当前规则集合法特性候选。

    Args:
        identifier: 可交给规则集 effect factory 的稳定特性标识。
        support_status: repository 对当前特性读取和机制映射的覆盖声明。
        support_reason: 对当前覆盖状态的解释，必须可直接进入诊断结果。
    """

    identifier: str
    support_status: MechanismSupportStatus = MechanismSupportStatus.SUPPORTED
    support_reason: str = "Repository projection marks this ability as supported."

    def __post_init__(self) -> None:
        """拒绝空标识和缺少原因的覆盖声明。"""
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ConfigurationSpaceError(
                "ability identifier must be a non-blank string"
            )
        if not isinstance(self.support_status, MechanismSupportStatus):
            raise ConfigurationSpaceError(
                "support_status must be a MechanismSupportStatus"
            )
        if not isinstance(self.support_reason, str) or not self.support_reason.strip():
            raise ConfigurationSpaceError(
                "support_reason must be a non-blank string"
            )


@dataclass(frozen=True, slots=True)
class PokemonConfigurationProfile:
    """保存配置生成器消费的 version-aware Pokémon 读取模型。

    该 DTO 位于 application 边界，不包含 SQLAlchemy row、PokeAPI 历史表或 session。
    #31 的 repository implementation 只需把数据库结果映射成该稳定形状，配置生成器
    无需知道候选来自 PostgreSQL、fake repository 还是测试夹具。

    Args:
        ruleset_id: 当前规则集稳定标识。
        version_group_id: repository 已完成历史还原的 PokeAPI version group 主轴。
        pokemon_id: 当前规则集下的 Pokémon 稳定 ID。
        name: 用于结果解释的规范化名称。
        types: 当前 version group 下的一到两个属性。
        base_stats: 当前形态的六项种族值。
        moves: 当前规则集可学习的招式候选。
        abilities: 当前规则集合法的特性候选。
        can_evolve: 是否仍可进化，供后续 domain 道具规则使用。
    """

    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    name: str
    types: tuple[Type, ...]
    base_stats: StatValues
    moves: tuple[MoveConfigurationCandidate, ...]
    abilities: tuple[AbilityConfigurationCandidate, ...]
    can_evolve: bool = False

    def __post_init__(self) -> None:
        """规范化集合并校验 repository projection 的稳定业务字段。"""
        if not isinstance(self.ruleset_id, str) or not self.ruleset_id.strip():
            raise ConfigurationSpaceError("ruleset_id must be a non-blank string")
        if not _is_positive_integer(self.version_group_id):
            raise ConfigurationSpaceError(
                "version_group_id must be a positive integer"
            )
        if not _is_positive_integer(self.pokemon_id):
            raise ConfigurationSpaceError("pokemon_id must be a positive integer")
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.name != self.name.strip()
        ):
            raise ConfigurationSpaceError(
                "name must be a normalized non-empty string"
            )
        if not isinstance(self.base_stats, StatValues):
            raise ConfigurationSpaceError("base_stats must be a StatValues")
        base_stat_values = (
            self.base_stats.hp,
            self.base_stats.attack,
            self.base_stats.defense,
            self.base_stats.special_attack,
            self.base_stats.special_defense,
            self.base_stats.speed,
        )
        if any(not _is_positive_integer(value) for value in base_stat_values):
            raise ConfigurationSpaceError(
                "base_stats values must be positive integers"
            )
        if not isinstance(self.can_evolve, bool):
            raise ConfigurationSpaceError("can_evolve must be a bool")

        normalized_types = tuple(self.types)
        if not 1 <= len(normalized_types) <= 2:
            raise ConfigurationSpaceError("types must contain one or two values")
        if any(not isinstance(value, Type) for value in normalized_types):
            raise ConfigurationSpaceError("types must contain only Type values")
        type_ids = tuple(value.value for value in normalized_types)
        if len(type_ids) != len(set(type_ids)):
            raise ConfigurationSpaceError("types must be unique")

        normalized_moves = tuple(self.moves)
        normalized_abilities = tuple(self.abilities)
        if not normalized_moves:
            raise ConfigurationSpaceError("moves must not be empty")
        if not normalized_abilities:
            raise ConfigurationSpaceError("abilities must not be empty")
        if any(not isinstance(value, MoveConfigurationCandidate) for value in normalized_moves):
            raise ConfigurationSpaceError(
                "moves must contain only MoveConfigurationCandidate values"
            )
        if any(
            not isinstance(value, AbilityConfigurationCandidate)
            for value in normalized_abilities
        ):
            raise ConfigurationSpaceError(
                "abilities must contain only AbilityConfigurationCandidate values"
            )

        object.__setattr__(self, "types", normalized_types)
        object.__setattr__(self, "moves", normalized_moves)
        object.__setattr__(self, "abilities", normalized_abilities)




__all__ = [
    "AbilityConfigurationCandidate",
    "MoveConfigurationCandidate",
    "PokemonConfigurationProfile",
]
