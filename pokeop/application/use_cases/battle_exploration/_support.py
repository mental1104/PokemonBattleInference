"""提供渐进探索 use cases 共用的图读取、游标校验与 lazy 分组投影。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256

from pokeop.application import state_graph_projection as projection
from pokeop.application.battle_graph_store import BattleGraphStore, StoredBattleGraph
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphError,
    StateGraphNode,
)
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationCursorError,
    ExplorationPathError,
    StateGraphExplorationUseCase,
)
from pokeop.application.state_graph_projection import (
    DamageRandomMetadata,
    ProbabilityProjection,
    TransitionGroup,
    TransitionGroupKind,
    TransitionGroupSummary,
)
from pokeop.application.use_cases.battle_exploration.errors import (
    BattleNodeNotFoundError,
    IncompatibleCalculationRevisionError,
    InvalidExplorationCursorError,
    TransitionGroupNotFoundError,
)
from pokeop.application.use_cases.battle_exploration.models import (
    BattleExplorationPosition,
)
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventType


@dataclass(frozen=True, slots=True)
class BattleExplorationContext:
    """保存一次 use case 调用读取到的图 artifact 与绑定 explorer。"""

    stored_graph: StoredBattleGraph
    explorer: StateGraphExplorationUseCase

    @property
    def graph(self) -> StateGraphBuildResult:
        """返回当前调用期间只读的完整状态图。"""
        return self.stored_graph.graph


@dataclass(frozen=True, slots=True)
class _TransitionGroupKey:
    """保存与 #58 分支组合同一致的机制类别和稳定来源判别键。"""

    kind: TransitionGroupKind
    discriminator: str


@dataclass(slots=True)
class _TransitionGroupAccumulator:
    """暂存当前 source node 中属于同一折叠组的正式图边。"""

    key: _TransitionGroupKey
    edges: list[StateGraphEdge]


def require_graph_store(graph_store: BattleGraphStore) -> None:
    """校验 use case 依赖满足 runtime-checkable store Protocol。

    Args:
        graph_store: 待注入的图存储实现。

    Raises:
        ValueError: 对象没有实现 ``put/get/delete`` 存储合同。
    """
    if not isinstance(graph_store, BattleGraphStore):
        raise ValueError("graph_store must implement BattleGraphStore")


