"""定义技能组合预览和固定配置精确摘要的 HTTP DTO。"""

from __future__ import annotations

from fractions import Fraction
from typing import Literal

from pydantic import BaseModel, Field

from pokeop.api.schemas.inference import (
    BattleInferenceCompletenessResponse,
    BattleInferenceSummaryResponse,
    ExpectedTurnsResponse,
    GraphSummaryResponse,
    PokemonConfigurationResponse,
    ProbabilityResponse,
)
from pokeop.api.schemas.battle_exploration import ExplorationCursorRequest
from pokeop.application.use_cases.fixed_battle_workflow import (
    EnumerateMoveSetCombinationsResult,
    FixedBattleSideSelection,
    FixedBattleSummaryResult,
    MoveSetOption,
    MoveSetSideResult,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    PokemonConfigurationSummary,
)


class FixedBattleSideRequest(BaseModel):
    """保存组合枚举与固定推演共享的一侧非招式配置。"""

    pokemon_id: int = Field(gt=0)
    form_id: int | None = Field(default=None, gt=0)
    level: int = Field(default=50, ge=1, le=100)
    stat_profile_id: str = Field(min_length=1)
    ability_identifier: str = Field(min_length=1)
    item_identifier: str | None = Field(default=None, min_length=1)

    def to_application(self) -> FixedBattleSideSelection:
        """转换为 application 固定配置值对象。

        Returns:
            经过 application 层再次校验的不可变固定配置。
        """
        return FixedBattleSideSelection(
            pokemon_id=self.pokemon_id,
            form_id=self.form_id,
            level=self.level,
            stat_profile_id=self.stat_profile_id,
            ability_identifier=self.ability_identifier,
            item_identifier=self.item_identifier,
        )


class MoveSetCombinationSideRequest(FixedBattleSideRequest):
    """声明一侧希望枚举为一到四招技能组的候选池。"""

    candidate_move_ids: list[int] = Field(min_length=1, max_length=10)


class MoveSetCombinationsRequest(BaseModel):
    """声明只生成组合、不启动状态图计算的 HTTP 请求。"""

    ruleset_id: str = Field(default="pokemon-champion", min_length=1)
    version_group_id: int = Field(default=25, gt=0)
    calculation_revision: str = Field(min_length=1)
    attacker: MoveSetCombinationSideRequest
    defender: MoveSetCombinationSideRequest


class MoveSetOptionResponse(BaseModel):
    """返回一个稳定技能组 ID、招式 ID 和展示名称。"""

    move_set_id: str
    move_ids: list[int]
    move_names: list[str]


class MoveSetSideResponse(BaseModel):
    """返回一侧全部可选技能组及候选数量。"""

    pokemon_id: int
    pokemon_name: str
    candidate_count: int
    move_set_count: int
    move_sets: list[MoveSetOptionResponse]


class MoveSetCombinationsResponse(BaseModel):
    """返回双方独立技能组与理论配置对数量。"""

    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    attacker: MoveSetSideResponse
    defender: MoveSetSideResponse
    configuration_pair_count: int


class FixedBattleChosenSideRequest(FixedBattleSideRequest):
    """声明用户从组合列表中选定的一侧固定技能组。"""

    move_ids: list[int] = Field(min_length=1, max_length=4)


class FixedBattleGraphLimitsRequest(BaseModel):
    """限制一个固定配置精确求解允许消耗的图规模。"""

    max_nodes: int = Field(default=50_000, gt=0, le=500_000)
    max_edges: int = Field(default=300_000, gt=0, le=2_000_000)
    max_turns: int = Field(default=20, gt=0, le=200)


class FixedBattleSummaryRequest(BaseModel):
    """声明一次只针对一个双方固定配置的精确概率推演。"""

    ruleset_id: str = Field(default="pokemon-champion", min_length=1)
    version_group_id: int = Field(default=25, gt=0)
    attacker: FixedBattleChosenSideRequest
    defender: FixedBattleChosenSideRequest
    attacker_policy: Literal["uniform-random", "first-legal"] = "uniform-random"
    defender_policy: Literal["uniform-random", "first-legal"] = "uniform-random"
    limits: FixedBattleGraphLimitsRequest = Field(
        default_factory=FixedBattleGraphLimitsRequest
    )


class FixedBattleSnapshotStepRequest(FixedBattleSummaryRequest):
    """声明按当前路径快照展开下一层可能性的请求。"""

    cursor: ExplorationCursorRequest = Field(default_factory=ExplorationCursorRequest)


class FixedBattleJobLinksResponse(BaseModel):
    """返回固定任务后续轮询和取消使用的稳定链接。"""

    self: str
    cancel: str


class CreateFixedBattleJobResponse(BaseModel):
    """返回固定配置异步任务提交确认。"""

    job_id: str
    job_type: Literal["fixed-one-on-one"] = "fixed-one-on-one"
    status: str
    phase: Literal["queued"] = "queued"
    created_at: str
    submitted_configuration_pairs: int
    links: FixedBattleJobLinksResponse


def _move_set_option_response(option: MoveSetOption) -> MoveSetOptionResponse:
    """把 application 技能组投影为 JSON 友好响应。

    Args:
        option: 已规范化且包含展示名称的技能组。

    Returns:
        使用可变 JSON 数组表达 ID 与名称的响应对象。
    """
    return MoveSetOptionResponse(
        move_set_id=option.move_set_id,
        move_ids=list(option.move_ids),
        move_names=list(option.move_names),
    )


