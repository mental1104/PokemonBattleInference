"""定义 1v1 战斗推演用户旅程的 HTTP 请求与响应模型。"""

from __future__ import annotations

from fractions import Fraction

from pydantic import BaseModel, Field

from pokeop.application.use_cases.infer_one_on_one_battle import (
    FixedOneOnOneBattleResult,
    PokemonConfigurationSummary,
    RepresentativeBattlePath,
)


class DragoniteWeavileJourneyRequest(BaseModel):
    """快龙 vs 玛纽拉受控用户旅程的输入。"""

    dragonite_ability: str = Field(
        default="multiscale",
        pattern="^(multiscale|inner-focus)$",
        description="快龙特性：多重鳞片或精神力。",
    )
    weavile_plan: str = Field(
        default="ice-punch",
        pattern="^(ice-punch|fake-out-pressure)$",
        description="玛纽拉行动方案：冰冻拳直攻，或击掌奇袭与冰冻拳等概率施压。",
    )
    dragonite_stat_preset: str = Field(
        default="max_atk_plus",
        description="快龙能力预设 key。",
    )
    weavile_stat_preset: str = Field(
        default="max_atk_plus",
        description="玛纽拉能力预设 key。",
    )


class ProbabilityResponse(BaseModel):
    """同时暴露 JavaScript 安全的精确分数和便于展示的小数概率。"""

    numerator: str
    denominator: str
    decimal: float
    percent: float


class ExpectedTurnsResponse(BaseModel):
    """表示有限期望回合数或不可有限表示的结果。"""

    available: bool
    numerator: int | None = None
    denominator: int | None = None
    decimal: float | None = None


class PokemonConfigurationResponse(BaseModel):
    """返回一侧完整固定配置的展示字段。"""

    pokemon_id: int
    name: str
    level: int
    ability_identifier: str
    item_identifier: str
    move_ids: list[int]
    move_names: list[str]
    stats: dict[str, int]
    dimension_labels: dict[str, str]


class GraphSummaryResponse(BaseModel):
    """返回完整状态图的规模、循环和截断诊断。"""

    unique_state_count: int
    edge_count: int
    max_turn_number: int
    closed_cycle_count: int
    terminal_reachable_cycle_count: int
    is_complete: bool
    truncation_reasons: list[str]


class RepresentativePathStepResponse(BaseModel):
    """返回代表路径中的一项状态节点快照。"""

    node_id: int
    turn_number: int
    phase: str
    attacker_hp: int
    defender_hp: int
    outcome: str
    events: list[str]


class RepresentativePathResponse(BaseModel):
    """返回一种终局语义的一条代表性路径。"""

    reference: str
    outcome: str
    steps: list[RepresentativePathStepResponse]


class BattleInferenceCompletenessResponse(BaseModel):
    """返回完整状态图构建和精确求解的可信度信息。"""

    graph_complete: bool
    solver_status: str
    truncation_reasons: list[str]
    diagnostics: list[str]
    warnings: list[str]


class BattleInferenceSummaryResponse(BaseModel):
    """返回与当前浏览路径无关的完整概率空间结论。"""

    ruleset_id: str
    version_group_id: int
    observer: str
    attacker: PokemonConfigurationResponse
    defender: PokemonConfigurationResponse
    win_probability: ProbabilityResponse
    loss_probability: ProbabilityResponse
    draw_probability: ProbabilityResponse
    expected_turns: ExpectedTurnsResponse
    attacker_policy: str
    defender_policy: str
    graph: GraphSummaryResponse
    representative_paths: list[RepresentativePathResponse]
    included_mechanisms: list[str]
    excluded_mechanisms: list[str]
    configuration_coverage_percent: float
    completeness: BattleInferenceCompletenessResponse


class BattleExplorationResponse(BaseModel):
    """返回后续节点探索所需的稳定入口，不序列化 application 图对象。"""

    root_node_id: int
    graph_id: str | None
    calculation_revision: str
    expandable: bool


class BattleInferenceJourneyResponse(BaseModel):
    """冻结 summary 与 exploration 两个职责不同的顶层响应。"""

    summary: BattleInferenceSummaryResponse
    exploration: BattleExplorationResponse


def _probability(value: Fraction) -> ProbabilityResponse:
    """把精确 Fraction 转换为 API 概率 DTO。

    Args:
        value: 闭区间 [0, 1] 内的精确概率。

    Returns:
        分子分母使用字符串，同时包含小数和百分比近似值的响应对象。
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
    """把 application 配置摘要转换为 HTTP 响应。

    Args:
        summary: 一侧固定配置的稳定 application DTO。

    Returns:
        不暴露 domain 对象的 JSON 友好响应。
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


def _path(path: RepresentativeBattlePath) -> RepresentativePathResponse:
    """把一条 application 代表路径转换为轻量 HTTP 路径。

    Args:
        path: 已通过图前驱索引重建的代表路径。

    Returns:
        包含节点 HP、回合、终局和事件摘要的响应。
    """
    return RepresentativePathResponse(
        reference=path.reference,
        outcome=path.outcome.value,
        steps=[
            RepresentativePathStepResponse(
                node_id=step.node_id,
                turn_number=step.turn_number,
                phase=step.phase,
                attacker_hp=step.attacker_hp,
                defender_hp=step.defender_hp,
                outcome=step.outcome,
                events=list(step.events),
            )
            for step in path.steps
        ],
    )


def battle_inference_journey_response(
    result: FixedOneOnOneBattleResult,
) -> BattleInferenceJourneyResponse:
    """把 application 顶层合同投影为 summary 与 exploration HTTP DTO。

    Args:
        result: 同时保留完整图 artifact 和全局推演结论的 application 结果。

    Returns:
        不泄漏 domain/solver 图对象，且代表路径与探索入口明确分离的响应。
    """
    summary = result.summary
    inference = summary.inference
    expected = inference.expected_turns
    warnings = [
        f"未纳入机制：{identifier}"
        for identifier in inference.mechanism_coverage.excluded
    ]
    warnings.extend(summary.completeness.diagnostics)
    graph_statistics = summary.graph_statistics
    completeness = summary.completeness
    return BattleInferenceJourneyResponse(
        summary=BattleInferenceSummaryResponse(
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
                unique_state_count=graph_statistics.unique_state_count,
                edge_count=graph_statistics.edge_count,
                max_turn_number=graph_statistics.max_turn_number,
                closed_cycle_count=graph_statistics.closed_cycle_count,
                terminal_reachable_cycle_count=(
                    graph_statistics.terminal_reachable_cycle_count
                ),
                is_complete=graph_statistics.is_complete,
                truncation_reasons=list(graph_statistics.truncation_reasons),
            ),
            representative_paths=[
                _path(path) for path in summary.representative_paths
            ],
            included_mechanisms=list(
                inference.mechanism_coverage.included
            ),
            excluded_mechanisms=list(
                inference.mechanism_coverage.excluded
            ),
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
        ),
        exploration=BattleExplorationResponse(
            root_node_id=result.exploration.root_node_id,
            graph_id=result.exploration.graph_handle,
            calculation_revision=result.exploration.calculation_revision,
            expandable=result.exploration.expandable,
        ),
    )


__all__ = [
    "BattleExplorationResponse",
    "BattleInferenceJourneyResponse",
    "BattleInferenceSummaryResponse",
    "DragoniteWeavileJourneyRequest",
    "battle_inference_journey_response",
]
