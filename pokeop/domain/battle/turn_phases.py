from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TurnPhase(str, Enum):
    """表示完整 1v1 回合中不可由机制插件重排的稳定阶段。"""

    TURN_START = "turn-start"
    ACTION_SELECTION = "action-selection"
    ACTION_ORDER = "action-order"
    BEFORE_MOVE = "before-move"
    ACCURACY_CHECK = "accuracy-check"
    BEFORE_DAMAGE = "before-damage"
    DAMAGE = "damage"
    AFTER_DAMAGE = "after-damage"
    AFTER_MOVE = "after-move"
    FAINT_CHECK = "faint-check"
    TURN_END = "turn-end"


STABLE_TURN_PHASES: tuple[TurnPhase, ...] = (
    TurnPhase.TURN_START,
    TurnPhase.ACTION_SELECTION,
    TurnPhase.ACTION_ORDER,
    TurnPhase.BEFORE_MOVE,
    TurnPhase.ACCURACY_CHECK,
    TurnPhase.BEFORE_DAMAGE,
    TurnPhase.DAMAGE,
    TurnPhase.AFTER_DAMAGE,
    TurnPhase.AFTER_MOVE,
    TurnPhase.FAINT_CHECK,
    TurnPhase.TURN_END,
)


class InvalidTurnPhasePolicy(ValueError):
    """表示首版回合管线的阶段顺序被遗漏、重复或重排。"""


@dataclass(frozen=True, slots=True)
class TurnPhasePolicy:
    """保存规则集选择的稳定回合阶段顺序。

    Args:
        phases: 完整回合的模板顺序。首版只接受 ``STABLE_TURN_PHASES``，具体机制
            只能在对应阶段的窄协议中扩展，不能移动整个回合骨架。
    """

    phases: tuple[TurnPhase, ...] = STABLE_TURN_PHASES

    def __post_init__(self) -> None:
        """拒绝任何缺失、重复或重新排序的首版阶段策略。

        Raises:
            InvalidTurnPhasePolicy: ``phases`` 不等于稳定完整顺序时抛出。
        """
        if self.phases != STABLE_TURN_PHASES:
            raise InvalidTurnPhasePolicy(
                "the first turn resolver requires the stable complete phase order"
            )


DEFAULT_TURN_PHASE_POLICY = TurnPhasePolicy()


__all__ = [
    "DEFAULT_TURN_PHASE_POLICY",
    "InvalidTurnPhasePolicy",
    "STABLE_TURN_PHASES",
    "TurnPhase",
    "TurnPhasePolicy",
]
