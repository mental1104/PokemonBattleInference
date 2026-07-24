"""定义按配置分组的胜利路径 Top-K HTTP 请求与响应合同。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pokeop.api.schemas.battle_exploration import (
    ExactProbabilityResponse,
    ExplorationPathStepResponse,
)
from pokeop.application.use_cases.winning_paths import WinningPathGroupsResult


class _AttributeResponseModel(BaseModel):
    """允许响应模型直接读取 application 不可变 dataclass 字段。"""

    model_config = ConfigDict(from_attributes=True)


class ListWinningPathGroupsRequest(BaseModel):
    """请求一个固定 graph 配置下指定获胜侧的分页路径组。"""

    calculation_revision: str = Field(min_length=1)
    winner: str = Field(pattern="^(attacker|defender)$")
    limit: int = Field(default=10, ge=1, le=100)
    cursor: str | None = None
    sort: str = Field(default="shortest-high-probability")


class WinningPathConfigurationSideResponse(_AttributeResponseModel):
    """返回配置身份中的一方 Pokémon、特性、道具和招式组。"""

    pokemon_id: int
    name: str
    level: int
    ability_identifier: str
    item_identifier: str
    move_ids: list[int]


class WinningPathConfigurationResponse(_AttributeResponseModel):
    """返回不会跨 graph 配置归并的稳定双方配置摘要。"""

    configuration_key: str
    attacker: WinningPathConfigurationSideResponse
    defender: WinningPathConfigurationSideResponse


class JointActionAlternativeResponse(_AttributeResponseModel):
    """返回一条原始解释中的双方联合行动。"""

    attacker_move_id: int | None
    defender_move_id: int | None
    attacker_source_identifier: str | None
    defender_source_identifier: str | None


class JointActionStepResponse(_AttributeResponseModel):
    """返回一个回合的联合行动主步骤及歧义候选。"""

    turn_number: int
    attacker_move_id: int | None
    defender_move_id: int | None
    attacker_source_identifier: str | None
    defender_source_identifier: str | None
    ambiguous: bool
    alternatives: list[JointActionAlternativeResponse]


class WinningPathKeyEventResponse(_AttributeResponseModel):
    """返回命中失败、行动阻断、机制触发、状态或濒死关键事件。"""

    kind: str
    actor: str | None
    target: str | None
    move_id: int | None
    source_identifier: str | None


class WinningPathGroupResponse(_AttributeResponseModel):
    """返回同一配置和行动序列归并后的一个胜利路径组。"""

    path_key: str
    terminal_turn: int
    probability: ExactProbabilityResponse
    raw_path_count: int
    raw_history_count_estimate: int
    terminal_reasons: list[str]
    terminal_node_ids: list[int]
    actions: list[JointActionStepResponse]
    representative_path: list[ExplorationPathStepResponse]
    damage_values: list[int]
    attacker_remaining_hp_values: list[int]
    defender_remaining_hp_values: list[int]
    key_events: list[WinningPathKeyEventResponse]


class WinningPathPrefixNodeResponse(_AttributeResponseModel):
    """返回当前页路径组构造的递归行动前缀树节点。"""

    prefix_key: str
    depth: int
    action: JointActionStepResponse | None
    probability: ExactProbabilityResponse
    raw_path_count: int
    terminal_path_keys: list[str]
    children: list["WinningPathPrefixNodeResponse"]


class WinningPathCycleReferenceResponse(_AttributeResponseModel):
    """返回被压缩为有限引用的回边或重复节点。"""

    source_node_id: int
    edge_id: int
    target_node_id: int
    prefix_depth: int
    component_id: int | None


class WinningPathGroupsResponse(_AttributeResponseModel):
    """返回胜利路径分页窗口、概率覆盖、前缀树与完整性语义。"""

    graph_id: str
    calculation_revision: str
    winner: str
    sort: str
    configuration: WinningPathConfigurationResponse
    winner_probability: ExactProbabilityResponse | None
    returned_probability: ExactProbabilityResponse
    returned_coverage: ExactProbabilityResponse | None
    path_groups: list[WinningPathGroupResponse]
    prefix_tree: WinningPathPrefixNodeResponse
    cycle_references: list[WinningPathCycleReferenceResponse]
    next_cursor: str | None
    has_more: bool
    query_complete: bool
    traversal_truncated: bool


def winning_path_groups_response(
    result: WinningPathGroupsResult,
) -> WinningPathGroupsResponse:
    """把 application 查询结果转换为不泄漏图对象的 HTTP DTO。

    Args:
        result: 已完成 graph、分页游标和概率校验的 application 结果。

    Returns:
        可由 FastAPI 直接序列化的稳定胜利路径响应。
    """
    return WinningPathGroupsResponse.model_validate(result)


__all__ = [
    "ListWinningPathGroupsRequest",
    "WinningPathGroupsResponse",
    "winning_path_groups_response",
]
