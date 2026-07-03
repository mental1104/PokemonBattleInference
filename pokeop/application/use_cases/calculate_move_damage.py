from __future__ import annotations

from dataclasses import dataclass

from pokeop.domain.battle.context import (
    BattleMove,
    BattlePokemon,
    DamageContextBuilder,
    MoveCategory,
)
from pokeop.domain.battle.damage import DamageRollResult, calculate_damage_rolls
from pokeop.domain.battle.ko import KOChanceResult, estimate_ko_chance
from pokeop.domain.battle.stats import (
    StatProfile,
    StatValues,
    calculate_actual_stats,
)
from pokeop.domain.models.types import Type


@dataclass(frozen=True)
class PokemonBattleSnapshot:
    """
    application 层接收的一只宝可梦战斗快照。

    它描述用例调用者已经准备好的宝可梦名称、等级、属性和能力配置；
    用例会把 stat_profile 算成实际能力值，再组装成 domain 的 BattlePokemon。
    """

    name: str
    level: int
    types: tuple[Type, ...]
    stat_profile: StatProfile


@dataclass(frozen=True)
class MoveBattleSnapshot:
    """
    application 层接收的一次招式快照。

    本阶段不接数据库，所以招式名称、属性、分类和威力都由调用者直接传入；
    use case 会把它转换成 domain 的 BattleMove 后进入伤害计算。
    """

    name: str
    type: Type
    category: MoveCategory
    power: int


@dataclass(frozen=True)
class CalculateMoveDamageCommand:
    """
    计算单招伤害的 use case 输入命令。

    包含攻击方、防守方和招式三个快照，不包含 HTTP request、数据库 session 或 SQLAlchemy 对象。
    """

    attacker: PokemonBattleSnapshot
    defender: PokemonBattleSnapshot
    move: MoveBattleSnapshot


@dataclass(frozen=True)
class CalculateMoveDamageResult:
    """
    计算单招伤害的 use case 输出结果。

    返回双方实际能力值、完整伤害 roll 结果和 KO 概率，
    让测试或未来 API 层可以直接读取需要展示的字段。
    """

    attacker_stats: StatValues
    defender_stats: StatValues
    damage: DamageRollResult
    ko_chance: KOChanceResult


class CalculateMoveDamageUseCase:
    """
    编排单招伤害计算的 application use case。

    它负责把输入快照转换成 domain 对象，调用能力值、伤害和 KO 计算；
    它不查询数据库、不写 SQL，也不包含 FastAPI request/response 逻辑。
    """

    def execute(
        self,
        command: CalculateMoveDamageCommand,
    ) -> CalculateMoveDamageResult:
        """
        执行一次单招伤害计算。

        先根据双方 StatProfile 和等级计算实际能力值，再构造 BattlePokemon/BattleMove，
        最后调用 domain 伤害责任链和 KO 估算，返回聚合后的结果对象。
        """
        attacker_stats = calculate_actual_stats(
            command.attacker.stat_profile,
            level=command.attacker.level,
        )
        defender_stats = calculate_actual_stats(
            command.defender.stat_profile,
            level=command.defender.level,
        )

        attacker = BattlePokemon(
            name=command.attacker.name,
            level=command.attacker.level,
            types=command.attacker.types,
            stats=attacker_stats,
        )
        defender = BattlePokemon(
            name=command.defender.name,
            level=command.defender.level,
            types=command.defender.types,
            stats=defender_stats,
        )
        move = BattleMove(
            name=command.move.name,
            type=command.move.type,
            category=command.move.category,
            power=command.move.power,
        )

        damage = calculate_damage_rolls(
            DamageContextBuilder.for_move(
                attacker=attacker,
                defender=defender,
                move=move,
            ).build()
        )
        ko_chance = estimate_ko_chance(
            rolls=damage.rolls,
            defender_hp=defender.stats.hp,
        )

        return CalculateMoveDamageResult(
            attacker_stats=attacker_stats,
            defender_stats=defender_stats,
            damage=damage,
            ko_chance=ko_chance,
        )


def calculate_move_damage(
    command: CalculateMoveDamageCommand,
) -> CalculateMoveDamageResult:
    """函数式便捷入口：创建 CalculateMoveDamageUseCase 并执行 command。"""
    return CalculateMoveDamageUseCase().execute(command)


__all__ = [
    "CalculateMoveDamageCommand",
    "CalculateMoveDamageResult",
    "CalculateMoveDamageUseCase",
    "MoveBattleSnapshot",
    "PokemonBattleSnapshot",
    "calculate_move_damage",
]
