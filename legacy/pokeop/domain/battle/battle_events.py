from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
)


class InvalidBattleEventError(ValueError):
    """表示结构化战斗事件违反稳定领域合同。"""


class BattleEventKind(str, Enum):
    """标识完整回合中可供战报投影消费的稳定业务事件类别。"""

    TURN_STARTED = "turn-started"
    MOVE_SELECTED = "move-selected"
    ACTION_ORDERED = "action-ordered"
    MOVE_USED = "move-used"
    ACTION_BLOCKED = "action-blocked"
    HIT = "hit"
    MISS = "miss"
    DAMAGE = "damage"
    HP_CHANGED = "hp-changed"
    PP_CHANGED = "pp-changed"
    ABILITY_TRIGGERED = "ability-triggered"
    ITEM_TRIGGERED = "item-triggered"
    STATUS_APPLIED = "status-applied"
    STATUS_PREVENTED = "status-prevented"
    FAINTED = "fainted"
    TURN_ENDED = "turn-ended"


@dataclass(frozen=True, slots=True, kw_only=True)
class BattleEvent(TransitionEvent):
    """记录一条不可变、无文案的战斗业务事件。

    ``BattleEvent`` 复用 ``TransitionEventSummary`` 的路径组合与替代路径归并能力，
    但通过独立 ``kind`` 和显式字段表达业务语义。domain 只记录事实，不生成中文、
    英文或 Pokémon Showdown 风格文本；application/API/frontend presenter 可以据此投影。

    Args:
        kind: 事件的稳定类别。
        turn_number: 事件所属回合号，必须为正整数。
        actor: 发起行动、触发机制或进入状态的一方；事件没有明确主体时为 None。
        target: 行动或状态变化的目标侧；无目标事件为 None。
        move_id: 关联普通招式时的正整数 ID；挣扎、回合边界等事件为 None。
        source_identifier: 触发事件的稳定机制标识，例如 ``fake_out``、
            ``ability:multiscale`` 或 ``flinch``；无额外来源时为 None。
        value: 事件的整数值。伤害为实际扣除 HP，行动顺序为从 1 开始的序号，
            HP/PP 变化默认保存 ``after_value - before_value``。
        before_value: HP、PP 等数值变化前的值；与 ``after_value`` 必须同时出现。
        after_value: HP、PP 等数值变化后的值；与 ``before_value`` 必须同时出现。
    """

    kind: BattleEventKind
    turn_number: int
    actor: BattleSide | None = None
    target: BattleSide | None = None
    move_id: int | None = None
    source_identifier: str | None = None
    value: int | None = None
    before_value: int | None = None
    after_value: int | None = None
    event_type: TransitionEventType = field(
        default=TransitionEventType.CUSTOM,
        init=False,
        repr=False,
    )
    event_id: str = field(default="", init=False, repr=False)
    outcome_id: str = field(default="", init=False, repr=False)
    numeric_value: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """校验显式字段并生成兼容随机事件路径合同的稳定标识。

        Raises:
            InvalidBattleEventError: 类别、回合、侧别、招式 ID、来源或数值字段非法时抛出。
        """
        if not isinstance(self.kind, BattleEventKind):
            raise InvalidBattleEventError("kind must be a BattleEventKind")
        if isinstance(self.turn_number, bool) or self.turn_number <= 0:
            raise InvalidBattleEventError("turn_number must be greater than 0")
        for field_name, side in (("actor", self.actor), ("target", self.target)):
            if side is not None and not isinstance(side, BattleSide):
                raise InvalidBattleEventError(
                    f"{field_name} must be a BattleSide or None"
                )
        if self.move_id is not None and (
            isinstance(self.move_id, bool) or self.move_id <= 0
        ):
            raise InvalidBattleEventError("move_id must be greater than 0 or None")
        if self.source_identifier is not None and not self.source_identifier.strip():
            raise InvalidBattleEventError("source_identifier cannot be blank")

        for field_name, number in (
            ("value", self.value),
            ("before_value", self.before_value),
            ("after_value", self.after_value),
        ):
            if number is not None and (
                isinstance(number, bool) or not isinstance(number, int)
            ):
                raise InvalidBattleEventError(
                    f"{field_name} must be an integer or None"
                )
        if (self.before_value is None) != (self.after_value is None):
            raise InvalidBattleEventError(
                "before_value and after_value must be provided together"
            )

        resolved_value = self.value
        if (
            resolved_value is None
            and self.before_value is not None
            and self.after_value is not None
        ):
            resolved_value = self.after_value - self.before_value
            object.__setattr__(self, "value", resolved_value)

        actor = self.actor.value if self.actor is not None else "none"
        target = self.target.value if self.target is not None else "none"
        move_id = str(self.move_id) if self.move_id is not None else "none"
        source = self.source_identifier or "none"
        before = str(self.before_value) if self.before_value is not None else "none"
        after = str(self.after_value) if self.after_value is not None else "none"
        value = str(resolved_value) if resolved_value is not None else "none"
        object.__setattr__(
            self,
            "event_id",
            (
                f"turn-{self.turn_number}:{self.kind.value}:{actor}:{target}:"
                f"{move_id}:{source}:{before}:{after}:{value}"
            ),
        )
        object.__setattr__(self, "outcome_id", self.kind.value)
        object.__setattr__(self, "numeric_value", resolved_value)

    @property
    def delta(self) -> int | None:
        """返回 before/after 可推导的数值差；非数值变化事件返回 None。"""
        if self.before_value is None or self.after_value is None:
            return None
        return self.after_value - self.before_value


