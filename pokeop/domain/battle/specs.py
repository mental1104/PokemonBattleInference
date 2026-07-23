from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type


class InvalidBattleState(ValueError):
    """表示 1v1 战斗配置或动态状态违反了领域不变量。"""


@dataclass(frozen=True, slots=True)
class MoveSpecKey:
    """表示影响后续战斗结果的招式配置规范化键。

    招式名称属于展示信息，因此不会进入键；招式 ID、属性、分类、威力、命中率、
    最大 PP 和优先级会影响合法行动、行动顺序或状态转移，必须参与状态去重。
    """

    move_id: int
    move_type_id: int
    category: MoveCategory
    power: int
    accuracy: int | None
    max_pp: int
    priority: int


@dataclass(frozen=True, slots=True, eq=False)
class MoveSpec:
    """表示一只宝可梦携带的不可变招式配置。

    Args:
        move_id: 规则集内稳定的招式 ID，必须为正整数。
        move: 现有伤害计算入口使用的只读招式快照。
        max_pp: 当前规则集和配置下的最大 PP，必须大于 0。
        priority: 当前规则集下的招式优先级；数值越大越早执行。
        accuracy: 百分制基础命中率，必须位于 1 到 100；None 表示跳过普通命中判定。
    """

    move_id: int
    move: BattleMove
    max_pp: int
    priority: int = 0
    accuracy: int | None = 100

    def __post_init__(self) -> None:
        """校验招式 ID、PP、优先级和基础命中率。

        Raises:
            InvalidBattleState: 任一招式配置字段不满足稳定领域合同时抛出。
        """
        if isinstance(self.move_id, bool) or self.move_id <= 0:
            raise InvalidBattleState("move_id must be greater than 0")
        if not isinstance(self.move, BattleMove):
            raise InvalidBattleState("move must be a BattleMove")
        if isinstance(self.max_pp, bool) or self.max_pp <= 0:
            raise InvalidBattleState("max_pp must be greater than 0")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise InvalidBattleState("move priority must be an integer")
        if self.accuracy is not None and (
            isinstance(self.accuracy, bool) or not 1 <= self.accuracy <= 100
        ):
            raise InvalidBattleState(
                "move accuracy must be between 1 and 100 or None"
            )

    @property
    def state_key(self) -> MoveSpecKey:
        """返回排除展示名称后的稳定招式配置键。

        Returns:
            包含招式 ID、战斗属性、伤害分类、威力、命中率、最大 PP 和优先级的键。
        """
        return MoveSpecKey(
            move_id=self.move_id,
            move_type_id=self.move.type.value,
            category=self.move.category,
            power=self.move.power,
            accuracy=self.accuracy,
            max_pp=self.max_pp,
            priority=self.priority,
        )

    def __hash__(self) -> int:
        """按战斗语义键计算哈希值，避开 Type 枚举当前不可哈希的问题。"""
        return hash(self.state_key)

    def __eq__(self, other: object) -> bool:
        """按战斗语义比较招式配置，忽略不会影响结果的展示名称。"""
        return isinstance(other, MoveSpec) and self.state_key == other.state_key


@dataclass(frozen=True, slots=True)
class PokemonSpecKey:
    """表示影响未来战斗结果的宝可梦不变配置键。"""

    pokemon_id: int
    level: int
    type_ids: tuple[int, ...]
    stats: tuple[int, int, int, int, int, int]
    ability: DamageAbility
    item: DamageItem
    can_evolve: bool
    grounding_state: GroundingState | None
    moves: tuple[MoveSpecKey, ...]


