from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import TYPE_CHECKING, Generic, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from pokeop.domain.battle.damage import DamageRollResult


StateT = TypeVar("StateT", bound="StateKeyed")
LeftStateT = TypeVar("LeftStateT", bound="StateKeyed")
RightStateT = TypeVar("RightStateT", bound="StateKeyed")
ResultStateT = TypeVar("ResultStateT", bound="StateKeyed")


class TransitionError(ValueError):
    """带权战斗状态转移合同被违反时的基础异常。"""


class InvalidTransitionProbabilityError(TransitionError):
    """表示单条转移没有使用合法的精确概率。"""


class EmptyTransitionSetError(TransitionError):
    """表示完整随机事件没有产生任何后继分支。"""


class UnnormalizedTransitionSetError(TransitionError):
    """表示一组完整随机分支的概率总和不严格等于 1。"""


class InvalidStateKeyError(TransitionError):
    """表示后继状态没有提供稳定且可哈希的状态键。"""


class InvalidTransitionEventError(TransitionError):
    """表示事件摘要缺少稳定标识或包含非法数值。"""


@runtime_checkable
class StateKeyed(Protocol):
    """可参与状态图归并的不可变状态协议。

    具体 ``BattleState`` 只需暴露稳定且可哈希的 ``state_key``。概率工具不会读取
    HP、PP、回合数等业务字段，也不会依据对象身份判断两个状态是否等价。
    """

    @property
    def state_key(self) -> Hashable:
        """返回只包含未来战斗语义的稳定状态键。"""


class TransitionEventType(str, Enum):
    """标识随机状态转移中可解释事件的稳定类别。"""

    HIT_CHECK = "hit_check"
    DAMAGE_ROLL = "damage_roll"
    SPEED_TIE = "speed_tie"
    SECONDARY_EFFECT = "secondary_effect"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class TransitionEvent:
    """记录一条随机分支中的类型化事件摘要。

    ``event_id`` 标识随机事件来源，例如某次命中判定或伤害档位；``outcome_id``
    标识该来源下的稳定分支结果。``numeric_value`` 只保存解释该结果所需的整数，
    例如实际伤害，不引用完整战斗对象。

    Args:
        event_type: 随机事件的稳定类型。
        event_id: 随机事件来源的稳定标识。
        outcome_id: 当前分支结果的稳定标识。
        numeric_value: 解释结果所需的可选整数值。
    """

    event_type: TransitionEventType
    event_id: str
    outcome_id: str
    numeric_value: int | None = None

    def __post_init__(self) -> None:
        """校验事件来源和结果都使用非空稳定标识。"""
        if not self.event_id.strip():
            raise InvalidTransitionEventError("transition event_id cannot be empty")
        if not self.outcome_id.strip():
            raise InvalidTransitionEventError("transition outcome_id cannot be empty")