def require_identifier(value: str, field_name: str) -> None:
    """拒绝非字符串、空值或携带首尾空白的稳定标识。

    Args:
        value: 待校验的标识值。
        field_name: 用于稳定错误消息的字段名。
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and normalized")


def load_context(
    graph_store: BattleGraphStore,
    *,
    graph_id: str,
    calculation_revision: str,
) -> BattleExplorationContext:
    """读取一份未过期图并绑定现有 edge-sequence explorer。

    Args:
        graph_store: application 定义的图存储端口。
        graph_id: 调用方请求读取的稳定图标识。
        calculation_revision: 调用方支持的精确计算语义版本。

    Returns:
        同时保存 ``StoredBattleGraph`` 和 cursor explorer 的调用上下文。

    Raises:
        BattleGraphNotFound: 图不存在时由 store 原样抛出。
        BattleGraphExpired: 图已过期时由 store 原样抛出。
        IncompatibleCalculationRevisionError: 请求版本与图版本不一致。
    """
    require_identifier(graph_id, "graph_id")
    require_identifier(calculation_revision, "calculation_revision")
    stored_graph = graph_store.get(graph_id)
    if stored_graph.calculation_revision != calculation_revision:
        raise IncompatibleCalculationRevisionError(
            graph_id,
            requested_revision=calculation_revision,
            stored_revision=stored_graph.calculation_revision,
        )
    try:
        explorer = StateGraphExplorationUseCase(
            graph_id=stored_graph.graph_id,
            graph=stored_graph.graph,
        )
    except ExplorationPathError as error:
        raise BattleNodeNotFoundError(
            graph_id,
            stored_graph.graph.root_node_id,
        ) from error
    return BattleExplorationContext(stored_graph=stored_graph, explorer=explorer)


def validate_cursor(
    context: BattleExplorationContext,
    cursor: ExplorationCursor,
) -> None:
    """把现有 cursor 合同异常收口为稳定 use case 异常。

    Args:
        context: 已完成 store 与版本校验的图上下文。
        cursor: 待验证的真实边序列。
    """
    try:
        context.explorer.validate(cursor)
    except ExplorationCursorError as error:
        raise InvalidExplorationCursorError(
            context.stored_graph.graph_id,
            str(error),
        ) from error


def current_node(
    context: BattleExplorationContext,
    cursor: ExplorationCursor,
) -> StateGraphNode:
    """读取合法 cursor 当前节点并保留 node-not-found 错误语义。"""
    validate_cursor(context, cursor)
    try:
        return context.graph.node(cursor.current_node_id)
    except StateGraphError as error:
        raise BattleNodeNotFoundError(
            context.stored_graph.graph_id,
            cursor.current_node_id,
        ) from error


def node_by_id(
    context: BattleExplorationContext,
    node_id: GraphNodeId,
) -> StateGraphNode:
    """按节点 ID 读取报告步骤的 source node。"""
    try:
        return context.graph.node(node_id)
    except StateGraphError as error:
        raise BattleNodeNotFoundError(
            context.stored_graph.graph_id,
            node_id,
        ) from error


def outgoing_edges(
    graph: StateGraphBuildResult,
    node_id: GraphNodeId,
) -> tuple[StateGraphEdge, ...]:
    """按完整图顺序读取指定 source node 的全部正式出边。"""
    return tuple(edge for edge in graph.edges if edge.source_node_id == node_id)


def position(
    context: BattleExplorationContext,
    cursor: ExplorationCursor,
) -> BattleExplorationPosition:
    """把合法 cursor 转换为节点详情和 JSON 安全概率投影。"""
    validate_cursor(context, cursor)
    node = current_node(context, cursor)
    edges = outgoing_edges(context.graph, node.node_id)
    return BattleExplorationPosition(
        graph_id=context.stored_graph.graph_id,
        calculation_revision=context.stored_graph.calculation_revision,
        cursor=cursor,
        node=projection._node_detail(node, has_outgoing_edges=bool(edges)),
        cumulative_probability=ProbabilityProjection.from_fraction(
            context.explorer.cumulative_probability(cursor)
        ),
    )


def list_group_summaries(
    node: StateGraphNode,
    edges: tuple[StateGraphEdge, ...],
) -> tuple[TransitionGroup, ...]:
    """复用联合行动投影，只构造默认折叠的 group 摘要。"""
    return projection._transition_groups(
        node=node,
        outgoing_edges=edges,
        cumulative_probability=Fraction(1, 1),
        expanded_group_ids=frozenset(),
    )


def expand_group(
    *,
    graph_id: str,
    node: StateGraphNode,
    edges: tuple[StateGraphEdge, ...],
    cumulative_probability: Fraction,
    group_id: str,
) -> TransitionGroup:
    """按稳定 group ID 展开一个联合行动的紧凑随机 outcomes。"""
    groups = projection._transition_groups(
        node=node,
        outgoing_edges=edges,
        cumulative_probability=cumulative_probability,
        expanded_group_ids=frozenset((group_id,)),
    )
    for group in groups:
        if group.group_id == group_id:
            return group
    raise TransitionGroupNotFoundError(graph_id, node.node_id, group_id)


def edge_by_id(
    context: BattleExplorationContext,
    edge_id: GraphEdgeId,
) -> StateGraphEdge:
    """读取已经由 cursor.validate 验证过的连续正式图边。"""
    index = int(edge_id)
    try:
        edge = context.graph.edges[index]
    except IndexError as error:
        raise InvalidExplorationCursorError(
            context.stored_graph.graph_id,
            f"edge_id {index} is outside the graph",
        ) from error
    if int(edge.edge_id) != index:
        raise InvalidExplorationCursorError(
            context.stored_graph.graph_id,
            f"graph edge index {index} contains edge_id {int(edge.edge_id)}",
        )
    return edge


def _group_accumulators(
    edges: tuple[StateGraphEdge, ...],
) -> tuple[_TransitionGroupAccumulator, ...]:
    """按 #58 首个真实分叉规则把当前节点出边稳定分组。"""
    if not edges:
        return ()
    selection_signatures = {
        _selection_signature(path)
        for edge in edges
        for path in edge.event_summary.paths
    }
    has_strategy_branch = len(selection_signatures) > 1
    accumulators: dict[_TransitionGroupKey, _TransitionGroupAccumulator] = {}
    for edge in edges:
        key = _group_key_for_edge(edge, has_strategy_branch=has_strategy_branch)
        accumulator = accumulators.get(key)
        if accumulator is None:
            accumulator = _TransitionGroupAccumulator(key=key, edges=[])
            accumulators[key] = accumulator
        accumulator.edges.append(edge)
    return tuple(accumulators.values())