@dataclass(frozen=True, slots=True, eq=False)
class PokemonSpec:
    """表示跨回合保持不变的宝可梦战斗配置。

    该对象位于纯 domain 层，只保存已经解析完成的等级、属性、最终能力值、特性、
    道具和招式配置；它不知道这些数据来自数据库、CSV、API 还是测试夹具。

    Args:
        pokemon_id: 当前规则集中的宝可梦稳定 ID，必须为正整数。
        name: 供现有 DamageContext 展示和 trace 使用的名称，不进入 StateKey。
        level: 战斗等级，必须位于 1 到 100。
        types: 一到两个互不重复的战斗属性。
        stats: 已经计算完成的六项实际能力值，每项必须大于 0。
        ability: 已归一化或可由 DamageAbility 解析的特性。
        item: 已归一化或可由 DamageItem 解析的携带道具。
        moves: 一到四个互不重复的招式配置。
        can_evolve: 是否仍可进化，供进化奇石等既有伤害规则使用。
        grounding_state: 可选的接地状态覆盖；None 表示沿用属性等默认规则。
    """

    pokemon_id: int
    name: str
    level: int
    types: tuple[Type, ...]
    stats: StatValues
    ability: DamageAbility = DamageAbility.UNKNOWN
    item: DamageItem = DamageItem.UNKNOWN
    moves: tuple[MoveSpec, ...] = ()
    can_evolve: bool = False
    grounding_state: GroundingState | None = None

    def __post_init__(self) -> None:
        """规范化枚举与元组，并校验不变配置的完整性。

        Raises:
            InvalidBattleState: ID、名称、等级、属性、能力值或招式配置非法时抛出。
        """
        if isinstance(self.pokemon_id, bool) or self.pokemon_id <= 0:
            raise InvalidBattleState("pokemon_id must be greater than 0")
        if not self.name or self.name != self.name.strip():
            raise InvalidBattleState("name must be a non-empty normalized value")
        if isinstance(self.level, bool) or not 1 <= self.level <= 100:
            raise InvalidBattleState("level must be between 1 and 100")

        if not isinstance(self.stats, StatValues):
            raise InvalidBattleState("stats must be a StatValues instance")
        if not isinstance(self.can_evolve, bool):
            raise InvalidBattleState("can_evolve must be a bool")
        if self.grounding_state is not None and not isinstance(
            self.grounding_state, GroundingState
        ):
            raise InvalidBattleState(
                "grounding_state must be a GroundingState or None"
            )

        normalized_types = tuple(self.types)
        if not 1 <= len(normalized_types) <= 2:
            raise InvalidBattleState("pokemon must have one or two types")
        if any(not isinstance(pokemon_type, Type) for pokemon_type in normalized_types):
            raise InvalidBattleState("pokemon types must be Type values")
        type_ids = tuple(pokemon_type.value for pokemon_type in normalized_types)
        if len(type_ids) != len(set(type_ids)):
            raise InvalidBattleState("pokemon types must be unique")

        for field_name, value in (
            ("hp", self.stats.hp),
            ("attack", self.stats.attack),
            ("defense", self.stats.defense),
            ("special_attack", self.stats.special_attack),
            ("special_defense", self.stats.special_defense),
            ("speed", self.stats.speed),
        ):
            if isinstance(value, bool) or value <= 0:
                raise InvalidBattleState(f"{field_name} stat must be greater than 0")

        normalized_moves = tuple(self.moves)
        if not 1 <= len(normalized_moves) <= 4:
            raise InvalidBattleState("pokemon must configure between one and four moves")
        if any(not isinstance(move, MoveSpec) for move in normalized_moves):
            raise InvalidBattleState("moves must contain only MoveSpec values")
        move_ids = tuple(move.move_id for move in normalized_moves)
        if len(move_ids) != len(set(move_ids)):
            raise InvalidBattleState("configured move ids must be unique")

        object.__setattr__(self, "types", normalized_types)
        object.__setattr__(self, "moves", normalized_moves)
        object.__setattr__(self, "ability", DamageAbility.from_identifier(self.ability))
        object.__setattr__(self, "item", DamageItem.from_identifier(self.item))

    def move_spec(self, move_id: int) -> MoveSpec:
        """按招式 ID 读取当前配置中的招式定义。

        Args:
            move_id: 需要查找的正整数招式 ID。

        Returns:
            与 move_id 对应的不可变 MoveSpec。

        Raises:
            InvalidBattleState: 当前配置没有该招式时抛出。
        """
        for move in self.moves:
            if move.move_id == move_id:
                return move
        raise InvalidBattleState(f"move_id {move_id} is not configured for pokemon")

    @property
    def state_key(self) -> PokemonSpecKey:
        """返回排除名称等展示信息后的稳定宝可梦配置键。

        Returns:
            可安全参与 StateKey 哈希与相等性判断的 PokemonSpecKey。
        """
        return PokemonSpecKey(
            pokemon_id=self.pokemon_id,
            level=self.level,
            type_ids=tuple(pokemon_type.value for pokemon_type in self.types),
            stats=(
                self.stats.hp,
                self.stats.attack,
                self.stats.defense,
                self.stats.special_attack,
                self.stats.special_defense,
                self.stats.speed,
            ),
            ability=self.ability,
            item=self.item,
            can_evolve=self.can_evolve,
            grounding_state=self.grounding_state,
            moves=tuple(move.state_key for move in self.moves),
        )

    def __hash__(self) -> int:
        """按战斗语义键计算哈希值，使配置可作为集合或字典键。"""
        return hash(self.state_key)

    def __eq__(self, other: object) -> bool:
        """按影响战斗结果的配置比较，忽略名称等展示字段。"""
        return isinstance(other, PokemonSpec) and self.state_key == other.state_key


__all__ = [
    "InvalidBattleState",
    "MoveSpec",
    "MoveSpecKey",
    "PokemonSpec",
    "PokemonSpecKey",
]