@dataclass(frozen=True, slots=True)
class TransitionEventSummary:
    """保存一个后继状态对应的一条或多条随机事件路径。

    等价状态归并后可能由多个随机结果到达同一节点。``paths`` 保留每条轻量事件
    历史，``path_probabilities`` 保存这些路径在当前 ``WeightedTransition`` 条件下的
    精确概率。调用方因此可以在不拆散基础 ``StateKey`` 的前提下继续计算事件条件概率。

    Args:
        paths: 到达同一后继状态的不可变事件路径。
        path_probabilities: 与 ``paths`` 一一对应且严格归一化的条件概率。省略时单路径
            默认为 1；多路径为兼容旧调用按等概率解释。
    """

    paths: tuple[tuple[TransitionEvent, ...], ...] = ((),)
    path_probabilities: tuple[Fraction, ...] | None = None

    def __post_init__(self) -> None:
        """校验路径和条件概率，并合并完全相同的重复路径。

        Raises:
            InvalidTransitionEventError: 路径、概率数量、精度或归一化语义非法。
        """
        if not self.paths:
            raise InvalidTransitionEventError(
                "transition event summary must contain at least one path"
            )

        materialized_paths = tuple(self.paths)
        for path in materialized_paths:
            if not isinstance(path, tuple):
                raise InvalidTransitionEventError(
                    "transition event paths must use immutable tuples"
                )
            if any(not isinstance(event, TransitionEvent) for event in path):
                raise InvalidTransitionEventError(
                    "transition event paths can only contain TransitionEvent values"
                )

        probabilities = self.path_probabilities
        if probabilities is None:
            probability = Fraction(1, len(materialized_paths))
            materialized_probabilities = tuple(
                probability for _ in materialized_paths
            )
        else:
            materialized_probabilities = tuple(probabilities)
            if len(materialized_probabilities) != len(materialized_paths):
                raise InvalidTransitionEventError(
                    "transition path probabilities must align with paths"
                )
            if any(
                not isinstance(probability, Fraction)
                or probability <= 0
                or probability > 1
                for probability in materialized_probabilities
            ):
                raise InvalidTransitionEventError(
                    "transition path probabilities must use positive Fractions"
                )
            if sum(materialized_probabilities, start=Fraction(0)) != Fraction(1):
                raise InvalidTransitionEventError(
                    "transition path probabilities must sum exactly to 1"
                )

        unique_paths: list[tuple[TransitionEvent, ...]] = []
        probability_by_path: dict[tuple[TransitionEvent, ...], Fraction] = {}
        for path, probability in zip(
            materialized_paths,
            materialized_probabilities,
            strict=True,
        ):
            if path not in probability_by_path:
                unique_paths.append(path)
                probability_by_path[path] = Fraction(0)
            probability_by_path[path] += probability

        normalized_probabilities = tuple(
            probability_by_path[path] for path in unique_paths
        )
        if sum(normalized_probabilities, start=Fraction(0)) != Fraction(1):
            raise InvalidTransitionEventError(
                "deduplicated transition path probabilities must sum exactly to 1"
            )
        object.__setattr__(self, "paths", tuple(unique_paths))
        object.__setattr__(self, "path_probabilities", normalized_probabilities)

    @classmethod
    def empty(cls) -> TransitionEventSummary:
        """创建不附带随机事件的确定性路径摘要。"""
        return cls(((),), (Fraction(1),))

    @classmethod
    def single(cls, event: TransitionEvent) -> TransitionEventSummary:
        """为单个类型化事件创建一条确定条件路径。

        Args:
            event: 当前随机分支对应的事件结果。

        Returns:
            只包含该事件且条件概率为 1 的不可变摘要。
        """
        return cls(((event,),), (Fraction(1),))

    @property
    def weighted_paths(
        self,
    ) -> tuple[tuple[Fraction, tuple[TransitionEvent, ...]], ...]:
        """返回按路径顺序排列的精确条件概率与事件路径。

        Returns:
            每项依次包含条件概率和对应事件路径；全部概率严格相加为 1。
        """
        probabilities = self.path_probabilities
        if probabilities is None:  # pragma: no cover - ``__post_init__`` 已规范化。
            raise InvalidTransitionEventError(
                "transition path probabilities were not normalized"
            )
        return tuple(zip(probabilities, self.paths, strict=True))

    def concatenate(
        self,
        following: TransitionEventSummary,
    ) -> TransitionEventSummary:
        """按执行顺序连接两组路径，并精确相乘条件概率。

        Args:
            following: 后续随机事件的路径摘要。

        Returns:
            当前路径与后续路径做笛卡尔积后的新摘要。
        """
        combined_paths: list[tuple[TransitionEvent, ...]] = []
        combined_probabilities: list[Fraction] = []
        for current_probability, current_path in self.weighted_paths:
            for following_probability, following_path in following.weighted_paths:
                combined_paths.append(current_path + following_path)
                combined_probabilities.append(
                    current_probability * following_probability
                )
        return TransitionEventSummary(
            tuple(combined_paths),
            tuple(combined_probabilities),
        )

    def merge_alternatives(
        self,
        other: TransitionEventSummary,
        *,
        self_probability: Fraction = Fraction(1, 2),
        other_probability: Fraction = Fraction(1, 2),
    ) -> TransitionEventSummary:
        """按两组父分支概率合并到达同一状态的替代事件路径。

        Args:
            other: 另一组等价后继状态的路径摘要。
            self_probability: 当前摘要所属父分支的绝对正概率或正权重。
            other_probability: 另一摘要所属父分支的绝对正概率或正权重。

        Returns:
            将父分支权重换算为条件概率并精确合并后的路径摘要。

        Raises:
            InvalidTransitionEventError: 父分支权重不是正 ``Fraction``。
        """
        for field_name, probability in (
            ("self_probability", self_probability),
            ("other_probability", other_probability),
        ):
            if not isinstance(probability, Fraction) or probability <= 0:
                raise InvalidTransitionEventError(
                    f"{field_name} must be a positive Fraction"
                )
        total = self_probability + other_probability
        paths: list[tuple[TransitionEvent, ...]] = []
        probabilities: list[Fraction] = []
        for probability, path in self.weighted_paths:
            paths.append(path)
            probabilities.append(self_probability / total * probability)
        for probability, path in other.weighted_paths:
            paths.append(path)
            probabilities.append(other_probability / total * probability)
        return TransitionEventSummary(tuple(paths), tuple(probabilities))