def _group_summary_projection(
    node: StateGraphNode,
    accumulator: _TransitionGroupAccumulator,
) -> TransitionGroup:
    """从边概率和轻量伤害事实构造一个默认收起的 group。"""
    grouped_edges = tuple(
        sorted(accumulator.edges, key=lambda edge: int(edge.edge_id))
    )
    damage_rolls = _damage_rolls_for_edges(node, grouped_edges)
    return TransitionGroup(
        group_id=_group_id(node.node_id, accumulator.key),
        kind=accumulator.key.kind,
        label_key=_GROUP_LABEL_KEYS[accumulator.key.kind],
        probability=ProbabilityProjection.from_fraction(
            sum(
                (edge.probability for edge in grouped_edges),
                start=Fraction(0, 1),
            )
        ),
        raw_result_count=sum(
            len(edge.event_summary.paths) for edge in grouped_edges
        ),
        distinct_outcome_count=len(grouped_edges),
        summary=_damage_summary(damage_rolls),
        expanded=False,
        outcomes=(),
    )


def _damage_rolls_for_edges(
    node: StateGraphNode,
    edges: tuple[StateGraphEdge, ...],
) -> tuple[DamageRandomMetadata, ...]:
    """只读取 group 摘要所需的伤害档位与 HP loss，不创建 outcome DTO。"""
    metadata: list[DamageRandomMetadata] = []
    for edge in edges:
        for path in edge.event_summary.paths:
            random_events = tuple(
                event for event in path if not isinstance(event, BattleEvent)
            )
            battle_events = tuple(
                event for event in path if isinstance(event, BattleEvent)
            )
            # 复用 #58 唯一的伤害档/实际 HP loss 配对规则，避免摘要与展开漂移。
            metadata.extend(
                projection._damage_random_metadata(
                    node=node,
                    random_events=random_events,
                    battle_events=battle_events,
                )
            )
    return tuple(metadata)


def _damage_summary(
    damage_rolls: tuple[DamageRandomMetadata, ...],
) -> TransitionGroupSummary:
    """根据当前 group 的原始伤害路径生成最小/最大摘要。"""
    if not damage_rolls:
        return TransitionGroupSummary(None, None, None, None)
    damages = tuple(metadata.final_damage for metadata in damage_rolls)
    hp_losses = tuple(metadata.actual_hp_loss for metadata in damage_rolls)
    return TransitionGroupSummary(
        minimum_damage=min(damages),
        maximum_damage=max(damages),
        minimum_hp_loss=min(hp_losses),
        maximum_hp_loss=max(hp_losses),
    )


