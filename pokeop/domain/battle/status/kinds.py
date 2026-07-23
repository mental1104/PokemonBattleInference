from __future__ import annotations

from enum import Enum, unique


@unique
class NonVolatileStatusKind(str, Enum):
    """表示交换后仍会保留的主要异常状态类型。"""

    SLEEP = "sleep"
    PARALYSIS = "paralysis"
    BURN = "burn"
    FREEZE = "freeze"
    POISON = "poison"
    BAD_POISON = "bad_poison"


@unique
class VolatileStatusKind(str, Enum):
    """表示会随交换或回合阶段清理的临时状态类型。"""

    CONFUSION = "confusion"
    INFATUATION = "infatuation"
    FLINCH = "flinch"


__all__ = ["NonVolatileStatusKind", "VolatileStatusKind"]