def event_summary(events: Iterable[BattleEvent]) -> TransitionEventSummary:
    """把按发生顺序提供的业务事件包装成一条不可变事件路径。

    Args:
        events: 同一确定执行阶段内按先后顺序排列的结构化事件。

    Returns:
        只包含该路径的 ``TransitionEventSummary``；空输入返回确定性空路径摘要。
    """
    materialized = tuple(events)
    if not materialized:
        return TransitionEventSummary.empty()
    return TransitionEventSummary((materialized,))


def append_battle_events(
    summary: TransitionEventSummary,
    events: Iterable[BattleEvent],
) -> TransitionEventSummary:
    """把业务事件追加到每条既有替代路径末尾。

    Args:
        summary: 已经包含父阶段随机事件和业务事件的路径摘要。
        events: 当前确定阶段新产生、按发生顺序排列的业务事件。

    Returns:
        保留全部替代路径并追加新事件后的摘要；空事件集合原样返回输入摘要。
    """
    materialized = tuple(events)
    if not materialized:
        return summary
    return summary.concatenate(event_summary(materialized))


def prepend_battle_events(
    summary: TransitionEventSummary,
    events: Iterable[BattleEvent],
) -> TransitionEventSummary:
    """把业务事件插入每条既有替代路径前端。

    Args:
        summary: 当前阶段已经生成的随机或业务事件路径。
        events: 必须先于摘要内事件展示的确定业务事件。

    Returns:
        新事件在前、原摘要路径在后的笛卡尔积结果；空事件集合原样返回输入摘要。
    """
    materialized = tuple(events)
    if not materialized:
        return summary
    return event_summary(materialized).concatenate(summary)


def battle_event_paths(
    summary: TransitionEventSummary,
) -> tuple[tuple[BattleEvent, ...], ...]:
    """从混合事件摘要中按路径筛出结构化战斗事件。

    Args:
        summary: 可能同时包含命中、伤害档等随机事件和 ``BattleEvent`` 的摘要。

    Returns:
        与原替代路径一一对应的业务事件元组；某条路径没有业务事件时返回空元组。
    """
    return tuple(
        tuple(event for event in path if isinstance(event, BattleEvent))
        for path in summary.paths
    )


__all__ = [
    "BattleEvent",
    "BattleEventKind",
    "InvalidBattleEventError",
    "append_battle_events",
    "battle_event_paths",
    "event_summary",
    "prepend_battle_events",
]
