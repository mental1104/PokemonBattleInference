"""定义支持严格速度目标的配置求解 HTTP schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.api.schemas.configuration_solver import (
    ConfigurationGoalRequest,
    GoalVerificationResponse,
    NatureOptionResponse,
    SearchConfigurationSpreadsRequest,
    SolveConfigurationRequest,
    SolverPokemonSummary,
    SolvedConfigurationResponse,
    StatSpreadRangeResponse,
    _goal_response,
    _pokemon_summary,
    _range_response,
)
from pokeop.api.schemas.calculator import _stats_to_dict
from pokeop.application.use_cases.configuration_speed_goals import (
    ConfigurationSpeedGoalResult,
)
from pokeop.application.use_cases.search_configuration_spreads_with_speed import (
    SearchPokemonStatSpreadsWithSpeedResult,
)
from pokeop.application.use_cases.solve_configuration_with_speed import (
    SolvePokemonConfigurationWithSpeedResult,
)


class ConfigurationSpeedGoalRequest(BaseModel):
    """要求待配置 Pokémon 严格快于指定目标配置的 HTTP 输入。"""

    goal_id: str = Field(description="前端生成的稳定速度目标 ID。")
    target_pokemon_id: int = Field(
        gt=0,
        description="作为速度线参照的 Pokémon ID。",
    )
    target_stat_preset: str = Field(
        min_length=1,
        description="参照 Pokémon 使用的配置模板或不可变快照。",
    )


class SolveConfigurationWithSpeedRequest(SolveConfigurationRequest):
    """从已有配置中同时验证伤害目标与严格速度目标。"""

    goals: list[ConfigurationGoalRequest] = Field(default_factory=list, max_length=20)
    speed_goals: list[ConfigurationSpeedGoalRequest] = Field(
        default_factory=list,
        max_length=20,
    )


class SearchConfigurationSpreadsWithSpeedRequest(SearchConfigurationSpreadsRequest):
    """根据伤害与严格速度目标反推 EV、IV 和性格。"""

    goals: list[ConfigurationGoalRequest] = Field(default_factory=list, max_length=20)
    speed_goals: list[ConfigurationSpeedGoalRequest] = Field(
        default_factory=list,
        max_length=20,
    )


class SpeedGoalVerificationResponse(BaseModel):
    """候选配置对单个严格速度目标的复核证据。"""

    goal_id: str
    satisfied: bool
    target: SolverPokemonSummary
    subject_speed: int
    target_speed: int
    speed_margin: int


class SolvedConfigurationWithSpeedResponse(SolvedConfigurationResponse):
    """一套候选配置及其伤害、速度两类目标证据。"""

    speed_goals: list[SpeedGoalVerificationResponse] = Field(default_factory=list)


class SolveConfigurationWithSpeedResponse(BaseModel):
    """模板验证或属性反推共用的速度感知响应。"""

    ruleset_id: str
    ruleset_name: str
    subject: SolverPokemonSummary
    level: int
    reachable: bool
    candidates: list[SolvedConfigurationWithSpeedResponse]
    rejected_goals: list[GoalVerificationResponse]
    rejected_speed_goals: list[SpeedGoalVerificationResponse]
    scope: list[str]
    warnings: list[str]


def _speed_goal_response(
    result: ConfigurationSpeedGoalResult,
    *,
    ruleset_id: str,
) -> SpeedGoalVerificationResponse:
    """把 application 严格速度证据转换成 HTTP 响应。

    Args:
        result: application 返回的实际速度比较结果。
        ruleset_id: 生成目标 Pokémon sprite 地址所需的规则集标识。

    Returns:
        前端可直接展示的速度线、差值与满足状态。
    """
    return SpeedGoalVerificationResponse(
        goal_id=result.goal_id,
        satisfied=result.satisfied,
        target=_pokemon_summary(result.target, ruleset_id=ruleset_id),
        subject_speed=result.subject_speed,
        target_speed=result.target_speed,
        speed_margin=result.speed_margin,
    )


def solve_configuration_with_speed_response_from_result(
    result: SolvePokemonConfigurationWithSpeedResult,
) -> SolveConfigurationWithSpeedResponse:
    """把速度感知的已有配置求解结果转换为 HTTP 响应。

    Args:
        result: application 层已有配置候选及两类目标证据。

    Returns:
        solution_kind 为 preset 的速度感知响应。
    """
    ruleset_id = result.ruleset.ruleset_id
    return SolveConfigurationWithSpeedResponse(
        ruleset_id=ruleset_id,
        ruleset_name=result.ruleset.ruleset_name,
        subject=_pokemon_summary(result.subject, ruleset_id=ruleset_id),
        level=result.level,
        reachable=result.reachable,
        candidates=[
            SolvedConfigurationWithSpeedResponse(
                stat_preset=candidate.preset.key,
                stat_preset_label=candidate.preset.label,
                stat_preset_assumption=candidate.preset.assumption,
                stats=_stats_to_dict(candidate.stats),
                goals=[
                    _goal_response(goal, ruleset_id=ruleset_id)
                    for goal in candidate.goal_results
                ],
                speed_goals=[
                    _speed_goal_response(goal, ruleset_id=ruleset_id)
                    for goal in candidate.speed_goal_results
                ],
            )
            for candidate in result.candidates
        ],
        rejected_goals=[
            _goal_response(goal, ruleset_id=ruleset_id)
            for goal in result.rejected_goal_results
        ],
        rejected_speed_goals=[
            _speed_goal_response(goal, ruleset_id=ruleset_id)
            for goal in result.rejected_speed_goal_results
        ],
        scope=list(result.scope),
        warnings=list(result.warnings),
    )


def search_configuration_spreads_with_speed_response_from_result(
    result: SearchPokemonStatSpreadsWithSpeedResult,
) -> SolveConfigurationWithSpeedResponse:
    """把速度感知的属性反推结果转换为共用 HTTP 响应。

    Args:
        result: application 层带代表分配、区间和两类目标证据的结果。

    Returns:
        solution_kind 为 spread 的速度感知响应。
    """
    ruleset_id = result.ruleset.ruleset_id
    return SolveConfigurationWithSpeedResponse(
        ruleset_id=ruleset_id,
        ruleset_name=result.ruleset.ruleset_name,
        subject=_pokemon_summary(result.subject, ruleset_id=ruleset_id),
        level=result.level,
        reachable=result.reachable,
        candidates=[
            SolvedConfigurationWithSpeedResponse(
                stat_preset=candidate.candidate_id,
                stat_preset_label=(
                    f"反推解 · {candidate.nature_label} · EV {candidate.evs.total()}"
                ),
                stat_preset_assumption=(
                    "代表值满足全部目标；区间表示其余五项保持代表值时，"
                    "该字段可独立调整。"
                ),
                solution_kind="spread",
                nature_id=candidate.nature_id,
                nature_label=candidate.nature_label,
                nature_options=[
                    NatureOptionResponse(
                        identifier=option.identifier,
                        label=option.label,
                    )
                    for option in candidate.nature_options
                ],
                evs=candidate.evs.to_dict(),
                ivs=candidate.ivs.to_dict(),
                ev_ranges=_range_response(candidate.ev_ranges),
                iv_ranges=_range_response(candidate.iv_ranges),
                stats=_stats_to_dict(candidate.stats),
                goals=[
                    _goal_response(goal, ruleset_id=ruleset_id)
                    for goal in candidate.goal_results
                ],
                speed_goals=[
                    _speed_goal_response(goal, ruleset_id=ruleset_id)
                    for goal in candidate.speed_goal_results
                ],
            )
            for candidate in result.candidates
        ],
        rejected_goals=[
            _goal_response(goal, ruleset_id=ruleset_id)
            for goal in result.rejected_goal_results
        ],
        rejected_speed_goals=[
            _speed_goal_response(goal, ruleset_id=ruleset_id)
            for goal in result.rejected_speed_goal_results
        ],
        scope=list(result.scope),
        warnings=list(result.warnings),
    )


__all__ = [
    "ConfigurationSpeedGoalRequest",
    "SearchConfigurationSpreadsWithSpeedRequest",
    "SolveConfigurationWithSpeedRequest",
    "SolveConfigurationWithSpeedResponse",
    "SpeedGoalVerificationResponse",
    "search_configuration_spreads_with_speed_response_from_result",
    "solve_configuration_with_speed_response_from_result",
]
