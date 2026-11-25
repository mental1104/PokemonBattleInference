from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


class InvalidMoveExecutionPolicy(ValueError):
    """表示首版通用招式执行规则超出当前实现能够稳定表达的范围。"""


@dataclass(frozen=True, slots=True)
class MoveExecutionPolicy:
    """冻结通用招式执行中的 PP、命中与挣扎规则。

    该策略属于纯 domain 规则集配置，不识别任何具体招式 identifier。首版固定采用
    百分制命中率：合法普通招式在命中判定前消耗 1 PP，未命中仍保留该消耗；在
    ``ValidateActionEffect`` 阶段被阻止或在 ``BeforeMoveEffect`` 阶段提前结束时
    不消耗 PP。后续世代差异应新增策略实现或扩展显式字段，而不是在执行器中散落
    generation 判断。

    Args:
        accuracy_denominator: 招式命中率的分母。首版固定为 100。
        consume_pp_on_miss: 未命中时是否消耗已选择招式的 PP；首版固定为 True。
        consume_pp_when_action_blocked: 行动在执行前被畏缩等效果阻止时是否消耗 PP；
            首版固定为 False。
        consume_pp_when_before_move_stops: ``BeforeMoveEffect`` 在命中判定前终止行动时
            是否消耗 PP；首版固定为 False。
        struggle_power: 挣扎使用的基础威力，必须为正整数。
        struggle_recoil_fraction: 挣扎反伤占使用者最大 HP 的比例，必须位于 ``(0, 1]``。
    """

    accuracy_denominator: int = 100
    consume_pp_on_miss: bool = True
    consume_pp_when_action_blocked: bool = False
    consume_pp_when_before_move_stops: bool = False
    struggle_power: int = 50
    struggle_recoil_fraction: Fraction = Fraction(1, 4)

    def __post_init__(self) -> None:
        """校验首版执行语义和挣扎参数。

        Raises:
            InvalidMoveExecutionPolicy: 命中率分母、PP 语义或挣扎参数不受首版支持时抛出。
        """
        if self.accuracy_denominator != 100:
            raise InvalidMoveExecutionPolicy(
                "the first move execution policy requires percentage accuracy"
            )
        if self.consume_pp_on_miss is not True:
            raise InvalidMoveExecutionPolicy(
                "the first move execution policy consumes pp on miss"
            )
        if self.consume_pp_when_action_blocked is not False:
            raise InvalidMoveExecutionPolicy(
                "the first move execution policy does not consume pp when blocked"
            )
        if self.consume_pp_when_before_move_stops is not False:
            raise InvalidMoveExecutionPolicy(
                "the first move execution policy does not consume pp before move stops"
            )
        if isinstance(self.struggle_power, bool) or self.struggle_power <= 0:
            raise InvalidMoveExecutionPolicy("struggle_power must be greater than 0")
        if not isinstance(self.struggle_recoil_fraction, Fraction):
            raise InvalidMoveExecutionPolicy(
                "struggle_recoil_fraction must use fractions.Fraction"
            )
        if not 0 < self.struggle_recoil_fraction <= 1:
            raise InvalidMoveExecutionPolicy(
                "struggle_recoil_fraction must be in the interval (0, 1]"
            )


__all__ = ["InvalidMoveExecutionPolicy", "MoveExecutionPolicy"]
