"""定义配置求解中的严格速度目标及其复核结果。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.use_cases.calculate_catalog_damage import (
    CalculatorCatalogRepository,
    CalculatorPokemonProfile,
    CalculatorRulesetContext,
    stat_profile_from_preset,
)
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationSolverInputError,
)
from pokeop.domain.battle.stats import (
    NatureModifier,
    StatProfile,
    StatValues,
    calculate_actual_stats,
)
from pokeop.domain.models.pokemon_fields import StatField


@dataclass(frozen=True, slots=True)
class ConfigurationSpeedGoalCommand:
    """要求待配置 Pokémon 严格快于指定 Pokémon 配置。

    Args:
        goal_id: 前端生成的稳定目标 ID，必须在全部伤害与速度目标中唯一。
        target_pokemon_id: 作为速度线参照的 Pokémon ID，必须为正整数。
        target_stat_preset: 参照 Pokémon 使用的内置配置 key 或不可变配置快照。
    """

    goal_id: str
    target_pokemon_id: int
    target_stat_preset: str


@dataclass(frozen=True, slots=True)
class PreparedConfigurationSpeedGoal:
    """缓存速度目标在一次搜索中不会变化的目标资料与实际速度。"""

    command: ConfigurationSpeedGoalCommand
    target: CalculatorPokemonProfile
    target_stats: StatValues


@dataclass(frozen=True, slots=True)
class ConfigurationSpeedGoalResult:
    """一套候选配置对单个严格速度目标的复核证据。

    Args:
        goal_id: 对应请求中的稳定目标 ID。
        satisfied: 待配置 Pokémon 的实际 Speed 是否严格大于目标实际 Speed。
        target: 速度线参照 Pokémon 的 application 读取模型。
        subject_speed: 当前候选配置计算得到的待配置 Pokémon 实际 Speed。
        target_speed: 参照配置计算得到的目标 Pokémon 实际 Speed。
        speed_margin: 两者差值；大于零才表示成功超过速度线。
    """

    goal_id: str
    satisfied: bool
    target: CalculatorPokemonProfile
    subject_speed: int
    target_speed: int
    speed_margin: int


def prepare_configuration_speed_goals(
    *,
    repository: CalculatorCatalogRepository,
    ruleset: CalculatorRulesetContext,
    level: int,
    goals: tuple[ConfigurationSpeedGoalCommand, ...],
) -> tuple[PreparedConfigurationSpeedGoal, ...]:
    """读取并计算速度目标的固定参照配置。

    Args:
        repository: 提供 Pokémon 战斗读取模型的 catalog repository。
        ruleset: 当前求解使用的规则集上下文。
        level: 双方统一使用的等级，范围由上层命令校验为 1..100。
        goals: 用户添加的严格速度目标。

    Returns:
        包含目标 Pokémon、配置实际能力和原始命令的不可变元组。

    Raises:
        ConfigurationSolverInputError: 目标 ID、Pokémon ID、配置或 Pokémon 不合法时抛出。
    """
    prepared: list[PreparedConfigurationSpeedGoal] = []
    for goal in goals:
        if not goal.goal_id or goal.goal_id != goal.goal_id.strip():
            raise ConfigurationSolverInputError(
                "speed goal_id must be a normalized non-empty string"
            )
        if goal.target_pokemon_id <= 0:
            raise ConfigurationSolverInputError(
                "speed target_pokemon_id must be positive"
            )
        if not goal.target_stat_preset.strip():
            raise ConfigurationSolverInputError(
                "speed target_stat_preset is required"
            )
        target = repository.get_pokemon_profile(
            ruleset_id=ruleset.ruleset_id,
            pokemon_id=goal.target_pokemon_id,
        )
        if target is None:
            raise ConfigurationSolverInputError(
                f"unknown speed target pokemon_id: {goal.target_pokemon_id}"
            )
        target_stats = calculate_actual_stats(
            _speed_target_profile(goal.target_stat_preset, target.base_stats),
            level=level,
        )
        prepared.append(
            PreparedConfigurationSpeedGoal(
                command=goal,
                target=target,
                target_stats=target_stats,
            )
        )
    return tuple(prepared)


def evaluate_configuration_speed_goals(
    *,
    subject_stats: StatValues,
    goals: tuple[PreparedConfigurationSpeedGoal, ...],
) -> tuple[ConfigurationSpeedGoalResult, ...]:
    """使用同一套候选能力值复核全部严格速度目标。

    Args:
        subject_stats: 待配置 Pokémon 在当前候选下的实际六项能力值。
        goals: 已准备完成的速度目标及其固定目标速度。

    Returns:
        按请求顺序排列的速度比较证据；相等速度不视为满足“超过”。
    """
    return tuple(
        ConfigurationSpeedGoalResult(
            goal_id=goal.command.goal_id,
            satisfied=subject_stats.speed > goal.target_stats.speed,
            target=goal.target,
            subject_speed=subject_stats.speed,
            target_speed=goal.target_stats.speed,
            speed_margin=subject_stats.speed - goal.target_stats.speed,
        )
        for goal in goals
    )


def configuration_speed_goals_satisfied(
    *,
    subject_stats: StatValues,
    goals: tuple[PreparedConfigurationSpeedGoal, ...],
) -> bool:
    """快速判断当前候选是否严格快于全部速度目标。

    Args:
        subject_stats: 待配置 Pokémon 的当前实际能力值。
        goals: 已准备完成的速度目标集合。

    Returns:
        全部目标均满足时返回 True；空集合也返回 True。
    """
    return all(subject_stats.speed > goal.target_stats.speed for goal in goals)


def _speed_target_profile(preset_key: str, base_stats: StatValues) -> StatProfile:
    """把速度目标配置转换为 domain StatProfile。

    Args:
        preset_key: 配置管理中的内置 key 或不可变配置快照。
        base_stats: 参照 Pokémon 的六项种族值。

    Returns:
        可交给现代能力值公式计算的完整配置。

    Raises:
        ConfigurationSolverInputError: 配置 key 或快照不合法时由现有转换逻辑抛出。
    """
    if preset_key == "max_speed_plus":
        # 配置管理已经公开“极限速度”，但旧伤害模板集合不包含它；速度目标在边界处
        # 显式展开，避免为了比较 Speed 扩大原伤害计算器的模板语义。
        return StatProfile(
            base_stats=base_stats,
            evs=StatValues(speed=252),
            nature_modifier=NatureModifier.increase(StatField.SPEED),
        )
    return stat_profile_from_preset(preset_key, base_stats)


__all__ = [
    "ConfigurationSpeedGoalCommand",
    "ConfigurationSpeedGoalResult",
    "PreparedConfigurationSpeedGoal",
    "configuration_speed_goals_satisfied",
    "evaluate_configuration_speed_goals",
    "prepare_configuration_speed_goals",
]
