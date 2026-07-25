"""求解事件产品图属性、有限分布和类型化元数据覆盖。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from fractions import Fraction

from pokeop.application.solver.graph_solver import BattleGraphSolver
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphNode,
    StrongComponentKind,
)
from pokeop.domain.battle.battle_events import BattleEvent
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEvent

from .product_graph import (
    _EventProductGraph,
    _EventTracker,
    _require_solved,
    _required_probability,
)
from .query import BattleEventQuery
from .results import (
    EventPathGroupCoverage,
    KeyEventSummary,
    ProbabilityDistributionBucket,
)


def _solve_product_property(
    product: _EventProductGraph,
    solver: BattleGraphSolver,
    property_predicate: Callable[[_EventTracker, GraphNodeOutcome, bool], bool],
) -> Fraction:
    """把产品图吸收历史二分类并求解属性成立概率。

    Args:
        product: 事件历史产品图。
        solver: 现有精确图求解器。
        property_predicate: 接收自动机状态、原终局和是否封闭循环边界的判定函数。

    Returns:
        从产品根节点最终进入属性成立边界的精确概率。
    """
    closed_nodes = frozenset(
        node_id
        for component in product.graph.components
        if component.kind is StrongComponentKind.CLOSED_CYCLE
        for node_id in component.node_ids
    )
    binary_nodes: list[StateGraphNode] = []
    for node, tracker in zip(
        product.graph.nodes,
        product.trackers,
        strict=True,
    ):
        closed = node.node_id in closed_nodes
        boundary = node.is_terminal or closed
        if not boundary:
            binary_nodes.append(
                replace(
                    node,
                    outcome=GraphNodeOutcome.NON_TERMINAL,
                    termination_reason=None,
                )
            )
            continue
        outcome = (
            GraphNodeOutcome.ATTACKER_WIN
            if property_predicate(tracker, node.outcome, closed)
            else GraphNodeOutcome.DEFENDER_WIN
        )
        binary_nodes.append(
            replace(node, outcome=outcome, termination_reason=None)
        )

    binary_graph = replace(product.graph, nodes=tuple(binary_nodes))
    result = solver.solve(binary_graph, BattleSide.ATTACKER)
    _require_solved("event property", result)
    return _required_probability("event property", result.win_probability)


def _occurrence_count_distribution(
    product: _EventProductGraph,
    query: BattleEventQuery,
    solver: BattleGraphSolver,
) -> tuple[tuple[ProbabilityDistributionBucket, ...], int]:
    """求解 0..N 和 ``N+`` 发生次数桶的精确概率。

    Args:
        product: 已构建的有限事件历史乘积图。
        query: 提供单独展示的最大精确次数。
        solver: 复用的精确图求解器。

    Returns:
        完整次数分布以及为该分布执行的求解次数。
    """
    buckets: list[ProbabilityDistributionBucket] = []
    for count in range(query.distribution_count_limit + 1):
        probability = _solve_product_property(
            product,
            solver,
            lambda tracker, _outcome, _closed, expected=count: (
                tracker.occurrence_count_bucket == expected
            ),
        )
        buckets.append(
            ProbabilityDistributionBucket(
                key=f"count:{count}",
                probability=probability,
            )
        )
    overflow_probability = _solve_product_property(
        product,
        solver,
        lambda tracker, _outcome, _closed: (
            tracker.occurrence_count_bucket
            > query.distribution_count_limit
        ),
    )
    buckets.append(
        ProbabilityDistributionBucket(
            key=f"count:{query.distribution_count_limit + 1}+",
            probability=overflow_probability,
        )
    )
    return tuple(buckets), len(buckets)


def _first_occurrence_distribution(
    product: _EventProductGraph,
    query: BattleEventQuery,
    solver: BattleGraphSolver,
) -> tuple[tuple[ProbabilityDistributionBucket, ...], int]:
    """求解从未发生、逐回合首次发生和更晚首次发生的精确概率。

    Args:
        product: 已构建的有限事件历史乘积图。
        query: 提供单独展示的最大精确回合。
        solver: 复用的精确图求解器。

    Returns:
        完整首次发生回合分布以及为该分布执行的求解次数。
    """
    buckets: list[ProbabilityDistributionBucket] = [
        ProbabilityDistributionBucket(
            key="first:never",
            probability=_solve_product_property(
                product,
                solver,
                lambda tracker, _outcome, _closed: (
                    tracker.first_occurrence_turn_bucket is None
                ),
            ),
        )
    ]
    for turn_number in range(1, query.distribution_turn_limit + 1):
        probability = _solve_product_property(
            product,
            solver,
            lambda tracker, _outcome, _closed, expected=turn_number: (
                tracker.first_occurrence_turn_bucket == expected
            ),
        )
        buckets.append(
            ProbabilityDistributionBucket(
                key=f"first:turn:{turn_number}",
                probability=probability,
            )
        )
    overflow_probability = _solve_product_property(
        product,
        solver,
        lambda tracker, _outcome, _closed: (
            tracker.first_occurrence_turn_bucket is not None
            and tracker.first_occurrence_turn_bucket
            > query.distribution_turn_limit
        ),
    )
    buckets.append(
        ProbabilityDistributionBucket(
            key=f"first:after:{query.distribution_turn_limit}",
            probability=overflow_probability,
        )
    )
    return tuple(buckets), len(buckets)


def _event_metadata_coverage(
    graph: StateGraphBuildResult,
    query: BattleEventQuery,
) -> tuple[EventPathGroupCoverage, tuple[KeyEventSummary, ...]]:
    """统计正式图边路径组覆盖，并提炼唯一类型化关键事件。

    Args:
        graph: 保留正式类型化事件路径的原始状态图。
        query: 决定哪些事件算作命中的结构化查询。

    Returns:
        路径组覆盖统计和按覆盖数量排序的关键事件摘要。
    """
    total_path_groups = 0
    matching_path_groups = 0
    matching_edge_ids: set[GraphEdgeId] = set()
    counts: dict[tuple[object, ...], int] = defaultdict(int)
    representative: dict[tuple[object, ...], TransitionEvent] = {}

    for edge in graph.edges:
        for path in edge.event_summary.paths:
            total_path_groups += 1
            matched_events = tuple(
                event for event in path if query.predicate.matches(event)
            )
            if not matched_events:
                continue
            matching_path_groups += 1
            matching_edge_ids.add(edge.edge_id)
            for event in set(matched_events):
                key = _key_event_identity(event)
                counts[key] += 1
                representative[key] = event

    ordered_keys = sorted(
        counts,
        key=lambda key: (-counts[key], tuple(str(value) for value in key)),
    )
    truncated_keys = ordered_keys[: query.max_key_event_summaries]
    key_events = tuple(
        _key_event_summary(representative[key], counts[key])
        for key in truncated_keys
    )
    return (
        EventPathGroupCoverage(
            total_edge_count=len(graph.edges),
            matching_edge_count=len(matching_edge_ids),
            total_event_path_group_count=total_path_groups,
            matching_event_path_group_count=matching_path_groups,
        ),
        key_events,
    )


def _key_event_identity(event: TransitionEvent) -> tuple[object, ...]:
    """返回用于关键事件去重的完整结构化字段键。

    Args:
        event: 待去重的随机或业务事件。

    Returns:
        不依赖展示文本的完整结构化字段元组。
    """
    if isinstance(event, BattleEvent):
        return (
            event.event_type,
            event.kind,
            event.actor,
            event.target,
            event.move_id,
            event.source_identifier,
            event.event_id,
            event.outcome_id,
        )
    return (
        event.event_type,
        None,
        None,
        None,
        None,
        None,
        event.event_id,
        event.outcome_id,
    )


def _key_event_summary(
    event: TransitionEvent,
    path_group_count: int,
) -> KeyEventSummary:
    """把随机或业务事件转换为无对象引用的关键事件摘要。

    Args:
        event: 待投影的类型化事件。
        path_group_count: 包含该事件的正式路径组数量。

    Returns:
        可供 application/API 投影使用的稳定事件摘要。
    """
    if isinstance(event, BattleEvent):
        return KeyEventSummary(
            event_type=event.event_type,
            battle_event_kind=event.kind,
            actor=event.actor,
            target=event.target,
            move_id=event.move_id,
            effect_identifier=event.source_identifier,
            event_id=event.event_id,
            outcome_id=event.outcome_id,
            path_group_count=path_group_count,
        )
    return KeyEventSummary(
        event_type=event.event_type,
        battle_event_kind=None,
        actor=None,
        target=None,
        move_id=None,
        effect_identifier=None,
        event_id=event.event_id,
        outcome_id=event.outcome_id,
        path_group_count=path_group_count,
    )


__all__ = [
    "_event_metadata_coverage",
    "_first_occurrence_distribution",
    "_occurrence_count_distribution",
    "_solve_product_property",
]
