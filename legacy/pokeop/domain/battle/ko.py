from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TurnEffect:
    """
    预留的回合结束效果标记。

    本阶段不会处理文柚果、剩饭、中毒、灼伤等回合效果；
    先保留这个对象，方便后续在 KO 估算管线中扩展。
    """

    key: str


@dataclass(frozen=True)
class KOChanceResult:
    """
    表示基于当前伤害档位估算的一击和二击击杀概率。

    ohko_chance 基于单次伤害档位计算，two_hit_ko_chance 基于两次伤害组合计算；
    guaranteed_* 字段用于直接表达是否稳定一击或稳定二击。
    """

    ohko_chance: float
    two_hit_ko_chance: float
    guaranteed_ohko: bool
    guaranteed_2hko: bool


def estimate_ko_chance(
    *,
    rolls: Sequence[int],
    defender_hp: int,
    turn_effects: Sequence[TurnEffect] = (),
) -> KOChanceResult:
    """
    根据伤害档位估算一击和二击击杀概率。

    一击概率统计单次 damage >= HP 的档位比例；
    二击概率枚举 damage1 + damage2 >= HP 的所有组合。
    turn_effects 是后续回血、扣血和状态结算的扩展口，本阶段传入会明确报错。
    """
    if not rolls:
        raise ValueError("rolls must not be empty")
    if defender_hp <= 0:
        raise ValueError("defender_hp must be greater than 0")
    if turn_effects:
        raise NotImplementedError("turn effects are reserved for a later phase")

    roll_count = len(rolls)
    ohko_hits = sum(1 for damage in rolls if damage >= defender_hp)
    two_hit_kos = sum(
        1
        for first in rolls
        for second in rolls
        if first + second >= defender_hp
    )

    return KOChanceResult(
        ohko_chance=ohko_hits / roll_count,
        two_hit_ko_chance=two_hit_kos / (roll_count * roll_count),
        guaranteed_ohko=min(rolls) >= defender_hp,
        guaranteed_2hko=min(rolls) * 2 >= defender_hp,
    )


__all__ = ["KOChanceResult", "TurnEffect", "estimate_ko_chance"]
