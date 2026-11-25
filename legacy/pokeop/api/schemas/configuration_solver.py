from __future__ import annotations

from pydantic import BaseModel, Field

from pokeop.api.schemas.calculator import _pokemon_sprite_url, _stats_to_dict
from pokeop.application.use_cases.search_configuration_spreads import (
    SearchPokemonStatSpreadsResult,
    StatSpreadRange,
)
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
    target_ability_identifier: str = Field(
        min_length=1,
        description="目标 Pokémon 当前选择的合法特性 identifier。",
    )
    target_item_identifier: str | None = Field(
        default=None,
        description="目标 Pokémon 当前选择的已实现持有道具 identifier。",
    )
    target_stat_preset: str = Field(default="no_investment", description="对手配置模板。")
    damage_roll_policy: DamageRollPolicy | None = Field(
        default=None,
        description="显式随机档口径；缺省时 attack=min、defense=max。",
    )


class SolveConfigurationRequest(BaseModel):
    """从已有配置模板中搜索可达候选的 HTTP 请求。"""

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    subject_pokemon_id: int = Field(gt=0, description="需要被配置的 Pokémon ID。")
    subject_ability_identifier: str = Field(
        min_length=1,
        description="待配置 Pokémon 当前选择的合法特性 identifier。",
    )
    subject_item_identifier: str | None = Field(
        default=None,
        description="待配置 Pokémon 当前选择的已实现持有道具 identifier。",
    )
    level: int = Field(default=50, ge=1, le=100, description="本次求解等级。")
    goals: list[ConfigurationGoalRequest] = Field(min_length=1, max_length=20)
    allowed_stat_presets: list[str] = Field(
        default_factory=list,
        description="允许搜索的配置模板；为空表示使用首版内置确定性模板。",
    )
    max_candidates: int = Field(default=3, ge=1, le=10, description="最多返回候选数。")


class SearchConfigurationSpreadsRequest(BaseModel):
    """根据多目标直接反推 EV、IV 与性格的 HTTP 请求。

    与模板求解不同，本请求只固定待配置 Pokémon、特性、道具和等级；服务端在合法
    EV 单项/总量约束内搜索代表分配，并默认最多返回十条按 EV 成本排序的区间候选。
    """

    ruleset_id: str = Field(default="pokemon-champion", description="当前规则集标识。")
    subject_pokemon_id: int = Field(gt=0, description="需要被反推配置的 Pokémon ID。")
    subject_ability_identifier: str = Field(
        min_length=1,
        description="待配置 Pokémon 当前固定选择的合法特性 identifier。",
    )
    subject_item_identifier: str | None = Field(
        default=None,
        description="待配置 Pokémon 当前固定选择的已实现持有道具 identifier。",
    )
    level: int = Field(default=50, ge=1, le=100, description="本次反推等级。")
    goals: list[ConfigurationGoalRequest] = Field(min_length=1, max_length=20)
    max_candidates: int = Field(
        default=10,
        ge=1,
        le=10,
        description="最多返回多少条 EV/IV/性格候选。",
    )


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


class StatValueRangeResponse(BaseModel):
    """单项 EV 或 IV 在其余字段固定时的独立安全区间。"""

    minimum: int
    maximum: int


class StatSpreadRangeResponse(BaseModel):
    """六项 EV 或 IV 独立安全区间。"""

    hp: StatValueRangeResponse
    attack: StatValueRangeResponse
    defense: StatValueRangeResponse
    special_attack: StatValueRangeResponse
    special_defense: StatValueRangeResponse
    speed: StatValueRangeResponse


class NatureOptionResponse(BaseModel):
    """对当前目标等价可选的一项性格。"""

    identifier: str
    label: str


class SolvedConfigurationResponse(BaseModel):
    """一套满足全部目标的模板候选或属性反推候选。"""

    stat_preset: str
    stat_preset_label: str
    stat_preset_assumption: str
    stats: dict[str, int]
    goals: list[GoalVerificationResponse]
    solution_kind: str = "preset"
    nature_id: str | None = None
    nature_label: str | None = None
    nature_options: list[NatureOptionResponse] = Field(default_factory=list)
    evs: dict[str, int] | None = None
    ivs: dict[str, int] | None = None
    ev_ranges: StatSpreadRangeResponse | None = None
    iv_ranges: StatSpreadRangeResponse | None = None


class SolveConfigurationResponse(BaseModel):
    """模板搜索或属性反推共用的 HTTP 响应。"""

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
    """把 application Pokémon profile 转成前端摘要。

    Args:
        result: application 层 Pokémon profile。
        ruleset_id: 用于生成当前规则集 sprite 地址的稳定标识。

    Returns:
        仅包含页面展示字段的 Pokémon 摘要。
    """
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
    """把 application move profile 转成前端摘要。

    Args:
        result: application 层固定威力招式 profile。

    Returns:
        包含本地化名称、属性、分类和威力的招式摘要。
    """
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
    """把单目标复核证据转成 HTTP schema。

    Args:
        result: application 返回的单目标伤害与满足状态。
        ruleset_id: 生成目标 Pokémon sprite 地址所需的规则集标识。

    Returns:
        前端可以直接展示的目标复核结构。
    """
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


def _range_response(result: StatSpreadRange) -> StatSpreadRangeResponse:
    """把 application 六项范围对象转换成 API schema。

    Args:
        result: 六项能力各自的独立安全区间。

    Returns:
        字段名稳定的六项范围响应。
    """
    return StatSpreadRangeResponse(
        hp=StatValueRangeResponse(
            minimum=result.hp.minimum,
            maximum=result.hp.maximum,
        ),
        attack=StatValueRangeResponse(
            minimum=result.attack.minimum,
            maximum=result.attack.maximum,
        ),
        defense=StatValueRangeResponse(
            minimum=result.defense.minimum,
            maximum=result.defense.maximum,
        ),
        special_attack=StatValueRangeResponse(
            minimum=result.special_attack.minimum,
            maximum=result.special_attack.maximum,
        ),
        special_defense=StatValueRangeResponse(
            minimum=result.special_defense.minimum,
            maximum=result.special_defense.maximum,
        ),
        speed=StatValueRangeResponse(
            minimum=result.speed.minimum,
            maximum=result.speed.maximum,
        ),
    )


def solve_configuration_response_from_result(
    result: SolvePokemonConfigurationResult,
) -> SolveConfigurationResponse:
    """把已有模板求解结果转换成共用 HTTP 响应。

    Args:
        result: application 层模板候选求解结果。

    Returns:
        solution_kind 为 preset 的响应，新增反推字段保持空值。
    """
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


def search_configuration_spreads_response_from_result(
    result: SearchPokemonStatSpreadsResult,
) -> SolveConfigurationResponse:
    """把 EV、IV 与性格反推结果转换成共用 HTTP 响应。

    Args:
        result: application 层属性反推结果，候选已经包含代表值和独立安全区间。

    Returns:
        solution_kind 为 spread 的响应，可直接用于结果卡片和专属配置保存。
    """
    return SolveConfigurationResponse(
        ruleset_id=result.ruleset.ruleset_id,
        ruleset_name=result.ruleset.ruleset_name,
        subject=_pokemon_summary(result.subject, ruleset_id=result.ruleset.ruleset_id),
        level=result.level,
        reachable=result.reachable,
        candidates=[
            SolvedConfigurationResponse(
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
    "SearchConfigurationSpreadsRequest",
    "SolveConfigurationRequest",
    "SolveConfigurationResponse",
    "search_configuration_spreads_response_from_result",
    "solve_configuration_response_from_result",
]
