from __future__ import annotations

from pokeop.application.use_cases.configuration_speed_goals import (
    ConfigurationSpeedGoalCommand,
)
from pokeop.application.use_cases.search_configuration_spreads_with_speed import (
    SearchPokemonStatSpreadsWithSpeedCommand,
    SearchPokemonStatSpreadsWithSpeedUseCase,
)
from pokeop.application.use_cases.solve_configuration_with_speed import (
    SolvePokemonConfigurationWithSpeedCommand,
    SolvePokemonConfigurationWithSpeedUseCase,
)
from tests.application.use_cases.test_calculate_catalog_damage import (
    SCIZOR_ID,
    SYLVEON_ID,
    FakeCalculatorRepository,
)
from tests.application.use_cases.test_calculate_catalog_damage_with_abilities import (
    FakeCalculatorAbilityRepository,
)


def speed_goal(
    *,
    target_preset: str,
) -> ConfigurationSpeedGoalCommand:
    """创建巨钳螳螂需要严格快于仙子伊布指定配置的速度目标。

    Args:
        target_preset: 仙子伊布使用的内置配置 key 或不可变配置快照。

    Returns:
        可复用于模板验证和属性反推的严格速度目标命令。
    """
    return ConfigurationSpeedGoalCommand(
        goal_id="outspeed-sylveon",
        target_pokemon_id=SYLVEON_ID,
        target_stat_preset=target_preset,
    )


def test_preset_solver_accepts_speed_goal_without_damage_goals() -> None:
    """
    用户可能只关心一条速度线，而不添加任何攻击或防守伤害目标。该场景使用五十级无投入中性巨钳螳螂
    对比五十级无投入中性仙子伊布，前者实际速度应为八十五，后者应为八十，因此已有配置验证模式必须
    返回可达候选，并提供 subject_speed、target_speed 和正五点 speed_margin。这个测试保护速度目标可以
    独立成为合法求解约束，也保护“超过”采用实际能力值严格大于，而不是依赖种族值或错误复用伤害字段。
    """
    result = SolvePokemonConfigurationWithSpeedUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    ).execute(
        SolvePokemonConfigurationWithSpeedCommand(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            speed_goals=(speed_goal(target_preset="no_investment"),),
            allowed_stat_presets=("no_investment",),
        )
    )

    assert result.reachable is True
    assert result.candidates[0].stats.speed == 85
    evidence = result.candidates[0].speed_goal_results[0]
    assert evidence.satisfied is True
    assert evidence.subject_speed == 85
    assert evidence.target_speed == 80
    assert evidence.speed_margin == 5


def test_spread_search_finds_minimum_speed_ev_to_cross_target_line() -> None:
    """
    自动反推模式面对五十级极限速度仙子伊布时，需要同时选择速度性格和足够的 Speed EV，而不能继续
    沿用旧实现中固定的零速度投入。巨钳螳螂在开朗性格、三十一 Speed IV 下，二百二十 Speed EV
    恰好得到一百二十四实际速度，严格超过目标的一百二十三；再少一个有效 EV 档就会同速或更慢。
    测试同时断言候选代表值、严格速度证据以及 EV/IV 独立安全下界，防止搜索器漏算速度性格、把同速
    视为成功，或返回无法真正跨过目标速度线的区间解。
    """
    result = SearchPokemonStatSpreadsWithSpeedUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    ).execute(
        SearchPokemonStatSpreadsWithSpeedCommand(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            speed_goals=(speed_goal(target_preset="max_speed_plus"),),
            max_candidates=3,
        )
    )

    assert result.reachable is True
    candidate = result.candidates[0]
    assert candidate.nature_id == "jolly"
    assert candidate.evs.speed == 220
    assert candidate.ivs.speed == 31
    assert candidate.stats.speed == 124
    assert candidate.ev_ranges.speed.minimum == 220
    assert candidate.iv_ranges.speed.minimum == 31
    evidence = candidate.speed_goal_results[0]
    assert evidence.target_speed == 123
    assert evidence.speed_margin == 1


def test_preset_solver_rejects_equal_speed_as_not_outspeeding() -> None:
    """
    速度目标的产品文案是“超过指定配置”，因此同速不能被解释为已经达标。这里让待配置巨钳螳螂和
    速度目标都引用同一只巨钳螳螂的无投入中性配置，两侧实际速度均为八十五。求解器必须返回不可达，
    rejected_speed_goal_results 中保留零点差值并标记 satisfied 为假。该测试锁定严格大于语义，避免未来
    为了放宽搜索而误改成大于等于，也为后续加入顺风、围巾或速度等级时保留清晰的基础比较边界。
    """
    result = SolvePokemonConfigurationWithSpeedUseCase(
        FakeCalculatorRepository(),
        FakeCalculatorAbilityRepository(),
    ).execute(
        SolvePokemonConfigurationWithSpeedCommand(
            subject_pokemon_id=SCIZOR_ID,
            subject_ability_identifier="swarm",
            speed_goals=(
                ConfigurationSpeedGoalCommand(
                    goal_id="equal-speed-line",
                    target_pokemon_id=SCIZOR_ID,
                    target_stat_preset="no_investment",
                ),
            ),
            allowed_stat_presets=("no_investment",),
        )
    )

    assert result.reachable is False
    assert result.candidates == ()
    evidence = result.rejected_speed_goal_results[0]
    assert evidence.satisfied is False
    assert evidence.subject_speed == 85
    assert evidence.target_speed == 85
    assert evidence.speed_margin == 0