@dataclass(frozen=True, slots=True)
class WeightedTransition(Generic[StateT]):
    """表示一个由战斗随机事件产生的精确带权后继状态。

    该类型只表达命中、伤害档位、同速和追加效果等战斗随机概率，不表达玩家行动
    策略的选择权重。``state`` 必须提供稳定 ``state_key``，供图求解器按语义归并。

    Args:
        probability: 当前后继状态在完整随机分布中的精确概率。
        state: 不可变后继状态。
        event_summary: 当前后继状态内部替代事件路径及其条件概率。
        source_key: 可选稳定解释来源键。
    """

    probability: Fraction
    state: StateT
    event_summary: TransitionEventSummary = TransitionEventSummary.empty()
    source_key: str | None = None

    def __post_init__(self) -> None:
        """校验概率精度、取值范围、后继状态键和来源键。

        Raises:
            InvalidTransitionProbabilityError: 概率不是 ``Fraction`` 或不在 ``(0, 1]``。
            InvalidStateKeyError: 状态没有提供可哈希的稳定键。
            InvalidTransitionEventError: 事件摘要类型错误或 ``source_key`` 为空白。
        """
        if not isinstance(self.probability, Fraction):
            raise InvalidTransitionProbabilityError(
                "transition probability must use fractions.Fraction"
            )
        if not 0 < self.probability <= 1:
            raise InvalidTransitionProbabilityError(
                "transition probability must be in the interval (0, 1]"
            )
        try:
            state_key = self.state.state_key
            hash(state_key)
        except (AttributeError, TypeError) as exc:
            raise InvalidStateKeyError(
                "transition state must expose a hashable state_key"
            ) from exc
        if not isinstance(self.event_summary, TransitionEventSummary):
            raise InvalidTransitionEventError(
                "transition event_summary must be a TransitionEventSummary"
            )
        if self.source_key is not None and not self.source_key.strip():
            raise InvalidTransitionEventError(
                "transition source_key cannot be blank"
            )


@dataclass(slots=True)
class _TransitionAccumulator(Generic[StateT]):
    """在等价状态归并期间暂存概率和带条件权重的轻量事件摘要。"""

    state: StateT
    probability: Fraction
    event_summary: TransitionEventSummary
    source_key: str | None


def _materialize_transitions(
    transitions: Iterable[WeightedTransition[StateT]],
) -> tuple[WeightedTransition[StateT], ...]:
    """把单次可迭代输入冻结为元组，并拒绝空分支集合。

    Args:
        transitions: 一组代表完整或待归一化随机分支的转移。

    Returns:
        可重复遍历的不可变转移元组。

    Raises:
        EmptyTransitionSetError: 输入没有任何转移。
    """
    materialized = tuple(transitions)
    if not materialized:
        raise EmptyTransitionSetError("transition set cannot be empty")
    return materialized


def total_transition_probability(
    transitions: Iterable[WeightedTransition[StateT]],
) -> Fraction:
    """计算一组非空转移的精确概率总和。

    Args:
        transitions: 待统计的带权状态转移。

    Returns:
        使用 ``Fraction`` 表达的精确概率总和。

    Raises:
        EmptyTransitionSetError: 输入没有任何转移。
    """
    materialized = _materialize_transitions(transitions)
    return sum(
        (transition.probability for transition in materialized),
        start=Fraction(0),
    )


