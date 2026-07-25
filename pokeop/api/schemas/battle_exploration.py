"""定义战斗状态图渐进探索的稳定 HTTP 请求与响应合同。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from pokeop.api.schemas.inference import (
    BattleInferenceSummaryResponse,
    battle_inference_journey_response,
)
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationPathStep,
)
from pokeop.application.use_cases.battle_exploration import (
    BattleReport,
    BattleTransitionGroupOutcomesResult,
    BattleTransitionGroupsResult,
)
from pokeop.application.use_cases.store_battle_graph import (
    StoredFixedOneOnOneBattleResult,
)


class _AttributeResponseModel(BaseModel):
    """允许响应 DTO 直接从只读 application dataclass 投影字段。"""

    model_config = ConfigDict(from_attributes=True)


class ExactProbabilityResponse(_AttributeResponseModel):
    """同时返回 JavaScript 安全的精确分数和展示近似值。"""

    numerator: str
    denominator: str
    decimal: float
    percent: float


class ExplorationPathStepRequest(BaseModel):
    """表示前端 cursor 中一条真实选择边及其两端节点。"""

    source_node_id: int = Field(ge=0)
    edge_id: int = Field(ge=0)
    target_node_id: int = Field(ge=0)

    def to_application(self) -> ExplorationPathStep:
        """把 HTTP 步骤转换为 application 不可变路径步骤。

        Returns:
            保留 source、edge 和 target 三个稳定 ID 的 application DTO。
        """
        return ExplorationPathStep(
            source_node_id=self.source_node_id,
            edge_id=self.edge_id,
            target_node_id=self.target_node_id,
        )


class ExplorationCursorRequest(BaseModel):
    """只保存真实 edge 序列，不接受前端上传完整 BattleState。"""

    steps: list[ExplorationPathStepRequest] = Field(default_factory=list)

    def to_application(
        self,
        *,
        graph_id: str,
        root_node_id: int,
    ) -> ExplorationCursor:
        """结合服务端根节点重建 application cursor。

        Args:
            graph_id: URL 中指定、并已由 graph store 验证的稳定图标识。
            root_node_id: 服务端完整图的根节点 ID，不能由前端自行声明。

        Returns:
            允许合流和循环回边的不可变 application cursor。
        """
        return ExplorationCursor(
            graph_id=graph_id,
            root_node_id=root_node_id,
            steps=tuple(step.to_application() for step in self.steps),
        )


class ExplorationPathStepResponse(BaseModel):
    """返回 cursor 中一条经过 application 校验的真实路径步骤。"""

    source_node_id: int
    edge_id: int
    target_node_id: int


class ExplorationCursorResponse(BaseModel):
    """返回可原样提交给下一次探索请求的稳定 cursor。"""

    steps: list[ExplorationPathStepResponse]

    @classmethod
    def from_application(cls, cursor: ExplorationCursor) -> "ExplorationCursorResponse":
        """把 application cursor 投影为不重复携带 graph/root 的 HTTP DTO。

        Args:
            cursor: 已经过完整图连续性校验的真实边序列。

        Returns:
            只包含有序步骤、可与 URL graph ID 组合使用的响应游标。
        """
        return cls(
            steps=[
                ExplorationPathStepResponse(
                    source_node_id=int(step.source_node_id),
                    edge_id=int(step.edge_id),
                    target_node_id=int(step.target_node_id),
                )
                for step in cursor.steps
            ]
        )


class ExploreBattleGraphRequest(BaseModel):
    """请求读取根节点或 cursor 当前节点的折叠探索视图。"""

    calculation_revision: str = Field(min_length=1)
    cursor: ExplorationCursorRequest = Field(default_factory=ExplorationCursorRequest)


class AdvanceBattleExplorationRequest(ExploreBattleGraphRequest):
    """请求从 cursor 当前节点沿一条正式边前进一步。"""

    edge_id: int = Field(ge=0)


class BacktrackBattleExplorationRequest(ExploreBattleGraphRequest):
    """请求返回上一级，或截断到指定祖先深度。"""

    depth: int | None = Field(default=None, ge=0)


class MoveSlotDetailResponse(_AttributeResponseModel):
    """返回一个招式槽当前 PP、禁用和锁定状态。"""

    move_id: int
    current_pp: int
    max_pp: int
    disabled: bool
    locked: bool


class StatusDetailResponse(_AttributeResponseModel):
    """返回主状态或临时状态的显式可空字段。"""

    kind: str
    turns_asleep: int | None = None
    toxic_counter: int | None = None
    turns_remaining: int | None = None
    source_id: str | None = None


class StatStagesDetailResponse(_AttributeResponseModel):
    """返回七类能力等级的当前快照。"""

    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    accuracy: int
    evasion: int


class BattlerDetailResponse(_AttributeResponseModel):
    """返回一侧不泄漏 domain 对象的完整节点状态。"""

    pokemon_id: int
    name: str
    ability: str
    item: str
    current_hp: int
    max_hp: int
    moves: list[MoveSlotDetailResponse]
    major_status: StatusDetailResponse | None
    volatile_statuses: list[StatusDetailResponse]
    stat_stages: StatStagesDetailResponse
    last_move_id: int | None
    choice_lock_move_id: int | None
    item_consumed: bool
    first_turn: bool


class SideConditionsDetailResponse(_AttributeResponseModel):
    """返回一侧当前已经建模的屏障状态。"""

    reflect: bool
    light_screen: bool
    aurora_veil: bool


class BattleFieldDetailResponse(_AttributeResponseModel):
    """返回天气、场地和双方边侧状态。"""

    weather: str | None
    terrain: str | None
    attacker_side_conditions: SideConditionsDetailResponse
    defender_side_conditions: SideConditionsDetailResponse


class BattleNodeDetailResponse(_AttributeResponseModel):
    """返回 cursor 当前节点的完整 JSON 友好详情。"""

    node_id: int
    turn_number: int
    phase: str
    outcome: str
    termination_reason: str | None
    attacker: BattlerDetailResponse
    defender: BattlerDetailResponse
    field: BattleFieldDetailResponse
    terminal: bool
    has_outgoing_edges: bool


class RandomResultDetailResponse(_AttributeResponseModel):
    """返回一条原始随机事件的稳定来源、结果和值。"""

    event_type: str
    event_id: str
    outcome_id: str
    numeric_value: int | None


class BattleEventDetailResponse(_AttributeResponseModel):
    """返回一条不含 domain 对象引用的结构化战斗事实。"""

    kind: str
    turn_number: int
    actor: str | None
    target: str | None
    move_id: int | None
    source_identifier: str | None
    value: int | None
    before_value: int | None
    after_value: int | None


class DamageRandomMetadataResponse(_AttributeResponseModel):
    """返回伤害档原始值、最终伤害和实际 HP 损失。"""

    raw_roll_index: int
    raw_roll_value: int
    final_damage: int
    actual_hp_loss: int


class JointActionDetailResponse(_AttributeResponseModel):
    """返回联合行动中一侧选择的行动类型和招式 ID。"""

    side: str
    action_type: str
    move_id: int | None


class ActionResolutionDetailResponse(_AttributeResponseModel):
    """返回一侧行动的最终顺序、执行状态、命中与取消原因。"""

    side: str
    move_id: int | None
    action_type: str
    order_position: int | None
    status: str
    hit: bool | None
    reason: str | None


class StatusEffectSummaryResponse(_AttributeResponseModel):
    """返回状态施加或阻止的紧凑结构化摘要。"""

    result: str
    source_side: str | None
    target_side: str | None
    source_identifier: str | None


class CompactRandomResultResponse(_AttributeResponseModel):
    """返回等价随机路径归并后的离散结果摘要。"""

    target_node_id: int
    action_resolutions: list[ActionResolutionDetailResponse]
    order_reason: str
    critical_hit: bool | None
    raw_roll_values: list[int]
    final_damage_values: list[int]
    actual_hp_losses: list[int]
    status_effects: list[StatusEffectSummaryResponse]
    path_count: int


class TransitionEventPathDetailResponse(_AttributeResponseModel):
    """返回同一正式边保留的一条原始事件替代路径。"""

    random_results: list[RandomResultDetailResponse]
    damage_rolls: list[DamageRandomMetadataResponse]
    battle_events: list[BattleEventDetailResponse]


class TransitionLabelFieldsResponse(_AttributeResponseModel):
    """返回 presenter 生成分支标签所需的结构化字段。"""

    selected_move_ids: list[int]
    acting_sides: list[str]
    target_sides: list[str]
    result_keys: list[str]
    source_identifiers: list[str]


class TransitionOutcomeResponse(_AttributeResponseModel):
    """返回一个已经按后继状态归并的可选择结果。"""

    edge_id: int
    target_node_id: int
    probability: ExactProbabilityResponse
    joint_probability: ExactProbabilityResponse
    cumulative_probability: ExactProbabilityResponse
    label_fields: TransitionLabelFieldsResponse
    raw_random_values: list[int]
    random_results: list[RandomResultDetailResponse]
    damage_rolls: list[DamageRandomMetadataResponse]
    compact_results: list[CompactRandomResultResponse]
    battle_event_paths: list[list[BattleEventDetailResponse]]
    event_paths: list[TransitionEventPathDetailResponse]


class TransitionGroupSummaryResponse(_AttributeResponseModel):
    """返回收起分支组可直接展示的伤害与 HP 损失区间。"""

    minimum_damage: int | None
    maximum_damage: int | None
    minimum_hp_loss: int | None
    maximum_hp_loss: int | None


class TransitionGroupResponse(_AttributeResponseModel):
    """返回一个默认收起或按需展开的稳定分支组。"""

    group_id: str
    kind: str
    label_key: str
    probability: ExactProbabilityResponse
    selection_probability: ExactProbabilityResponse
    attacker_action: JointActionDetailResponse | None
    defender_action: JointActionDetailResponse | None
    raw_result_count: int
    distinct_outcome_count: int
    summary: TransitionGroupSummaryResponse
    expanded: bool
    outcomes: list[TransitionOutcomeResponse]


class BattleReportStepResponse(_AttributeResponseModel):
    """返回 cursor 中一条实际选择边对应的结构化战报步骤。"""

    depth: int
    source_node_id: int
    edge_id: int
    target_node_id: int
    edge_probability: ExactProbabilityResponse
    cumulative_probability: ExactProbabilityResponse
    event_paths: list[TransitionEventPathDetailResponse]


class BattleReportResponse(_AttributeResponseModel):
    """返回严格按 cursor edge 顺序生成的完整结构化战报。"""

    graph_id: str
    calculation_revision: str
    root_node_id: int
    current_node_id: int
    depth: int
    cumulative_probability: ExactProbabilityResponse
    steps: list[BattleReportStepResponse]


class StoredBattleExplorationResponse(BaseModel):
    """返回首次推演后可跨请求使用的图句柄和根 cursor。"""

    graph_id: str
    root_node_id: int
    calculation_revision: str
    expires_at: datetime
    cursor: ExplorationCursorResponse
    expandable: bool


class StoredBattleInferenceJourneyResponse(BaseModel):
    """返回完整全局 summary 和具备生命周期的 exploration handle。"""

    summary: BattleInferenceSummaryResponse
    exploration: StoredBattleExplorationResponse


class BattleGraphExplorationResponse(BaseModel):
    """返回 cursor 当前节点、折叠分组、概率、面包屑和结构化战报。"""

    graph_id: str
    calculation_revision: str
    cursor: ExplorationCursorResponse
    node: BattleNodeDetailResponse
    transition_groups: list[TransitionGroupResponse]
    cumulative_probability: ExactProbabilityResponse
    breadcrumbs: list[ExplorationPathStepResponse]
    battle_report: BattleReportResponse
    terminal: bool


class BattleTransitionGroupOutcomesResponse(BaseModel):
    """只返回调用方明确请求展开的当前节点分支组。"""

    graph_id: str
    calculation_revision: str
    cursor: ExplorationCursorResponse
    current_node_id: int
    cumulative_probability: ExactProbabilityResponse
    transition_group: TransitionGroupResponse


def stored_battle_inference_journey_response(
    stored: StoredFixedOneOnOneBattleResult,
) -> StoredBattleInferenceJourneyResponse:
    """把完成 store 接线的 application 结果投影为首次 HTTP 响应。

    Args:
        stored: 同时包含 summary、轻量 exploration 和真实 TTL 句柄的 application 结果。

    Returns:
        顶层保持 ``summary + exploration``，并提供空步骤根 cursor 与过期时间。
    """
    projected = battle_inference_journey_response(stored.result)
    return StoredBattleInferenceJourneyResponse(
        summary=projected.summary,
        exploration=StoredBattleExplorationResponse(
            graph_id=stored.handle.graph_id,
            root_node_id=stored.handle.root_node_id,
            calculation_revision=stored.handle.calculation_revision,
            expires_at=stored.handle.expires_at,
            cursor=ExplorationCursorResponse(steps=[]),
            expandable=stored.result.exploration.expandable,
        ),
    )


def battle_graph_exploration_response(
    result: BattleTransitionGroupsResult,
    report: BattleReport,
) -> BattleGraphExplorationResponse:
    """把折叠 group 查询与同 cursor 战报合并为一次探索响应。

    Args:
        result: application 已校验 cursor 后返回的节点位置和折叠分支组。
        report: application 严格按同一 cursor 构建的结构化战报。

    Returns:
        不读取完整图内部 nodes/edges 的 HTTP 探索 DTO。
    """
    cursor = ExplorationCursorResponse.from_application(result.position.cursor)
    return BattleGraphExplorationResponse(
        graph_id=result.position.graph_id,
        calculation_revision=result.position.calculation_revision,
        cursor=cursor,
        node=BattleNodeDetailResponse.model_validate(result.position.node),
        transition_groups=[
            TransitionGroupResponse.model_validate(group)
            for group in result.transition_groups
        ],
        cumulative_probability=ExactProbabilityResponse.model_validate(
            result.position.cumulative_probability
        ),
        breadcrumbs=list(cursor.steps),
        battle_report=BattleReportResponse.model_validate(report),
        terminal=result.position.node.terminal,
    )


def battle_transition_group_outcomes_response(
    result: BattleTransitionGroupOutcomesResult,
) -> BattleTransitionGroupOutcomesResponse:
    """把单个按需展开 group 投影为窄 HTTP 响应。

    Args:
        result: application 返回的当前节点位置和唯一目标分支组。

    Returns:
        不重复返回其他 groups、完整图或整份战报的展开结果。
    """
    return BattleTransitionGroupOutcomesResponse(
        graph_id=result.position.graph_id,
        calculation_revision=result.position.calculation_revision,
        cursor=ExplorationCursorResponse.from_application(result.position.cursor),
        current_node_id=result.position.node.node_id,
        cumulative_probability=ExactProbabilityResponse.model_validate(
            result.position.cumulative_probability
        ),
        transition_group=TransitionGroupResponse.model_validate(
            result.transition_group
        ),
    )


__all__ = [
    "AdvanceBattleExplorationRequest",
    "BacktrackBattleExplorationRequest",
    "BattleGraphExplorationResponse",
    "BattleTransitionGroupOutcomesResponse",
    "ExploreBattleGraphRequest",
    "ExplorationCursorRequest",
    "StoredBattleInferenceJourneyResponse",
    "battle_graph_exploration_response",
    "battle_transition_group_outcomes_response",
    "stored_battle_inference_journey_response",
]
