"""定义行动选择策略的精确概率合同。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Generic, Protocol, Sequence, TypeVar, runtime_checkable


ActionT = TypeVar("ActionT")


class ActionPolicyError(ValueError):
    """行动策略合同被违反时的基础异常。"""


class NoLegalActionsError(ActionPolicyError):
    """表示调用策略时没有任何合法行动可供选择。"""


class InvalidActionDistributionError(ActionPolicyError):
    """表示行动选择权重不是有效的归一化概率分布。"""


class IllegalActionSelectionError(ActionPolicyError):
    """表示策略返回了当前合法行动集合之外的行动。"""


@dataclass(frozen=True, slots=True)
class ActionSelection(Generic[ActionT]):
    """一个合法行动及其玩家选择概率。

    该概率只描述行动策略，不包含命中、伤害乱数、同速判定等战斗随机事件。战斗随机
    概率将在带权状态转移合同中单独表达，避免两类概率被求解器重复相乘或混为一谈。
    """

    action: ActionT
    probability: Fraction

    def __post_init__(self) -> None:
        if not isinstance(self.probability, Fraction):
            raise InvalidActionDistributionError(
                "action selection probability must use fractions.Fraction"
            )
        if not 0 < self.probability <= 1:
            raise InvalidActionDistributionError(
                "action selection probability must be in the interval (0, 1]"
            )


@dataclass(frozen=True, slots=True)
class ActionDistribution(Generic[ActionT]):
    """行动策略对当前合法行动集合给出的精确概率分布。"""

    selections: tuple[ActionSelection[ActionT], ...]

    def __post_init__(self) -> None:
        if not self.selections:
            raise NoLegalActionsError("action distribution cannot be empty")

        seen_actions: list[ActionT] = []
        for selection in self.selections:
            if any(selection.action == seen for seen in seen_actions):
                raise InvalidActionDistributionError(
                    "action distribution cannot contain duplicate actions"
                )
            seen_actions.append(selection.action)

        if self.total_probability != Fraction(1, 1):
            raise InvalidActionDistributionError(
                "action selection probabilities must sum exactly to 1"
            )

    @property
    def total_probability(self) -> Fraction:
        """返回行动选择概率总和，供求解边界做显式断言。"""
        return sum(
            (selection.probability for selection in self.selections),
            start=Fraction(0, 1),
        )

    def validate_legal_actions(self, legal_actions: Sequence[ActionT]) -> None:
        """确认策略没有选择当前集合之外的行动。

        求解器应在接收任意自定义策略的结果后调用该方法。策略可以只给部分合法行动
        非零概率，但不能制造、执行或替换合法行动。
        """
        if not legal_actions:
            raise NoLegalActionsError("cannot validate a policy without legal actions")
        for selection in self.selections:
            if selection.action not in legal_actions:
                raise IllegalActionSelectionError(
                    "action policy selected an action outside the legal action set"
                )

    @classmethod
    def deterministic(cls, action: ActionT) -> ActionDistribution[ActionT]:
        """创建只选择一个行动的确定性分布。"""
        return cls((ActionSelection(action=action, probability=Fraction(1, 1)),))


@runtime_checkable
class ActionPolicy(Protocol[ActionT]):
    """从当前合法行动集合生成玩家行动选择分布的稳定协议。"""

    @property
    def policy_id(self) -> str:
        """返回可记录到推演结果中的稳定策略标识。"""

    @property
    def description(self) -> str:
        """返回面向结果解释层的策略假设说明。"""

    def distribution_for(
        self,
        legal_actions: Sequence[ActionT],
    ) -> ActionDistribution[ActionT]:
        """为当前合法行动返回归一化选择概率，不执行任何战斗效果。"""


# 保留旧名称兼容既有调用方，同时把公开边界明确命名为行动选择策略。
ActionSelectionPolicy = ActionPolicy


class UniformRandomPolicy(Generic[ActionT]):
    """对当前每个具体合法行动赋予相同玩家选择概率。"""

    @property
    def policy_id(self) -> str:
        return "uniform-random"

    @property
    def description(self) -> str:
        return "从当前全部合法具体行动中等概率选择"

    def distribution_for(
        self,
        legal_actions: Sequence[ActionT],
    ) -> ActionDistribution[ActionT]:
        if not legal_actions:
            raise NoLegalActionsError(
                "uniform random policy requires at least one legal action"
            )
        probability = Fraction(1, len(legal_actions))
        distribution = ActionDistribution(
            tuple(
                ActionSelection(action=action, probability=probability)
                for action in legal_actions
            )
        )
        distribution.validate_legal_actions(legal_actions)
        return distribution


class FirstLegalActionPolicy(Generic[ActionT]):
    """测试或调试时选择调用方稳定排序后的第一个合法行动。"""

    @property
    def policy_id(self) -> str:
        return "first-legal-action"

    @property
    def description(self) -> str:
        return "仅用于测试或调试：始终选择合法行动列表中的第一项"

    def distribution_for(
        self,
        legal_actions: Sequence[ActionT],
    ) -> ActionDistribution[ActionT]:
        if not legal_actions:
            raise NoLegalActionsError(
                "first legal action policy requires at least one legal action"
            )
        distribution = ActionDistribution.deterministic(legal_actions[0])
        distribution.validate_legal_actions(legal_actions)
        return distribution