def _side_response(result: MoveSetSideResult) -> MoveSetSideResponse:
    """把一侧组合结果投影为 HTTP 响应。

    Args:
        result: 一侧完整候选计数和技能组列表。

    Returns:
        不包含对手或配置对执行记录的一侧响应。
    """
    return MoveSetSideResponse(
        pokemon_id=result.pokemon_id,
        pokemon_name=result.pokemon_name,
        candidate_count=result.candidate_count,
        move_set_count=result.move_set_count,
        move_sets=[_move_set_option_response(item) for item in result.move_sets],
    )


def move_set_combinations_response(
    result: EnumerateMoveSetCombinationsResult,
) -> MoveSetCombinationsResponse:
    """把组合枚举 application 结果转换为 HTTP DTO。

    Args:
        result: 已完成合法性与机制准入的双方技能组结果。

    Returns:
        不包含任何状态图、任务 ID 或配置对明细的轻量响应。
    """
    return MoveSetCombinationsResponse(
        ruleset_id=result.ruleset_id,
        version_group_id=result.version_group_id,
        calculation_revision=result.calculation_revision,
        attacker=_side_response(result.attacker),
        defender=_side_response(result.defender),
        configuration_pair_count=result.configuration_pair_count,
    )


def _probability(value: Fraction) -> ProbabilityResponse:
    """把精确概率转换为 JavaScript 安全的字符串分数。

    Args:
        value: 闭区间 [0, 1] 内的精确概率。

    Returns:
        同时包含字符串分数与展示近似值的响应对象。
    """
    decimal = float(value)
    return ProbabilityResponse(
        numerator=str(value.numerator),
        denominator=str(value.denominator),
        decimal=decimal,
        percent=decimal * 100,
    )


def _pokemon(
    summary: PokemonConfigurationSummary,
) -> PokemonConfigurationResponse:
    """把 application 一侧固定配置转换为展示 DTO。

    Args:
        summary: 已经由固定配置生成器还原能力值和技能名称的摘要。

    Returns:
        不暴露 domain 或 persistence 对象的 HTTP 响应。
    """
    return PokemonConfigurationResponse(
        pokemon_id=summary.pokemon_id,
        name=summary.name,
        level=summary.level,
        ability_identifier=summary.ability_identifier,
        item_identifier=summary.item_identifier,
        move_ids=list(summary.move_ids),
        move_names=list(summary.move_names),
        stats={
            "hp": summary.hp,
            "attack": summary.attack,
            "defense": summary.defense,
            "special_attack": summary.special_attack,
            "special_defense": summary.special_defense,
            "speed": summary.speed,
        },
        dimension_labels=dict(summary.dimension_labels),
    )


def fixed_battle_summary_response(
    result: FixedBattleSummaryResult,
) -> BattleInferenceSummaryResponse:
    """把无探索图的固定配置精确摘要转换为现有 summary 响应。

    Args:
        result: 只持有精确概率、机制覆盖和紧凑图统计的 application 结果。

    Returns:
        ``representative_paths`` 固定为空的全局推演摘要；调用方不会获得 graph ID。
    """
    summary = result.summary
    inference = summary.inference
    expected = inference.expected_turns
    graph = summary.graph_statistics
    completeness = summary.completeness
    warnings = [
        f"未纳入机制：{identifier}"
        for identifier in inference.mechanism_coverage.excluded
    ]
    warnings.extend(completeness.diagnostics)
    return BattleInferenceSummaryResponse(
        ruleset_id=inference.rules.ruleset_id,
        version_group_id=inference.rules.version_group_id,
        observer=inference.observer.value,
        attacker=_pokemon(summary.configuration.attacker),
        defender=_pokemon(summary.configuration.defender),
        win_probability=_probability(inference.win_probability.value),
        loss_probability=_probability(inference.loss_probability.value),
        draw_probability=_probability(inference.draw_probability.value),
        expected_turns=ExpectedTurnsResponse(
            available=expected is not None,
            numerator=expected.numerator if expected is not None else None,
            denominator=expected.denominator if expected is not None else None,
            decimal=float(expected) if expected is not None else None,
        ),
        attacker_policy=inference.attacker_policy.policy_id,
        defender_policy=inference.defender_policy.policy_id,
        graph=GraphSummaryResponse(
            unique_state_count=graph.unique_state_count,
            edge_count=graph.edge_count,
            max_turn_number=graph.max_turn_number,
            closed_cycle_count=graph.closed_cycle_count,
            terminal_reachable_cycle_count=graph.terminal_reachable_cycle_count,
            is_complete=graph.is_complete,
            truncation_reasons=list(graph.truncation_reasons),
        ),
        representative_paths=[],
        included_mechanisms=list(inference.mechanism_coverage.included),
        excluded_mechanisms=list(inference.mechanism_coverage.excluded),
        configuration_coverage_percent=(
            float(inference.configuration_coverage.coverage_ratio) * 100
        ),
        completeness=BattleInferenceCompletenessResponse(
            graph_complete=completeness.graph_complete,
            solver_status=completeness.solver_status,
            truncation_reasons=list(completeness.truncation_reasons),
            diagnostics=list(completeness.diagnostics),
            warnings=warnings,
        ),
    )


__all__ = [
    "CreateFixedBattleJobResponse",
    "FixedBattleSnapshotStepRequest",
    "FixedBattleSummaryRequest",
    "MoveSetCombinationsRequest",
    "MoveSetCombinationsResponse",
    "fixed_battle_summary_response",
    "move_set_combinations_response",
]
