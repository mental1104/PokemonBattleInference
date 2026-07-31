from __future__ import annotations

from pokeop.domain.battle.state import StatStages
from pokeop.domain.battle.stats import StatValues


def apply_stat_stage(value: int, stage: int) -> int:
    """按现代能力等级公式换算一项正整数实际能力。

    Args:
        value: 性格、EV、IV 和等级已经计算完成的正整数实际能力值。
        stage: 战斗中的能力等级，必须位于 -6 到 +6；0 表示不变。

    Returns:
        应用 ``(2 + stage) / 2`` 或 ``2 / (2 - stage)`` 后向下取整的正整数能力值。

    Raises:
        ValueError: value 不是正整数，或 stage 超出游戏允许范围时抛出。
    """
    if isinstance(value, bool) or value <= 0:
        raise ValueError("stat value must be a positive integer")
    if isinstance(stage, bool) or not -6 <= stage <= 6:
        raise ValueError("stat stage must be between -6 and 6")
    if stage >= 0:
        numerator = 2 + stage
        denominator = 2
    else:
        numerator = 2
        denominator = 2 - stage
    return max(1, value * numerator // denominator)


def apply_stat_stages(stats: StatValues, stages: StatStages) -> StatValues:
    """把战斗中的五项数值能力等级应用到一组实际能力值。

    HP 不存在战斗能力等级，因此保持原值；命中与回避不属于 ``StatValues``，继续保留在
    ``StatStages`` 供命中判定使用。该函数只负责纯数值换算，不判断特性、会心或规则集
    是否应忽略某一侧的等级变化。

    Args:
        stats: 配置模板已经展开得到的六项实际能力值。
        stages: 包含攻击、防御、特攻、特防、速度、命中和回避的不可变等级快照。

    Returns:
        HP 不变，攻击、防御、特攻、特防和速度已经应用对应等级的新 ``StatValues``。

    Raises:
        TypeError: stats 或 stages 不是对应的显式领域类型时抛出。
    """
    if not isinstance(stats, StatValues):
        raise TypeError("stats must be StatValues")
    if not isinstance(stages, StatStages):
        raise TypeError("stages must be StatStages")
    return StatValues(
        hp=stats.hp,
        attack=apply_stat_stage(stats.attack, stages.attack),
        defense=apply_stat_stage(stats.defense, stages.defense),
        special_attack=apply_stat_stage(
            stats.special_attack,
            stages.special_attack,
        ),
        special_defense=apply_stat_stage(
            stats.special_defense,
            stages.special_defense,
        ),
        speed=apply_stat_stage(stats.speed, stages.speed),
    )


__all__ = ["apply_stat_stage", "apply_stat_stages"]