def validate_transition_distribution(
    transitions: Iterable[WeightedTransition[StateT]],
) -> tuple[WeightedTransition[StateT], ...]:
    """验证一组完整随机分支严格归一化为 1。

    Args:
        transitions: 同一随机事件或组合事件产生的完整分支集合。

    Returns:
        验证后的不可变转移元组，便于调用方继续复用。

    Raises:
        EmptyTransitionSetError: 输入没有任何分支。
        UnnormalizedTransitionSetError: 分支概率总和不严格等于 1。
    """
    materialized = _materialize_transitions(transitions)
    total = sum(
        (transition.probability for transition in materialized),
        start=Fraction(0),
    )
    if total != Fraction(1):
        raise UnnormalizedTransitionSetError(
            f"transition probabilities must sum exactly to 1, got {total}"
        )
    return materialized


def normalize_transition_weights(
    transitions: Iterable[WeightedTransition[StateT]],
) -> tuple[WeightedTransition[StateT], ...]:
    """把一组正的精确权重转换为总和为 1 的概率分布。

    Args:
        transitions: 每条权重均已通过 ``WeightedTransition`` 合法性校验的分支。

    Returns:
        保留状态、事件摘要和来源键，只重新缩放概率的新转移元组。

    Raises:
        EmptyTransitionSetError: 输入没有任何分支。
    """
    materialized = _materialize_transitions(transitions)
    total = sum(
        (transition.probability for transition in materialized),
        start=Fraction(0),
    )
    normalized = tuple(
        WeightedTransition(
            probability=transition.probability / total,
            state=transition.state,
            event_summary=transition.event_summary,
            source_key=transition.source_key,
        )
        for transition in materialized
    )
    return validate_transition_distribution(normalized)


def merge_equivalent_transitions(
    transitions: Iterable[WeightedTransition[StateT]],
) -> tuple[WeightedTransition[StateT], ...]:
    """按稳定 ``state_key`` 合并语义等价的后继状态。

    Args:
        transitions: 已经严格归一化的完整随机分支集合。

    Returns:
        按首次出现的状态键稳定排序、概率精确相加后的转移元组。事件路径条件概率
        会按各父分支绝对概率重新加权，不会把不等概率路径误当成等概率。

    Raises:
        EmptyTransitionSetError: 输入没有任何分支。
        UnnormalizedTransitionSetError: 输入或归并后的概率总和不为 1。
    """
    materialized = validate_transition_distribution(transitions)
    accumulators: dict[Hashable, _TransitionAccumulator[StateT]] = {}

    for transition in materialized:
        state_key = transition.state.state_key
        existing = accumulators.get(state_key)
        if existing is None:
            accumulators[state_key] = _TransitionAccumulator(
                state=transition.state,
                probability=transition.probability,
                event_summary=transition.event_summary,
                source_key=transition.source_key,
            )
            continue

        existing.event_summary = existing.event_summary.merge_alternatives(
            transition.event_summary,
            self_probability=existing.probability,
            other_probability=transition.probability,
        )
        existing.probability += transition.probability
        if existing.source_key != transition.source_key:
            # 多个来源到达同一状态时，详细来源仍保留在事件路径中；顶层单值键不再误导。
            existing.source_key = None

    merged = tuple(
        WeightedTransition(
            probability=accumulator.probability,
            state=accumulator.state,
            event_summary=accumulator.event_summary,
            source_key=accumulator.source_key,
        )
        for accumulator in accumulators.values()
    )
    return validate_transition_distribution(merged)


def combine_independent_transitions(
    left: Iterable[WeightedTransition[LeftStateT]],
    right: Iterable[WeightedTransition[RightStateT]],
    *,
    state_combiner: Callable[[LeftStateT, RightStateT], ResultStateT],
    source_key: str | None = None,
) -> tuple[WeightedTransition[ResultStateT], ...]:
    """对两个独立随机事件做笛卡尔积并合并等价后继状态。

    Args:
        left: 第一个完整且归一化的随机分布。
        right: 第二个完整且归一化的随机分布。
        state_combiner: 根据两个分支状态构造新的不可变后继状态；不得原地修改输入。
        source_key: 可选的组合来源键；省略时由事件路径承担解释责任。

    Returns:
        概率按乘法组合、事件路径及条件概率按执行顺序连接并按 ``state_key`` 归并的分布。
    """
    left_transitions = validate_transition_distribution(left)
    right_transitions = validate_transition_distribution(right)
    combined = tuple(
        WeightedTransition(
            probability=left_transition.probability
            * right_transition.probability,
            state=state_combiner(
                left_transition.state,
                right_transition.state,
            ),
            event_summary=left_transition.event_summary.concatenate(
                right_transition.event_summary
            ),
            source_key=source_key,
        )
        for left_transition in left_transitions
        for right_transition in right_transitions
    )
    return merge_equivalent_transitions(combined)


