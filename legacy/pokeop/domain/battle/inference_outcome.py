from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BattleSide(str, Enum):
    """1v1 推演中的稳定双方标识。"""

    ATTACKER = "attacker"
    DEFENDER = "defender"


class TerminalOutcome(str, Enum):
    """状态图叶节点或吸收状态的胜负语义。"""

    ATTACKER_WIN = "attacker-win"
    DEFENDER_WIN = "defender-win"
    DRAW = "draw"


class TerminationReason(str, Enum):
    """一次推演分支停止扩展的原因。"""

    KNOCKOUT = "knockout"
    MUTUAL_KNOCKOUT = "mutual-knockout"
    MAX_TURNS = "max-turns"
    NO_PP = "no-pp"
    NO_LEGAL_ACTION = "no-legal-action"
    REPETITION = "repetition"
    CYCLE_GUARD = "cycle-guard"


@dataclass(frozen=True, slots=True)
class TerminalBattleOutcome:
    """一个终局及其停止原因，不包含展示文案或状态图对象。"""

    outcome: TerminalOutcome
    reason: TerminationReason
    turns: int

    def __post_init__(self) -> None:
        if self.turns < 0:
            raise ValueError("terminal outcome turns cannot be negative")
        if self.reason in {
            TerminationReason.MAX_TURNS,
            TerminationReason.REPETITION,
            TerminationReason.CYCLE_GUARD,
            TerminationReason.MUTUAL_KNOCKOUT,
        } and self.outcome is not TerminalOutcome.DRAW:
            raise ValueError(f"{self.reason.value} must produce a draw outcome")
