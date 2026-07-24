"""保存联合行动投影所需的精确策略与回合随机概率元数据。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
)


JOINT_ACTION_PROBABILITY_EVENT_ID = "application.joint-action-probability"


class JointActionProbabilityMetadataError(ValueError):
    """表示联合行动概率元数据缺失、重复或格式非法。"""


@dataclass(frozen=True, slots=True)
class JointActionProbabilityMetadata:
    """保存联合行动选择概率和该行动下的条件随机结果概率。

    Args:
        selection_probability: 双方策略独立选中该联合行动的精确概率。
        random_probability: 固定该联合行动后到达当前后继状态的条件概率。
    """

    selection_probability: Fraction
    random_probability: Fraction

    def __post_init__(self) -> None:
        """拒绝非精确概率以及不在 ``(0, 1]`` 内的概率。"""
        for field_name, probability in (
            ("selection_probability", self.selection_probability),
            ("random_probability", self.random_probability),
        ):
            if not isinstance(probability, Fraction):
                raise JointActionProbabilityMetadataError(
                    f"{field_name} must use fractions.Fraction"
                )
            if not 0 < probability <= 1:
                raise JointActionProbabilityMetadataError(
                    f"{field_name} must be in the interval (0, 1]"
                )


def with_joint_action_probability(
    summary: TransitionEventSummary,
    *,
    selection_probability: Fraction,
    random_probability: Fraction,
) -> TransitionEventSummary:
    """为回合 resolver 的每条事件路径追加精确概率元数据。

    Args:
        summary: 固定联合行动下、已经按后继状态归并的事件路径摘要。
        selection_probability: 双方策略选中当前联合行动的精确概率。
        random_probability: 固定联合行动后到达该后继状态的条件概率。

    Returns:
        保留原事件顺序并在路径末尾追加内部元数据事件的新摘要。
    """
    metadata = JointActionProbabilityMetadata(
        selection_probability=selection_probability,
        random_probability=random_probability,
    )
    event = TransitionEvent(
        event_type=TransitionEventType.CUSTOM,
        event_id=JOINT_ACTION_PROBABILITY_EVENT_ID,
        outcome_id=(
            f"{metadata.selection_probability.numerator}/"
            f"{metadata.selection_probability.denominator}|"
            f"{metadata.random_probability.numerator}/"
            f"{metadata.random_probability.denominator}"
        ),
    )
    return summary.concatenate(TransitionEventSummary.single(event))


def is_joint_action_probability_event(event: TransitionEvent) -> bool:
    """判断一条随机事件是否为 application 内部联合行动概率元数据。"""
    return (
        event.event_type is TransitionEventType.CUSTOM
        and event.event_id == JOINT_ACTION_PROBABILITY_EVENT_ID
    )


def joint_action_probability_from_path(
    path: tuple[TransitionEvent, ...],
) -> JointActionProbabilityMetadata | None:
    """从一条事件路径读取唯一的联合行动概率元数据。

    Args:
        path: 状态图边保留的一条完整事件替代路径。

    Returns:
        找到时返回精确概率；旧图或合成测试没有元数据时返回 None。

    Raises:
        JointActionProbabilityMetadataError: 同一路径存在重复或非法元数据时抛出。
    """
    metadata_events = tuple(
        event for event in path if is_joint_action_probability_event(event)
    )
    if not metadata_events:
        return None
    if len(metadata_events) != 1:
        raise JointActionProbabilityMetadataError(
            "event path must contain at most one joint action probability event"
        )
    payload = metadata_events[0].outcome_id
    try:
        selection_text, random_text = payload.split("|", maxsplit=1)
        selection_numerator, selection_denominator = selection_text.split(
            "/", maxsplit=1
        )
        random_numerator, random_denominator = random_text.split("/", maxsplit=1)
        return JointActionProbabilityMetadata(
            selection_probability=Fraction(
                int(selection_numerator), int(selection_denominator)
            ),
            random_probability=Fraction(int(random_numerator), int(random_denominator)),
        )
    except (ValueError, ZeroDivisionError) as error:
        raise JointActionProbabilityMetadataError(
            f"invalid joint action probability payload: {payload!r}"
        ) from error


__all__ = [
    "JOINT_ACTION_PROBABILITY_EVENT_ID",
    "JointActionProbabilityMetadata",
    "JointActionProbabilityMetadataError",
    "is_joint_action_probability_event",
    "joint_action_probability_from_path",
    "with_joint_action_probability",
]
