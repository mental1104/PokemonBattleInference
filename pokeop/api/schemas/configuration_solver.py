from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.api.schemas.calculator import _pokemon_sprite_url, _stats_to_dict
from pokeop.application.use_cases.solve_configuration_targets import (
    ConfigurationGoalResult,
    ConfigurationGoalKind,
    DamageRollPolicy,
    SolvePokemonConfigurationResult,
)


class ConfigurationGoalRequest(BaseModel):
    """一条反向求解目标的 HTTP 输入。"""

    goal_id: str = Field(description="前端生成的稳定目标 ID。")
    kind: ConfigurationGoalKind = Field(description="attack 或 defense。")
    target_pokemon_id: int = Field(gt=0, description="目标或攻击来源 Pokémon ID。")
    move_id: int = Field(gt=0, description="本目标使用的招式 ID。")
    required_turns: int = Field(default=1, ge=1, le=10, description="击倒回合数或承受次数。")
    target_stat_preset: str = Field(default="no_investment", description="对手配置模板。")
    damage_roll_policy: DamageRollPolicy | None = Field(
        default=None,
        description="显式随机档口径；缺省时 attack=min、defense=max。",
    )


class SolveConfigurationRequest(BaseModel):
    """反向求解 Pokémon 合法配置的 HTTP 请求。"""

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    subject_pokemon_id: int = Field(gt=0, description="需要被配置的 Pokémon ID。")
    level: int = Field(default=50, ge=1, le=100, description="本次求解等级。")
    goals: list[ConfigurationGoalRequest] = Field(min_length=1, max_length=20)
    allowed_stat_presets: list[str] = Field(
        default_factory=list,
        description="允许搜索的配置模板；为空表示使用首版内置确定性模板。",
    )
    max_candidates: int = Field(default=3, ge=1, le=10, description="最多返回候选数。")


class SolverPokemonSummary(BaseModel):
    """求解结果中的 Pokémon 摘要。"""

    pokemon_id: int
    identifier: str
    display_name: str
    form_identifier: str | None
    sprite_url: str
    types: list[str]
    type_names: list[str]


class SolverMoveSummary(BaseModel):
    """求解结果中的招式摘要。"""

    move_id: int
    identifier: str
    display_name: str
    type: str
    type_name: str
    category: str
    power: int


class GoalVerificationResponse(BaseModel):
    """候选配置对单个目标的复核证据。"""

    goal_id: str
    kind: str
    satisfied: bool
    subject_role: str
    target: SolverPokemonSummary
    move: SolverMoveSummary
    roll_policy: str
    damage_min: int
    damage_max: int
    selected_damage: int
    repetitions: int
    total_damage: int
    hp_threshold: int
    remaining_hp: int
    effective_attack: int | None
    effective_defense: int | None


class SolvedConfigurationResponse(BaseModel):
    """一套满足全部目标的配置候选。"""

    stat_preset: str
    stat_preset_label: str
    stat_preset_assumption: str
    stats: dict[str, int]
    goals: list[GoalVerificationResponse]


class SolveConfigurationResponse(BaseModel):
    """反向配置求解 HTTP 响应。"""

    ruleset_id: str
    ruleset_name: str
    subject: SolverPokemonSummary
    level: int
    reachable: bool
    candidates: list[SolvedConfigurationResponse]
    rejected_goals: list[GoalVerificationResponse]
    scope: list[str]
    warnings: list[str]


def _pokemon_summary(
    result,
    *,
    ruleset_id: str,
) -> SolverPokemonSummary:
    """把 application Pokémon profile 转成前端摘要。"""
    return SolverPokemonSummary(
        pokemon_id=result.pokemon_id,
        identifier=result.identifier,
        display_name=result.display_name,
        form_identifier=result.form_identifier,
        sprite_url=_pokemon_sprite_url(ruleset_id=ruleset_id, pokemon_id=result.pokemon_id),
        types=[type_value.name.lower() for type_value in result.types],
        type_names=list(result.type_names),
    )


def _move_summary(result) -> SolverMoveSummary:
    """把 application move profile 转成前端摘要。"""
    return SolverMoveSummary(
        move_id=result.move_id,
        identifier=result.identifier,
        display_name=result.display_name,
        type=result.type.name.lower(),
        type_name=result.type_name,
        category=result.category.value,
        power=result.power,
    )


def _goal_response(
    result: ConfigurationGoalResult,
    *,
    ruleset_id: str,
) -> GoalVerificationResponse:
    """把单目标复核证据转成 HTTP schema。"""
    return GoalVerificationResponse(
        goal_id=result.goal_id,
        kind=result.kind.value,
        satisfied=result.satisfied,
        subject_role=result.subject_role,
        target=_pokemon_summary(result.target, ruleset_id=ruleset_id),
        move=_move_summary(result.move),
        roll_policy=result.roll_policy.value,
        damage_min=result.damage.min_damage,
        damage_max=result.damage.max_damage,
        selected_damage=result.selected_damage,
        repetitions=result.repetitions,
        total_damage=result.total_damage,
        hp_threshold=result.hp_threshold,
        remaining_hp=result.remaining_hp,
        effective_attack=result.effective_attack,
        effective_defense=result.effective_defense,
    )


def solve_configuration_response_from_result(
    result: SolvePokemonConfigurationResult,
) -> SolveConfigurationResponse:
    """把 application 求解结果转换成 HTTP 响应。"""
    return SolveConfigurationResponse(
        ruleset_id=result.ruleset.ruleset_id,
        ruleset_name=result.ruleset.ruleset_name,
        subject=_pokemon_summary(result.subject, ruleset_id=result.ruleset.ruleset_id),
        level=result.level,
        reachable=result.reachable,
        candidates=[
            SolvedConfigurationResponse(
                stat_preset=candidate.preset.key,
                stat_preset_label=candidate.preset.label,
                stat_preset_assumption=candidate.preset.assumption,
                stats=_stats_to_dict(candidate.stats),
                goals=[
                    _goal_response(goal, ruleset_id=result.ruleset.ruleset_id)
                    for goal in candidate.goal_results
                ],
            )
            for candidate in result.candidates
        ],
        rejected_goals=[
            _goal_response(goal, ruleset_id=result.ruleset.ruleset_id)
            for goal in result.rejected_goal_results
        ],
        scope=list(result.scope),
        warnings=list(result.warnings),
    )


__all__ = [
    "ConfigurationGoalRequest",
    "SolveConfigurationRequest",
    "SolveConfigurationResponse",
    "solve_configuration_response_from_result",
]