def _group_key_for_edge(
    edge: StateGraphEdge,
    *,
    has_strategy_branch: bool,
) -> _TransitionGroupKey:
    """选择策略分叉或每条路径最早的正式随机机制作为 group key。"""
    if has_strategy_branch:
        return _TransitionGroupKey(
            kind=TransitionGroupKind.ACTION_SELECTION,
            discriminator="policy-selection",
        )
    first_events = {
        first
        for path in edge.event_summary.paths
        if (first := _first_random_event(path)) is not None
    }
    if len(first_events) == 1:
        event_type, event_id = next(iter(first_events))
        return _TransitionGroupKey(
            kind=_group_kind_for_event_type(event_type),
            discriminator=event_id,
        )
    if first_events:
        discriminator = "|".join(
            f"{event_type.value}:{event_id}"
            for event_type, event_id in sorted(
                first_events,
                key=lambda value: (value[0].value, value[1]),
            )
        )
        return _TransitionGroupKey(TransitionGroupKind.COMPOSITE, discriminator)
    return _TransitionGroupKey(
        TransitionGroupKind.COMPOSITE,
        edge.source_key or "deterministic-transition",
    )


def _selection_signature(
    path: tuple[TransitionEvent, ...],
) -> tuple[tuple[str | None, int | None, str | None], ...]:
    """读取一条完整回合路径中双方稳定的选招组合。"""
    return tuple(
        (
            event.actor.value if event.actor is not None else None,
            event.move_id,
            event.source_identifier,
        )
        for event in path
        if isinstance(event, BattleEvent)
        and event.kind is BattleEventKind.MOVE_SELECTED
    )


def _first_random_event(
    path: tuple[TransitionEvent, ...],
) -> tuple[TransitionEventType, str] | None:
    """返回路径中首个非业务、非 CUSTOM 的随机机制及来源。"""
    for event in path:
        if isinstance(event, BattleEvent):
            continue
        if event.event_type is TransitionEventType.CUSTOM:
            continue
        return (event.event_type, event.event_id)
    return None


def _group_kind_for_event_type(
    event_type: TransitionEventType,
) -> TransitionGroupKind:
    """把 domain 随机事件类别显式映射为 application 分支组类别。"""
    match event_type:
        case TransitionEventType.SPEED_TIE:
            return TransitionGroupKind.ACTION_ORDER
        case TransitionEventType.HIT_CHECK:
            return TransitionGroupKind.HIT_CHECK
        case TransitionEventType.DAMAGE_ROLL:
            return TransitionGroupKind.DAMAGE_DISTRIBUTION
        case TransitionEventType.SECONDARY_EFFECT:
            return TransitionGroupKind.SECONDARY_EFFECT
        case TransitionEventType.CUSTOM:
            return TransitionGroupKind.COMPOSITE
    return TransitionGroupKind.COMPOSITE


def _group_id(node_id: GraphNodeId, key: _TransitionGroupKey) -> str:
    """生成与 #58 完全一致、绑定 source node 和机制来源的稳定 group ID。"""
    payload = f"{int(node_id)}|{key.kind.value}|{key.discriminator}"
    digest = sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"tg-{int(node_id)}-{key.kind.value}-{digest}"


_GROUP_LABEL_KEYS: dict[TransitionGroupKind, str] = {
    TransitionGroupKind.ACTION_SELECTION: "battle.transition.action-selection",
    TransitionGroupKind.ACTION_ORDER: "battle.transition.action-order",
    TransitionGroupKind.HIT_CHECK: "battle.transition.hit-check",
    TransitionGroupKind.DAMAGE_DISTRIBUTION: "battle.transition.damage-distribution",
    TransitionGroupKind.SECONDARY_EFFECT: "battle.transition.secondary-effect",
    TransitionGroupKind.COMPOSITE: "battle.transition.composite",
}

_GROUP_KIND_ORDER: dict[TransitionGroupKind, int] = {
    TransitionGroupKind.ACTION_SELECTION: 0,
    TransitionGroupKind.ACTION_ORDER: 1,
    TransitionGroupKind.HIT_CHECK: 2,
    TransitionGroupKind.DAMAGE_DISTRIBUTION: 3,
    TransitionGroupKind.SECONDARY_EFFECT: 4,
    TransitionGroupKind.COMPOSITE: 5,
}
