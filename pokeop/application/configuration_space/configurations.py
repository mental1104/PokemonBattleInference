"""定义不可变、可哈希的单边与双方战斗配置模型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable

from pokeop.application.configuration_space.model_base import (
    ConfigurationSpaceError,
    _is_integer,
    _is_positive_integer,
)
from pokeop.domain.battle.specs import MoveSpec, MoveSpecKey
from pokeop.domain.battle.stats import StatProfile, StatValues
from pokeop.domain.models.types import Type


@dataclass(frozen=True, slots=True)
class ConfiguredMove:
    """保存进入配置结果的招式快照及其已验证 effect 标识。

    Args:
        move_spec: 已通过合法性与覆盖筛选的 domain 招式配置。
        effect_identifier: factory 返回的规范化机制标识；None 表示仅使用通用伤害行为。
    """

    move_spec: MoveSpec
    effect_identifier: str | None

    def __post_init__(self) -> None:
        """校验招式对象和可选机制标识，避免无效对象进入行为签名。"""
        if not isinstance(self.move_spec, MoveSpec):
            raise ConfigurationSpaceError("move_spec must be a MoveSpec")
        if self.effect_identifier is not None and not self.effect_identifier.strip():
            raise ConfigurationSpaceError("effect_identifier must be non-blank or None")

    @property
    def behavior_signature(self) -> tuple[MoveSpecKey, str]:
        """返回同时覆盖通用招式字段和具体机制标识的稳定行为签名。"""
        return (
            self.move_spec.state_key,
            self.effect_identifier if self.effect_identifier is not None else "none",
        )


@dataclass(frozen=True, slots=True, eq=False)
class PokemonBattleConfiguration:
    """表示一只 Pokémon 已完成四维枚举后的不可变 application 配置。

    该对象保留 representative 的 EV/性格来源用于解释，但行为判等只使用最终实际
    能力值、已验证机制标识和招式行为签名，因此多个 EV 整数方案可安全归并到同一类。

    Args:
        ruleset_id: 本配置适用的稳定规则集标识，参与跨规则集缓存判等。
        version_group_id: repository 已完成历史还原的 version group 主轴。
        pokemon_id: 当前规则集中的 Pokémon 稳定 ID。
        name: 仅用于解释和展示的规范化名称。
        level: 实际能力值计算使用的战斗等级。
        types: 当前 version group 下的一到两个属性。
        stats: 已计算完成的最终六项能力值。
        stat_profile: 当前等价类保留的代表 EV、IV 和性格来源。
        moves: 一到四个已验证机制覆盖的招式配置。
        ability_identifier: factory 返回的规范化特性标识。
        item_identifier: factory 返回的规范化道具标识，``none`` 表示无道具。
        can_evolve: 是否仍可进化，供后续道具规则使用。
        dimension_labels: 各 provider 为代表配置生成的解释标签。
        extra_dimensions: 主循环未知但参与行为判等的扩展维度签名。
    """

    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    name: str
    level: int
    types: tuple[Type, ...]
    stats: StatValues
    stat_profile: StatProfile
    moves: tuple[ConfiguredMove, ...]
    ability_identifier: str
    item_identifier: str
    can_evolve: bool
    dimension_labels: tuple[tuple[str, str], ...] = ()
    extra_dimensions: tuple[tuple[str, Hashable], ...] = ()

    def __post_init__(self) -> None:
        """校验最终配置仍满足缓存、解释和后续状态构造所需的不变量。"""
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
        if not _is_integer(self.level) or not 1 <= self.level <= 100:
            raise ConfigurationSpaceError("level must be an integer from 1 to 100")
        if not isinstance(self.stats, StatValues) or not isinstance(
            self.stat_profile, StatProfile
        ):
            raise ConfigurationSpaceError("stats and stat_profile must use domain models")
        if not 1 <= len(self.types) <= 2 or any(
            not isinstance(value, Type) for value in self.types
        ):
            raise ConfigurationSpaceError("types must contain one or two Type values")
        if not 1 <= len(self.moves) <= 4 or any(
            not isinstance(value, ConfiguredMove) for value in self.moves
        ):
            raise ConfigurationSpaceError(
                "moves must contain between one and four ConfiguredMove values"
            )
        move_ids = tuple(move.move_spec.move_id for move in self.moves)
        if len(move_ids) != len(set(move_ids)):
            raise ConfigurationSpaceError("configured move ids must be unique")
        if (
            not isinstance(self.ability_identifier, str)
            or not self.ability_identifier.strip()
            or not isinstance(self.item_identifier, str)
            or not self.item_identifier.strip()
        ):
            raise ConfigurationSpaceError(
                "ability and item identifiers must be non-blank strings"
            )
        if not isinstance(self.can_evolve, bool):
            raise ConfigurationSpaceError("can_evolve must be a bool")
        for dimension_key, signature in self.extra_dimensions:
            if not dimension_key.strip():
                raise ConfigurationSpaceError("extra dimension keys must not be blank")
            hash(signature)

    @property
    def behavior_signature(self) -> tuple[Hashable, ...]:
        """返回只包含当前已支持机制未来战斗行为的稳定归并签名。"""
        return (
            self.ruleset_id,
            self.version_group_id,
            self.pokemon_id,
            self.level,
            tuple(value.value for value in self.types),
            (
                self.stats.hp,
                self.stats.attack,
                self.stats.defense,
                self.stats.special_attack,
                self.stats.special_defense,
                self.stats.speed,
            ),
            tuple(move.behavior_signature for move in self.moves),
            self.ability_identifier,
            self.item_identifier,
            self.can_evolve,
            self.extra_dimensions,
        )

    def __hash__(self) -> int:
        """按行为签名计算哈希，使 representative 可安全用于缓存和集合。"""
        return hash(self.behavior_signature)

    def __eq__(self, other: object) -> bool:
        """忽略原始 EV/性格来源，仅比较当前机制下可证明等价的战斗行为。"""
        return (
            isinstance(other, PokemonBattleConfiguration)
            and self.behavior_signature == other.behavior_signature
        )


@dataclass(frozen=True, slots=True, eq=False)
class BattleConfiguration:
    """表示一次 1v1 状态图求解前的双方不可变配置对。"""

    attacker: PokemonBattleConfiguration
    defender: PokemonBattleConfiguration

    @property
    def behavior_signature(self) -> tuple[Hashable, Hashable]:
        """返回双方行为签名组成的稳定配置对键。"""
        return (
            self.attacker.behavior_signature,
            self.defender.behavior_signature,
        )

    def __hash__(self) -> int:
        """按双方行为签名计算哈希，便于缓存固定配置对求解结果。"""
        return hash(self.behavior_signature)

    def __eq__(self, other: object) -> bool:
        """按当前支持机制下的双方未来战斗行为比较配置对。"""
        return (
            isinstance(other, BattleConfiguration)
            and self.behavior_signature == other.behavior_signature
        )




__all__ = [
    "BattleConfiguration",
    "ConfiguredMove",
    "PokemonBattleConfiguration",
]
