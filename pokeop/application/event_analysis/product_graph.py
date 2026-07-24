"""构建不修改基础状态键的有限事件历史乘积图。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import cast

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    BattleGraphSolveStatus,
)
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
    StrongComponent,
    StrongComponentKind,
)
from pokeop.application.solver.strong_components import analyze_strong_components
from pokeop.domain.battle.state import StateKey
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
)

from .query import (
    BattleEventAnalysisError,
    BattleEventQuery,
    EventOccurrenceMode,
    EventTurnRange,
)


@dataclass(frozen=True, slots=True)
class _EventTracker:
    """保存分析产品自动机状态，不写入基础战斗 ``StateKey``。

    Args:
        original_node_id: 当前对应的原图节点。
        occurrence_count_bucket: 已匹配事件次数或饱和次数桶。
        first_occurrence_turn_bucket: 首次匹配回合或饱和回合桶。
        matched_in_range: 是否已有任意匹配落入查询回合范围。
        next_turn_bucket: 下一条完整回合边使用的回合号或饱和桶。
    """

    original_node_id: GraphNodeId
    occurrence_count_bucket: int
    first_occurrence_turn_bucket: int | None
    matched_in_range: bool
    next_turn_bucket: int


@dataclass(frozen=True, slots=True)
class _EventProductGraph:
    """保存事件历史乘积图和每个产品节点对应的自动机状态。

    Args:
        graph: 可由现有精确图求解器直接消费的产品图。
        trackers: 与连续产品节点 ID 一一对应的事件自动机状态。
        count_overflow_bucket: 表示大于等于该值的次数饱和桶。
        turn_overflow_bucket: 表示大于等于该值的回合饱和桶。
    """

    graph: StateGraphBuildResult
    trackers: tuple[_EventTracker, ...]
    count_overflow_bucket: int
    turn_overflow_bucket: int


def _require_solved(label: str, result: BattleGraphSolveResult) -> None:
    """拒绝不完整、资源受限或奇异方程结果。

    Args:
        label: 用于错误消息区分基线、产品图或属性求解阶段的稳定标签。
        result: 现有精确图求解器返回的结果。

    Raises:
        BattleEventAnalysisError: 求解状态不是 ``SOLVED``。
    """
    if result.status is BattleGraphSolveStatus.SOLVED:
        return
    diagnostics = "; ".join(result.diagnostics) or result.status.value
    raise BattleEventAnalysisError(
        f"{label} graph is not exactly solved: {diagnostics}"
    )


def _required_probability(label: str, probability: Fraction | None) -> Fraction:
    """读取已求解结果中的必需概率字段。

    Args:
        label: 缺失字段的稳定诊断标签。
        probability: 求解器返回的可空精确概率。

    Returns:
        非空 ``Fraction`` 概率。

    Raises:
        BattleEventAnalysisError: 已求解结果仍缺少对应概率。
    """
    if not isinstance(probability, Fraction):
        raise BattleEventAnalysisError(f"{label} probability is unavailable")
    return probability


def _build_event_product_graph(
    graph: StateGraphBuildResult,
    query: BattleEventQuery,
) -> _EventProductGraph:
    """把原图与有限事件历史自动机做乘积，不修改基础 ``StateKey``。

    Args:
        graph: 已构建并完成 SCC 分类的原始战斗状态图。
        query: 决定计数、首次回合和范围标记的事件查询。

    Returns:
        可被现有精确求解器消费的有限产品图及自动机状态表。
    """
    if not graph.is_complete:
        raise BattleEventAnalysisError("event analysis requires a complete state graph")
    if any(node.outcome is GraphNodeOutcome.UNKNOWN for node in graph.nodes):
        raise BattleEventAnalysisError(
            "event analysis cannot consume unknown graph nodes"
        )

    count_overflow = max(
        query.distribution_count_limit,
        query.min_occurrences,
        query.max_occurrences or 0,
    ) + 1
    root_turn = graph.node(graph.root_node_id).state.turn_number
    turn_bound_candidates = [query.distribution_turn_limit, root_turn]
    if query.turn_range is not None:
        if query.turn_range.start_turn is not None:
            turn_bound_candidates.append(query.turn_range.start_turn)
        if query.turn_range.end_turn is not None:
            turn_bound_candidates.append(query.turn_range.end_turn)
    turn_overflow = max(turn_bound_candidates) + 1

    root_tracker = _EventTracker(
        original_node_id=graph.root_node_id,
        occurrence_count_bucket=0,
        first_occurrence_turn_bucket=None,
        matched_in_range=False,
        next_turn_bucket=min(root_turn, turn_overflow),
    )
    trackers: list[_EventTracker] = [root_tracker]
    nodes: list[StateGraphNode] = [
        _product_node(GraphNodeId(0), root_tracker, graph)
    ]
    edges: list[StateGraphEdge] = []
    node_ids_by_tracker: dict[_EventTracker, GraphNodeId] = {
        root_tracker: GraphNodeId(0)
    }
    outgoing = _outgoing_edges(graph)
    work_queue: deque[GraphNodeId] = deque((GraphNodeId(0),))

    while work_queue:
        product_node_id = work_queue.popleft()
        tracker = trackers[int(product_node_id)]
        original_node = graph.node(tracker.original_node_id)
        if original_node.is_terminal:
            continue
        original_edges = outgoing[int(tracker.original_node_id)]
        if not original_edges:
            raise BattleEventAnalysisError(
                "non-terminal original node "
                f"{int(tracker.original_node_id)} has no edges"
            )

        for original_edge in original_edges:
            for path_probability, path in original_edge.event_summary.weighted_paths:
                next_tracker = _advance_tracker(
                    tracker,
                    original_edge.target_node_id,
                    path,
                    query,
                    count_overflow,
                    turn_overflow,
                )
                target_product_node_id = node_ids_by_tracker.get(next_tracker)
                edge_id = GraphEdgeId(len(edges))
                if target_product_node_id is None:
                    target_product_node_id = GraphNodeId(len(nodes))
                    node_ids_by_tracker[next_tracker] = target_product_node_id
                    trackers.append(next_tracker)
                    nodes.append(
                        _product_node(target_product_node_id, next_tracker, graph)
                    )
                    work_queue.append(target_product_node_id)
                edges.append(
                    StateGraphEdge(
                        edge_id=edge_id,
                        source_node_id=product_node_id,
                        target_node_id=target_product_node_id,
                        probability=original_edge.probability * path_probability,
                        event_summary=TransitionEventSummary(
                            (path,),
                            (Fraction(1),),
                        ),
                        source_key=original_edge.source_key,
                    )
                )

    components = analyze_strong_components(nodes, edges)
    statistics = _product_statistics(nodes, edges, components)
    product_graph = StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=tuple(nodes),
        edges=tuple(edges),
        components=components,
        statistics=statistics,
        truncation_reasons=(),
    )
    return _EventProductGraph(
        graph=product_graph,
        trackers=tuple(trackers),
        count_overflow_bucket=count_overflow,
        turn_overflow_bucket=turn_overflow,
    )


def _product_node(
    product_node_id: GraphNodeId,
    tracker: _EventTracker,
    original_graph: StateGraphBuildResult,
) -> StateGraphNode:
    """根据原节点和自动机状态创建一个产品节点。

    Args:
        product_node_id: 产品图内连续节点 ID。
        tracker: 当前节点关联的事件历史自动机状态。
        original_graph: 用于读取原始战斗状态和终局分类的基础图。

    Returns:
        复用原始 ``BattleState``、但使用独立分析键的产品节点。
    """
    original_node = original_graph.node(tracker.original_node_id)
    analysis_key = cast(
        StateKey,
        (
            "battle-event-analysis",
            int(tracker.original_node_id),
            tracker.occurrence_count_bucket,
            tracker.first_occurrence_turn_bucket,
            tracker.matched_in_range,
            tracker.next_turn_bucket,
        ),
    )
    return StateGraphNode(
        node_id=product_node_id,
        state=original_node.state,
        state_key=analysis_key,
        outcome=original_node.outcome,
        termination_reason=original_node.termination_reason,
    )


def _outgoing_edges(
    graph: StateGraphBuildResult,
) -> tuple[tuple[StateGraphEdge, ...], ...]:
    """按源节点索引原图出边，保留平行边和事件路径。

    Args:
        graph: 待建立出边索引的完整状态图。

    Returns:
        下标与 ``GraphNodeId`` 一致的不可变出边表。
    """
    outgoing: list[list[StateGraphEdge]] = [[] for _ in graph.nodes]
    for edge in graph.edges:
        outgoing[int(edge.source_node_id)].append(edge)
    return tuple(tuple(group) for group in outgoing)


def _advance_tracker(
    tracker: _EventTracker,
    target_node_id: GraphNodeId,
    path: tuple[TransitionEvent, ...],
    query: BattleEventQuery,
    count_overflow: int,
    turn_overflow: int,
) -> _EventTracker:
    """消费一条边事件路径并更新有限计数、首次回合和范围标记。

    Args:
        tracker: 转移前自动机状态。
        target_node_id: 原图边的目标节点。
        path: 当前替代路径内按顺序排列的类型化事件。
        query: 决定哪些事件计入分析的查询。
        count_overflow: 发生次数饱和桶；代表不小于该值。
        turn_overflow: 回合号饱和桶；代表不小于该值。

    Returns:
        指向原目标节点的新自动机状态。
    """
    matched_count = sum(query.predicate.matches(event) for event in path)
    current_turn = tracker.next_turn_bucket
    count_bucket = min(
        tracker.occurrence_count_bucket + matched_count,
        count_overflow,
    )
    first_turn = tracker.first_occurrence_turn_bucket
    if matched_count and first_turn is None:
        first_turn = current_turn
    matched_in_range = tracker.matched_in_range
    if matched_count and _turn_bucket_in_range(
        current_turn,
        query.turn_range,
        turn_overflow,
    ):
        matched_in_range = True
    next_turn = min(current_turn + 1, turn_overflow)
    return _EventTracker(
        original_node_id=target_node_id,
        occurrence_count_bucket=count_bucket,
        first_occurrence_turn_bucket=first_turn,
        matched_in_range=matched_in_range,
        next_turn_bucket=next_turn,
    )


def _turn_bucket_in_range(
    turn_bucket: int,
    turn_range: EventTurnRange | None,
    turn_overflow: int,
) -> bool:
    """判断精确或饱和回合桶是否完全落入查询范围。

    ``turn_overflow`` 的选取保证饱和桶不会横跨有限范围边界，因此该判断仍是精确的。

    Args:
        turn_bucket: 精确回合号或回合饱和桶。
        turn_range: 可选查询闭区间。
        turn_overflow: 表示大于等于该值的回合饱和桶。

    Returns:
        当前桶满足回合范围时返回 True。
    """
    if turn_range is None:
        return True
    if turn_bucket < turn_overflow:
        return turn_range.contains(turn_bucket)
    if turn_range.end_turn is not None and turn_range.end_turn < turn_overflow:
        return False
    return turn_range.start_turn is None or turn_range.start_turn <= turn_overflow


def _query_satisfied(
    tracker: _EventTracker,
    query: BattleEventQuery,
    product: _EventProductGraph,
) -> bool:
    """返回一个吸收历史是否满足完整事件 E 查询。

    Args:
        tracker: 吸收边界对应的事件自动机状态。
        query: 次数、回合范围和首次/任意发生语义。
        product: 提供饱和次数和回合桶边界的产品图。

    Returns:
        该完整随机历史满足事件 E 时返回 True。
    """
    count = tracker.occurrence_count_bucket
    if count < query.min_occurrences:
        return False
    if query.max_occurrences is not None:
        if count == product.count_overflow_bucket or count > query.max_occurrences:
            return False
    if query.turn_range is None:
        return True
    if query.occurrence_mode is EventOccurrenceMode.ANY:
        return tracker.matched_in_range
    first_turn = tracker.first_occurrence_turn_bucket
    return first_turn is not None and _turn_bucket_in_range(
        first_turn,
        query.turn_range,
        product.turn_overflow_bucket,
    )


def _product_statistics(
    nodes: list[StateGraphNode],
    edges: list[StateGraphEdge],
    components: tuple[StrongComponent, ...],
) -> StateGraphStatistics:
    """为产品图构造求解器与诊断使用的规模统计。

    Args:
        nodes: 产品图连续节点列表。
        edges: 产品图连续边列表。
        components: 产品图 SCC 分类结果。

    Returns:
        与最终产品图结构一致的规模和终局统计。
    """
    counts = StateGraphTerminalCounts(
        attacker_wins=sum(
            node.outcome is GraphNodeOutcome.ATTACKER_WIN for node in nodes
        ),
        defender_wins=sum(
            node.outcome is GraphNodeOutcome.DEFENDER_WIN for node in nodes
        ),
        draws=sum(node.outcome is GraphNodeOutcome.DRAW for node in nodes),
        non_terminal=sum(
            node.outcome is GraphNodeOutcome.NON_TERMINAL for node in nodes
        ),
        unknown=sum(node.outcome is GraphNodeOutcome.UNKNOWN for node in nodes),
    )
    return StateGraphStatistics(
        unique_state_count=len(nodes),
        edge_count=len(edges),
        max_turn_number=max(node.state.turn_number for node in nodes),
        terminal_counts=counts,
        closed_cycle_count=sum(
            component.kind is StrongComponentKind.CLOSED_CYCLE
            for component in components
        ),
        terminal_reachable_cycle_count=sum(
            component.kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE
            for component in components
        ),
    )


__all__ = [
    "_EventProductGraph",
    "_EventTracker",
    "_build_event_product_graph",
    "_query_satisfied",
    "_require_solved",
    "_required_probability",
]
