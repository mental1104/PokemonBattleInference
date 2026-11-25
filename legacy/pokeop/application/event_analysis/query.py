"""定义随机战斗事件的类型化过滤和查询合同。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventType


class BattleEventAnalysisError(ValueError):
    """表示事件分析请求、输入图或精确概率结果违反稳定合同。"""


class EventSideRole(str, Enum):
    """标识过滤侧别时匹配事件主体、目标或任一位置。"""

    ANY = "any"
    ACTOR = "actor"
    TARGET = "target"


class EventOccurrenceMode(str, Enum):
    """标识回合范围约束作用于任意发生还是首次发生。"""

    ANY = "any"
    FIRST = "first"


class ConditionalProbabilityStatus(str, Enum):
    """标识条件概率已定义或因条件事件概率为零而不可定义。"""

    DEFINED = "defined"
    UNDEFINED_ZERO_CONDITION = "undefined-zero-condition"


@dataclass(frozen=True, slots=True)
class EventTurnRange:
    """限制事件首次或任意发生所处的闭区间回合。

    Args:
        start_turn: 可选最小回合号；省略表示不限制下界。
        end_turn: 可选最大回合号；省略表示不限制上界。
    """

    start_turn: int | None = None
    end_turn: int | None = None

    def __post_init__(self) -> None:
        """校验回合边界为正整数且下界不大于上界。"""
        for field_name, value in (
            ("start_turn", self.start_turn),
            ("end_turn", self.end_turn),
        ):
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise BattleEventAnalysisError(
                    f"{field_name} must be greater than 0 or None"
                )
        if (
            self.start_turn is not None
            and self.end_turn is not None
            and self.start_turn > self.end_turn
        ):
            raise BattleEventAnalysisError(
                "event turn range start cannot exceed end"
            )

    def contains(self, turn_number: int) -> bool:
        """返回一个正回合号是否位于当前闭区间内。

        Args:
            turn_number: 待判断的正回合号。

        Returns:
            回合号满足已配置上下界时返回 True。
        """
        if self.start_turn is not None and turn_number < self.start_turn:
            return False
        if self.end_turn is not None and turn_number > self.end_turn:
            return False
        return True


@dataclass(frozen=True, slots=True)
class BattleEventPredicate:
    """使用结构化事件字段过滤随机或战斗业务事件。

    所有非空字段使用 AND 语义。侧别、招式和机制来源只适用于 ``BattleEvent``；
    不会解析 trace、中文或英文展示文案。

    Args:
        battle_event_kinds: 允许的业务事件类别；空元组表示不限制。
        transition_event_types: 允许的底层随机事件类别；空元组表示不限制。
        side: 需要匹配的观察侧；省略表示不限制。
        side_role: ``side`` 应匹配 actor、target 或任一位置。
        move_id: 关联招式 ID；省略表示不限制。
        effect_identifier: 特性、道具、状态或效果的稳定 ``source_identifier``。
        event_id: 底层随机事件来源 ID。
        outcome_id: 底层随机事件结果 ID。
    """

    battle_event_kinds: tuple[BattleEventKind, ...] = ()
    transition_event_types: tuple[TransitionEventType, ...] = ()
    side: BattleSide | None = None
    side_role: EventSideRole = EventSideRole.ANY
    move_id: int | None = None
    effect_identifier: str | None = None
    event_id: str | None = None
    outcome_id: str | None = None

    def __post_init__(self) -> None:
        """校验枚举集合、侧别、招式和稳定标识。"""
        if any(
            not isinstance(kind, BattleEventKind)
            for kind in self.battle_event_kinds
        ):
            raise BattleEventAnalysisError(
                "battle_event_kinds must contain BattleEventKind values"
            )
        if len(self.battle_event_kinds) != len(set(self.battle_event_kinds)):
            raise BattleEventAnalysisError(
                "battle_event_kinds cannot contain duplicates"
            )
        if any(
            not isinstance(event_type, TransitionEventType)
            for event_type in self.transition_event_types
        ):
            raise BattleEventAnalysisError(
                "transition_event_types must contain TransitionEventType values"
            )
        if len(self.transition_event_types) != len(
            set(self.transition_event_types)
        ):
            raise BattleEventAnalysisError(
                "transition_event_types cannot contain duplicates"
            )
        if self.side is not None and not isinstance(self.side, BattleSide):
            raise BattleEventAnalysisError("side must be a BattleSide or None")
        if not isinstance(self.side_role, EventSideRole):
            raise BattleEventAnalysisError("side_role must be an EventSideRole")
        if self.move_id is not None and (
            isinstance(self.move_id, bool) or self.move_id <= 0
        ):
            raise BattleEventAnalysisError("move_id must be greater than 0 or None")
        for field_name, value in (
            ("effect_identifier", self.effect_identifier),
            ("event_id", self.event_id),
            ("outcome_id", self.outcome_id),
        ):
            if value is not None and (not value.strip() or value != value.strip()):
                raise BattleEventAnalysisError(
                    f"{field_name} must be normalized non-empty text or None"
                )

    def matches(self, event: TransitionEvent) -> bool:
        """返回事件是否满足全部结构化字段过滤。

        Args:
            event: 图边事件路径中的类型化随机或业务事件。

        Returns:
            所有已配置字段均匹配时返回 True。
        """
        if not isinstance(event, TransitionEvent):
            return False
        if (
            self.transition_event_types
            and event.event_type not in self.transition_event_types
        ):
            return False
        if self.event_id is not None and event.event_id != self.event_id:
            return False
        if self.outcome_id is not None and event.outcome_id != self.outcome_id:
            return False

        needs_battle_event = bool(
            self.battle_event_kinds
            or self.side is not None
            or self.move_id is not None
            or self.effect_identifier is not None
        )
        if needs_battle_event and not isinstance(event, BattleEvent):
            return False
        if not isinstance(event, BattleEvent):
            return True
        if self.battle_event_kinds and event.kind not in self.battle_event_kinds:
            return False
        if self.move_id is not None and event.move_id != self.move_id:
            return False
        if (
            self.effect_identifier is not None
            and event.source_identifier != self.effect_identifier
        ):
            return False
        if self.side is None:
            return True
        if self.side_role is EventSideRole.ACTOR:
            return event.actor is self.side
        if self.side_role is EventSideRole.TARGET:
            return event.target is self.side
        return event.actor is self.side or event.target is self.side


@dataclass(frozen=True, slots=True)
class BattleEventQuery:
    """定义事件 E 的发生次数、回合范围与分布输出边界。

    ``min_occurrences`` 和 ``max_occurrences`` 总是作用于整条随机历史中的结构化匹配
    次数。``turn_range`` 在 ``ANY`` 模式要求至少一次匹配落入区间；在 ``FIRST`` 模式
    要求第一次匹配落入区间。

    Args:
        predicate: 不依赖展示文本的事件字段过滤器。
        occurrence_mode: 回合范围匹配任意发生或首次发生。
        turn_range: 可选闭区间回合过滤。
        min_occurrences: 事件 E 要求的最少发生次数。
        max_occurrences: 事件 E 允许的最大发生次数；None 表示不限制。
        distribution_count_limit: 发生次数分布单独列出的最大精确次数。
        distribution_turn_limit: 首次发生回合分布单独列出的最大精确回合。
        max_key_event_summaries: 返回的唯一关键事件摘要上限。
    """

    predicate: BattleEventPredicate
    occurrence_mode: EventOccurrenceMode = EventOccurrenceMode.ANY
    turn_range: EventTurnRange | None = None
    min_occurrences: int = 1
    max_occurrences: int | None = None
    distribution_count_limit: int = 8
    distribution_turn_limit: int = 16
    max_key_event_summaries: int = 32

    def __post_init__(self) -> None:
        """校验查询枚举、次数边界和有限分布预算。"""
        if not isinstance(self.predicate, BattleEventPredicate):
            raise BattleEventAnalysisError(
                "predicate must be a BattleEventPredicate"
            )
        if not isinstance(self.occurrence_mode, EventOccurrenceMode):
            raise BattleEventAnalysisError(
                "occurrence_mode must be an EventOccurrenceMode"
            )
        if self.turn_range is not None and not isinstance(
            self.turn_range, EventTurnRange
        ):
            raise BattleEventAnalysisError("turn_range must be EventTurnRange or None")
        if isinstance(self.min_occurrences, bool) or self.min_occurrences < 0:
            raise BattleEventAnalysisError(
                "min_occurrences must be a non-negative integer"
            )
        if self.max_occurrences is not None and (
            isinstance(self.max_occurrences, bool) or self.max_occurrences < 0
        ):
            raise BattleEventAnalysisError(
                "max_occurrences must be a non-negative integer or None"
            )
        if (
            self.max_occurrences is not None
            and self.min_occurrences > self.max_occurrences
        ):
            raise BattleEventAnalysisError(
                "min_occurrences cannot exceed max_occurrences"
            )
        for field_name, value in (
            ("distribution_count_limit", self.distribution_count_limit),
            ("distribution_turn_limit", self.distribution_turn_limit),
            ("max_key_event_summaries", self.max_key_event_summaries),
        ):
            if isinstance(value, bool) or value <= 0:
                raise BattleEventAnalysisError(
                    f"{field_name} must be greater than 0"
                )


__all__ = [
    "BattleEventAnalysisError",
    "BattleEventPredicate",
    "BattleEventQuery",
    "ConditionalProbabilityStatus",
    "EventOccurrenceMode",
    "EventSideRole",
    "EventTurnRange",
]
