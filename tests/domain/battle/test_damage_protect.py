from __future__ import annotations

from dataclasses import replace

from pokeop.domain.battle.damage import calculate_damage_rolls
from pokeop.domain.battle.modifiers import ModifierStage
from pokeop.domain.battle.rulesets.profiles import GEN9_RULESET
from tests.domain.battle.helpers import BattleMoveFactory, BattlePokemonFactory


def _modifiers_by_key(result):
    return {modifier.key: modifier for modifier in result.applied_modifiers}


def test_protect_reduction_lowers_damage_and_records_protect_stage():
    """
    验证 is_protect_reduced=True 只表达保护类穿透伤害减免 hook，而不是完整 Protect 行动判定。
    同一攻击方、防守方和物理招式在普通场景与 protect reduction 场景下计算，后者伤害必须更低；
    trace 需要记录 protect_reduction 且 stage 为 PROTECT，方便 Phase 2 确认该机制不属于行动合法性 gate。
    """
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    normal = calculate_damage_rolls(attacker=attacker, defender=defender, move=move)
    protected = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_protect_reduced=True,
    )

    modifier = _modifiers_by_key(protected)["protect_reduction"]
    assert protected.max_damage < normal.max_damage
    assert modifier.multiplier == GEN9_RULESET.damage_policy.protect_damage_multiplier
    assert modifier.stage is ModifierStage.PROTECT
    assert "Protect-style" in modifier.reason


def test_protect_multiplier_is_policy_configurable():
    """
    验证保护类减伤倍率来自 DamagePolicy，而不是 ProtectDamageModifier 内部硬编码。
    自定义 ruleset 将 protect_damage_multiplier 改为十分之一，同一 protect reduction 场景应比默认规则更低；
    trace multiplier 必须等于自定义 policy，保护未来 Z/Max 类穿保护减伤规则通过 policy 接入。
    """
    ruleset = replace(
        GEN9_RULESET,
        damage_policy=replace(GEN9_RULESET.damage_policy, protect_damage_multiplier=0.1),
    )
    attacker = BattlePokemonFactory.scizor("max_atk_neutral")
    defender = BattlePokemonFactory.sylveon("max_hp")
    move = BattleMoveFactory.bullet_punch()

    default = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        is_protect_reduced=True,
    )
    custom = calculate_damage_rolls(
        attacker=attacker,
        defender=defender,
        move=move,
        ruleset=ruleset,
        is_protect_reduced=True,
    )

    assert custom.max_damage < default.max_damage
    assert _modifiers_by_key(custom)["protect_reduction"].multiplier == 0.1


def test_non_protect_reduction_does_not_write_protect_trace():
    """
    验证默认伤害场景不会写入 protect_reduction trace，避免把普通 Protect 行动 gate 与本轮最小减伤 hook 混淆。
    本测试不传 is_protect_reduced，仍通过正式伤害入口计算标准子弹拳场景；
    结果 trace 中不能出现 PROTECT 阶段，后续 application 只有显式设置该字段时才会消费此能力。
    """
    result = calculate_damage_rolls(
        attacker=BattlePokemonFactory.scizor("max_atk_neutral"),
        defender=BattlePokemonFactory.sylveon("max_hp"),
        move=BattleMoveFactory.bullet_punch(),
    )

    assert "protect_reduction" not in _modifiers_by_key(result)