def branch_transitions(
    transitions: Iterable[WeightedTransition[StateT]],
    *,
    branch_factory: Callable[
        [StateT],
        Iterable[WeightedTransition[StateT]],
    ],
    source_key: str | None = None,
) -> tuple[WeightedTransition[StateT], ...]:
    """按每个父状态生成条件分支，并精确组合多级概率。

    Args:
        transitions: 当前层完整且归一化的状态分布。
        branch_factory: 为每个父状态返回一组完整且归一化的后继分支；不能返回空集合。
        source_key: 可选的组合来源键；省略时保留子分支来源键或父分支来源键。

    Returns:
        父子概率相乘、事件路径连接并按稳定状态键归并后的完整分布。

    Raises:
        EmptyTransitionSetError: 当前层或任一条件分支为空。
        UnnormalizedTransitionSetError: 当前层或任一条件分支未严格归一化。
    """
    parent_transitions = validate_transition_distribution(transitions)
    combined: list[WeightedTransition[StateT]] = []

    for parent in parent_transitions:
        children = validate_transition_distribution(branch_factory(parent.state))
        for child in children:
            combined.append(
                WeightedTransition(
                    probability=parent.probability * child.probability,
                    state=child.state,
                    event_summary=parent.event_summary.concatenate(
                        child.event_summary
                    ),
                    source_key=(
                        source_key
                        if source_key is not None
                        else child.source_key or parent.source_key
                    ),
                )
            )

    return merge_equivalent_transitions(combined)


def damage_rolls_to_transitions(
    *,
    state: StateT,
    damage_result: DamageRollResult,
    apply_damage: Callable[[StateT, int], StateT],
    event_id: str,
    source_key: str | None = None,
) -> tuple[WeightedTransition[StateT], ...]:
    """把 ``DamageRollResult`` 的等概率伤害档位转换为后继状态分布。

    Args:
        state: 伤害发生前的不可变战斗状态。
        damage_result: 已完成伤害链计算的结果；``rolls`` 中每个档位等概率出现。
        apply_damage: 接收旧状态和非负伤害，返回应用伤害后的新状态；实现应负责 HP 下限
            截断、濒死标记等具体 ``BattleState`` 语义，不能原地修改旧状态。
        event_id: 当前伤害随机事件的稳定标识，例如招式实例或执行阶段 ID。
        source_key: 可选的解释来源键，例如 ``damage.random-roll``。

    Returns:
        等概率伤害档位转换、按稳定状态键合并后的精确后继分布。

    Raises:
        EmptyTransitionSetError: 伤害结果没有任何随机档位。
        InvalidTransitionEventError: 存在负伤害或 ``event_id`` 为空。
    """
    rolls = tuple(damage_result.rolls)
    if not rolls:
        raise EmptyTransitionSetError("damage roll result cannot be empty")
    if not event_id.strip():
        raise InvalidTransitionEventError("damage roll event_id cannot be empty")

    probability = Fraction(1, len(rolls))
    transitions: list[WeightedTransition[StateT]] = []
    for index, damage in enumerate(rolls):
        if damage < 0:
            raise InvalidTransitionEventError(
                "damage roll values must be greater than or equal to 0"
            )
        event = TransitionEvent(
            event_type=TransitionEventType.DAMAGE_ROLL,
            event_id=event_id,
            outcome_id=f"roll-{index}",
            numeric_value=damage,
        )
        transitions.append(
            WeightedTransition(
                probability=probability,
                state=apply_damage(state, damage),
                event_summary=TransitionEventSummary.single(event),
                source_key=source_key,
            )
        )

    return merge_equivalent_transitions(transitions)


__all__ = [
    "EmptyTransitionSetError",
    "InvalidStateKeyError",
    "InvalidTransitionEventError",
    "InvalidTransitionProbabilityError",
    "StateKeyed",
    "TransitionError",
    "TransitionEvent",
    "TransitionEventSummary",
    "TransitionEventType",
    "UnnormalizedTransitionSetError",
    "WeightedTransition",
    "branch_transitions",
    "combine_independent_transitions",
    "damage_rolls_to_transitions",
    "merge_equivalent_transitions",
    "normalize_transition_weights",
    "total_transition_probability",
    "validate_transition_distribution",
]
