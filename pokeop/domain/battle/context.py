from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.models.types import Type

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


class MoveCategory(str, Enum):
    """表示招式伤害分类，用于决定取攻击/防御还是特攻/特防。"""

    PHYSICAL = "physical"
    SPECIAL = "special"
    STATUS = "status"


@dataclass(frozen=True)
class BattlePokemon:
    """
    表示已经进入一次伤害计算的宝可梦快照。

    这里保存的是计算时需要的最终等级、属性和实际能力值；
    它不关心这些数据来自数据库、CSV、测试夹具还是 application preset。
    """

    name: str
    level: int
    types: tuple[Type, ...]
    stats: StatValues
    ability: str | None = None
    item: str | None = None
    can_evolve: bool = False
    grounding_state: GroundingState | None = None

    def __post_init__(self) -> None:
        """校验战斗快照必须有正等级，并且至少拥有一个属性。"""
        if self.level < 1:
            raise ValueError("level must be greater than 0")
        if not self.types:
            raise ValueError("pokemon must have at least one type")


@dataclass(frozen=True)
class BattleMove:
    """
    表示一次伤害计算中使用的招式快照。

    本阶段只需要名称、属性、分类和威力；命中、优先级、多段等规则后续另行扩展。
    """

    name: str
    type: Type
    category: MoveCategory
    power: int

    def __post_init__(self) -> None:
        """校验物理/特殊招式必须有正威力，变化招式暂不参与直接伤害。"""
        if self.category is not MoveCategory.STATUS and self.power <= 0:
            raise ValueError("damaging moves must have positive power")


@dataclass(frozen=True)
class DamageContext:
    """
    表示一次完整伤害计算所需的纯 domain 输入。

    旧入口仍可分别传 attacker、defender、move；新机制统一通过该对象携带
    ruleset 和 BattleEnvironment，方便天气、场地、特性、道具共享上下文。
    """

    attacker: BattlePokemon
    defender: BattlePokemon
    move: BattleMove
    ruleset: "BattleRuleset | None" = None
    environment: BattleEnvironment = field(default_factory=BattleEnvironment)
    is_critical: bool = False
    is_spread_move: bool = False
    is_protect_reduced: bool = False
    is_multi_target_battle: bool = False


__all__ = ["BattleMove", "BattlePokemon", "DamageContext", "MoveCategory"]
