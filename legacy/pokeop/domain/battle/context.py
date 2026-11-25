from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.items import DamageItem
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
    ability: DamageAbility = DamageAbility.UNKNOWN
    item: DamageItem = DamageItem.UNKNOWN
    can_evolve: bool = False
    grounding_state: GroundingState | None = None

    def __post_init__(self) -> None:
        """校验战斗快照必须有正等级，并且至少拥有一个属性。"""
        if self.level < 1:
            raise ValueError("level must be greater than 0")
        if not self.types:
            raise ValueError("pokemon must have at least one type")
        object.__setattr__(
            self,
            "ability",
            DamageAbility.from_identifier(self.ability),
        )
        object.__setattr__(
            self,
            "item",
            DamageItem.from_identifier(self.item),
        )


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

    调用方通过 DamageContextBuilder 组装该对象；伤害计算入口只消费这个
    已经归一化的上下文快照。
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


@dataclass(frozen=True)
class DamageContextBuilder:
    """负责逐步组装一次伤害计算上下文，避免计算入口承载大量可选参数。"""

    attacker: BattlePokemon
    defender: BattlePokemon
    move: BattleMove
    ruleset: "BattleRuleset | None" = None
    environment: BattleEnvironment | None = None
    is_critical: bool = False
    is_spread_move: bool = False
    is_protect_reduced: bool = False
    is_multi_target_battle: bool = False

    @classmethod
    def for_move(
        cls,
        *,
        attacker: BattlePokemon,
        defender: BattlePokemon,
        move: BattleMove,
    ) -> "DamageContextBuilder":
        """以伤害计算必需的三元组创建 builder。"""
        return cls(attacker=attacker, defender=defender, move=move)

    def with_ruleset(
        self,
        ruleset: "BattleRuleset | None",
    ) -> "DamageContextBuilder":
        """设置本次伤害计算使用的规则集。"""
        return replace(self, ruleset=ruleset)

    def with_environment(
        self,
        environment: BattleEnvironment,
    ) -> "DamageContextBuilder":
        """设置天气、场地、双方场地状态等战斗环境。"""
        return replace(self, environment=environment)

    def with_critical_hit(self, enabled: bool = True) -> "DamageContextBuilder":
        """设置本次伤害是否按会心一击计算。"""
        return replace(self, is_critical=enabled)

    def as_spread_move(self, enabled: bool = True) -> "DamageContextBuilder":
        """设置本次招式是否按范围招式处理。"""
        return replace(self, is_spread_move=enabled)

    def with_protect_reduction(self, enabled: bool = True) -> "DamageContextBuilder":
        """设置本次伤害是否受到守住类效果削减。"""
        return replace(self, is_protect_reduced=enabled)

    def in_multi_target_battle(self, enabled: bool = True) -> "DamageContextBuilder":
        """设置当前战斗是否存在多个目标。"""
        return replace(self, is_multi_target_battle=enabled)

    def build(self) -> DamageContext:
        """构建供伤害责任链消费的不可变上下文。"""
        return DamageContext(
            attacker=self.attacker,
            defender=self.defender,
            move=self.move,
            ruleset=self.ruleset,
            environment=self.environment or BattleEnvironment(),
            is_critical=self.is_critical,
            is_spread_move=self.is_spread_move,
            is_protect_reduced=self.is_protect_reduced,
            is_multi_target_battle=self.is_multi_target_battle,
        )


__all__ = [
    "BattleMove",
    "BattlePokemon",
    "DamageAbility",
    "DamageContext",
    "DamageContextBuilder",
    "DamageItem",
    "MoveCategory",
]
