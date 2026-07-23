from __future__ import annotations

from pokeop.domain.battle.inference_rules import (
    BattleFormat,
    BattleInferenceRules,
    CycleResolution,
    InvalidBattleInferenceRules,
    RepetitionResolution,
    SwitchingPolicy,
)
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy


def test_default_inference_rules_freeze_first_one_on_one_contract():
    """默认规则必须完整表达首版范围和三条独立的无限战局保护线。"""
    rules = BattleInferenceRules()

    assert rules.ruleset_id == "pokemon-champion"
    assert rules.version_group_id == 25
    assert rules.level == 50
    assert rules.battle_format is BattleFormat.ONE_ON_ONE_SINGLES
    assert rules.switching_policy is SwitchingPolicy.DISABLED
    assert rules.allow_terastallization is False
    assert rules.allow_mega_evolution is False
    assert rules.allow_dynamax is False
    assert rules.max_turns == 100
    assert rules.repetition_resolution is RepetitionResolution.DECLARE_DRAW
    assert rules.cycle_resolution is CycleResolution.DECLARE_DRAW
    assert rules.damage_policy == DamagePolicy()


def test_inference_rules_allow_disabling_product_turn_limit_without_hiding_cycle_policy():
    """回合上限可关闭，但重复与循环语义仍必须由显式枚举保留。"""
    rules = BattleInferenceRules(
        max_turns=None,
        repetition_resolution=RepetitionResolution.CONTINUE,
        cycle_resolution=CycleResolution.SOLVE_ABSORPTION_PROBABILITY,
    )

    assert rules.max_turns is None
    assert rules.repetition_resolution is RepetitionResolution.CONTINUE
    assert rules.cycle_resolution is CycleResolution.SOLVE_ABSORPTION_PROBABILITY


def test_inference_rules_reject_transformations_outside_first_contract():
    """首版不能通过布尔开关偷偷进入太晶、Mega 或极巨化分支。"""
    try:
        BattleInferenceRules(allow_terastallization=True)
    except InvalidBattleInferenceRules as exc:
        assert "terastallization" in str(exc)
    else:
        raise AssertionError("expected unsupported transformation to be rejected")


def test_inference_rules_reject_invalid_level_and_turn_limit():
    """等级和产品保护回合上限必须在构造时失败，而不是留给求解器猜测。"""
    for kwargs in ({"level": 0}, {"level": 101}, {"max_turns": 0}):
        try:
            BattleInferenceRules(**kwargs)
        except InvalidBattleInferenceRules:
            continue
        raise AssertionError(f"expected invalid rules to be rejected: {kwargs}")
