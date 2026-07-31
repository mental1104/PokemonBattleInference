from __future__ import annotations

from pokeop.application.use_cases.search_configuration_spreads import (
    SearchPokemonStatSpreadsCommand,
    SearchPokemonStatSpreadsUseCase,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalCommand,
    ConfigurationGoalKind,
    DamageRollPolicy,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    BULLET_PUNCH_ID,
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import (
    FakeCalculatorAbilityRepository,
)


def spread_search_use_case() -> SearchPokemonStatSpreadsUseCase:
    """创建同时提供 catalog 与合法特性关系的属性反推用例。

    Returns:
        使用内存 fake repository 的 EV、IV 与性格反推 use case。
    """
    return SearchPokemonStatSpreadsUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    )


def attack_search_command(*, required_turns: int) -> SearchPokemonStatSpreadsCommand:
    """创建巨钳螳螂使用子弹拳攻击无投入仙子伊布的属性反推命令。

    Args:
        required_turns: 目标允许的攻击次数，一次用于不可达场景，两次用于可达场景。

    Returns:
        固定双方特性、目标配置和最低伤害档口径的搜索命令。
    """
    return SearchPokemonStatSpreadsCommand(
        subject_pokemon_id=SCIZOR_ID,
        subject_ability_identifier="swarm",
        goals=(
            ConfigurationGoalCommand(
                goal_id=f"attack-sylveon-{required_turns}hko",
                kind=ConfigurationGoalKind.ATTACK,
                target_pokemon_id=SYLVEON_ID,
                move_id=BULLET_PUNCH_ID,
                required_turns=required_turns,
                target_ability_identifier="cute-charm",
                target_stat_preset="no_investment",
                damage_roll_policy=DamageRollPolicy.MIN,
            ),
        ),
        max_candidates=10,
    )


def test_spread_search_returns_ranked_legal_candidates_and_independent_ranges():
    """
    巨钳螳螂需要在最低伤害档下用两次子弹拳击倒无投入仙子伊布，搜索器应在不预先提供模板的
    前提下反推出合法性格、EV 与 IV。每条代表分配必须满足单项 EV 不超过 252、总 EV 不超过
    510、IV 位于 0..31，并通过原有 domain 伤害链复核全部目标；返回区间必须包住代表值，且
    明确保持 Speed EV 为零。该场景保护“自动反推”不是把内置模板换个名字，而是真正搜索配置。
    """
    result = spread_search_use_case().execute(attack_search_command(required_turns=2))

    assert result.reachable is True
    assert 1 <= len(result.candidates) <= 10
    assert all(candidate.evs.total() <= 510 for candidate in result.candidates)
    assert all(max(candidate.evs.values()) <= 252 for candidate in result.candidates)
    assert all(min(candidate.ivs.values()) >= 0 for candidate in result.candidates)
    assert all(max(candidate.ivs.values()) <= 31 for candidate in result.candidates)

    candidate = result.candidates[0]
    assert candidate.nature_options
    assert candidate.evs.speed == 0
    assert all(goal.satisfied for goal in candidate.goal_results)
    assert candidate.ev_ranges.attack.minimum <= candidate.evs.attack
    assert candidate.evs.attack <= candidate.ev_ranges.attack.maximum
    assert candidate.iv_ranges.attack.minimum <= candidate.ivs.attack
    assert candidate.ivs.attack <= candidate.iv_ranges.attack.maximum
    assert any("单字段独立安全区间" == item for item in result.scope)
    assert any("不要把六项区间任意组合" in warning for warning in result.warnings)


def test_spread_search_reports_unreachable_without_violating_ev_budget():
    """
    当巨钳螳螂被要求在最低伤害档下一次子弹拳击倒仙子伊布时，即便搜索器枚举全部相关性格、
    采用六项 31 个体值并允许攻击投入达到 252，也不能通过超出 510 总 EV、伪造伤害或放宽目标
    来制造候选。结果应明确标记不可达、候选为空，并返回零努力值基线的逐目标失败证据，供页面
    解释当前约束为何无法满足。该测试保护搜索边界和不可达语义不会被优化算法悄悄破坏。
    """
    result = spread_search_use_case().execute(attack_search_command(required_turns=1))

    assert result.reachable is False
    assert result.candidates == ()
    assert len(result.rejected_goal_results) == 1
    assert result.rejected_goal_results[0].satisfied is False
    assert result.rejected_goal_results[0].remaining_hp > 0
