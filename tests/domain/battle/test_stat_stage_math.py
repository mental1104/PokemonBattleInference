from __future__ import annotations

import pytest

from pokeop.domain.battle.stat_stage_math import apply_stat_stage, apply_stat_stages
from pokeop.domain.battle.state import StatStages
from pokeop.domain.battle.stats import StatValues


def test_apply_stat_stages_uses_modern_positive_and_negative_multipliers() -> None:
    """
    该场景用一组容易人工核对的实际能力值验证现代战斗能力等级公式：攻击提升两级应从一百变成两百，
    防御降低两级应从一百二十变成六十，特攻提升一级应按三比二得到一百三十五，特防降低一级应按
    二比三向下取整得到七十三，速度提升六级应扩大到四倍。HP 不存在能力等级，必须原样保留二百；
    命中和回避虽然存在于 StatStages 中，却不能被误写进六项 StatValues。这个测试保护公式分子分母、
    floor 顺序和字段映射，避免前端传入的七项选择在 domain 边界被错位应用或把 HP 一并放大。
    """
    stats = StatValues(
        hp=200,
        attack=100,
        defense=120,
        special_attack=90,
        special_defense=110,
        speed=80,
    )
    stages = StatStages(
        attack=2,
        defense=-2,
        special_attack=1,
        special_defense=-1,
        speed=6,
        accuracy=3,
        evasion=-3,
    )

    result = apply_stat_stages(stats, stages)

    assert result == StatValues(
        hp=200,
        attack=200,
        defense=60,
        special_attack=135,
        special_defense=73,
        speed=320,
    )


def test_apply_stat_stage_rejects_non_stat_values_and_out_of_range_stages() -> None:
    """
    能力等级换算是伤害计算的可信领域边界，不能接受零能力、布尔值或超过正负六级的输入。虽然 HTTP
    schema 已经限制用户请求，application 和未来状态推演仍可能直接调用该纯函数，因此测试分别传入
    非正能力、把 True 伪装成整数能力、正七级和负七级，要求全部稳定抛出 ValueError。该场景防止
    Python 中 bool 继承 int 的特性绕过校验，也防止非法等级产生负分母或看似合理但不属于游戏规则的
    倍率结果；合法的零级则必须保持原能力不变，确保默认请求继续兼容旧伤害基线。
    """
    assert apply_stat_stage(137, 0) == 137

    with pytest.raises(ValueError, match="positive integer"):
        apply_stat_stage(0, 0)
    with pytest.raises(ValueError, match="positive integer"):
        apply_stat_stage(True, 0)
    with pytest.raises(ValueError, match="between -6 and 6"):
        apply_stat_stage(100, 7)
    with pytest.raises(ValueError, match="between -6 and 6"):
        apply_stat_stage(100, -7)
