"""提供置换不变的一对一推演 application 门面。"""

from __future__ import annotations

from dataclasses import dataclass

from . import _core
from ._core import *  # noqa: F403


BATTLE_INFERENCE_CALCULATION_REVISION = "battle-inference.summary-exploration.v2"
_core.BATTLE_INFERENCE_CALCULATION_REVISION = BATTLE_INFERENCE_CALCULATION_REVISION


@dataclass(frozen=True, slots=True)
class PokemonInferenceSelection(_core.PokemonInferenceSelection):
    """声明固定配置所需的无序技能组和能力预设。

    固定配置入口在校验唯一正整数 ID 后按 ``move_id`` 排序，使相同技能组的所有输入
    置换共享同一配置键、初始状态和缓存入口。排序仅发生在战斗开始前，不会改写运行时
    槽位顺序。
    """

    def __post_init__(self) -> None:
        """复用既有校验并将技能组规范化为稳定升序元组。"""
        _core.PokemonInferenceSelection.__post_init__(self)
        object.__setattr__(self, "move_ids", tuple(sorted(self.move_ids)))


@dataclass(frozen=True, slots=True)
class InferConfigurationSpaceBattleCommand(
    _core.InferConfigurationSpaceBattleCommand
):
    """声明批量配置空间推演，并默认使用置换不变的等概率行动策略。"""

    attacker_policy: BattleActionPolicyKind = (  # noqa: F405
        BattleActionPolicyKind.UNIFORM_RANDOM  # noqa: F405
    )
    defender_policy: BattleActionPolicyKind = (  # noqa: F405
        BattleActionPolicyKind.UNIFORM_RANDOM  # noqa: F405
    )


__all__ = _core.__all__
