"""从已求解状态图提取总结型归因报告。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.transitions import TransitionEventSummary

from .graph_solver import (
    _build_boundary_values,
    _build_outgoing_edges,
    _closed_cycle_node_ids,
    _solve_acyclic_graph,
    _solve_cyclic_graph,
    _topological_order,
    _validate_graph_structure,
)
from .models import StateGraphBuildResult


@dataclass(slots=True)
class _ActionPairAccumulator:
    """累计一个 root 行动簇的概率质量和终局贡献。"""

    attacker_move_id: int | None
    defender_move_id: int | None
    probability: Fraction = Fraction(0)
    attacker_win_contribution: Fraction = Fraction(0)
    defender_win_contribution: Fraction = Fraction(0)
    draw_contribution: Fraction = Fraction(0)
    representative_target_node_id: int | None = None
    path_count: int = 0


def build_root_action_pair_explanation(
    *,
    graph: StateGraphBuildResult,
    root_event_summary_by_state_key: dict[object, TransitionEventSummary],
    max_buckets: int = 12,
) -> dict[str, Any]:
    """构建完成页首版总结型归因报告。

    Args:
        graph: 已完整构建并可求解的精确状态图。
        root_event_summary_by_state_key: root 后继 ``state_key`` 到完整事件摘要的映射；
            summary 图自身可能已经丢弃事件，所以由执行器在 root 展开时额外提供。
        max_buckets: 返回的行动簇上限，按对己方胜率贡献从高到低排序。

    Returns:
        可直接 JSON 序列化的解释报告。所有概率仍来自完整图求解，不跳过任何随机路径。
    """
    if max_buckets <= 0:
        raise ValueError("max_buckets must be positive")
    values_by_node = _solve_values_by_node(graph)
    root_values = values_by_node[graph.root_node_id]
    accumulators: dict[tuple[int | None, int | None], _ActionPairAccumulator] = {}

    for edge in graph.edges:
        if edge.source_node_id != graph.root_node_id:
            continue
        target_node = graph.node(edge.target_node_id)
        event_summary = root_event_summary_by_state_key.get(target_node.state_key)
        if event_summary is None:
            event_summary = edge.event_summary
        successor_values = values_by_node[edge.target_node_id]
        for path_probability, path in event_summary.weighted_paths:
            attacker_move_id, defender_move_id = _action_pair_from_path(path)
            probability = edge.probability * path_probability
            key = (attacker_move_id, defender_move_id)
            bucket = accumulators.get(key)
            if bucket is None:
                bucket = _ActionPairAccumulator(
                    attacker_move_id=attacker_move_id,
                    defender_move_id=defender_move_id,
                    representative_target_node_id=int(edge.target_node_id),
                )
                accumulators[key] = bucket
            bucket.probability += probability
            bucket.attacker_win_contribution += probability * successor_values.attacker_win
            bucket.defender_win_contribution += probability * successor_values.defender_win
            bucket.draw_contribution += probability * successor_values.draw
            bucket.path_count += 1
            if bucket.representative_target_node_id is None:
                bucket.representative_target_node_id = int(edge.target_node_id)

    buckets = sorted(
        accumulators.values(),
        key=lambda item: item.attacker_win_contribution,
        reverse=True,
    )
    return {
        "version": "battle-inference.explanation.v1",
        "basis": "root-action-pair-attribution",
        "coverage": _fraction_json(sum((bucket.probability for bucket in buckets), Fraction(0))),
        "root": {
            "node_id": int(graph.root_node_id),
            "attacker_win": _fraction_json(root_values.attacker_win),
            "defender_win": _fraction_json(root_values.defender_win),
            "draw": _fraction_json(root_values.draw),
        },
        "buckets": [_bucket_json(bucket) for bucket in buckets[:max_buckets]],
        "omitted_bucket_count": max(0, len(buckets) - max_buckets),
        "graph": {
            "nodes": graph.statistics.unique_state_count,
            "edges": graph.statistics.edge_count,
        },
    }


def _solve_values_by_node(graph: StateGraphBuildResult):
    """复用精确求解器内部算法，返回每个节点的胜负平价值。"""
    _validate_graph_structure(graph)
    closed_cycle_nodes = _closed_cycle_node_ids(graph)
    boundary_values = _build_boundary_values(graph, closed_cycle_nodes)
    transient_node_ids = tuple(
        node.node_id for node in graph.nodes if node.node_id not in boundary_values
    )
    outgoing = _build_outgoing_edges(graph)
    transient_order = _topological_order(transient_node_ids, outgoing)
    if transient_order is not None:
        return _solve_acyclic_graph(graph, outgoing, boundary_values, transient_order)
    return _solve_cyclic_graph(graph, outgoing, boundary_values, transient_node_ids)


def _action_pair_from_path(
    path: tuple[object, ...],
) -> tuple[int | None, int | None]:
    """从一条事件路径提取双方本回合使用的招式 ID。"""
    attacker_move_id: int | None = None
    defender_move_id: int | None = None
    for event in path:
        if not isinstance(event, BattleEvent) or event.kind is not BattleEventKind.MOVE_USED:
            continue
        if event.actor is BattleSide.ATTACKER and attacker_move_id is None:
            attacker_move_id = event.move_id
        if event.actor is BattleSide.DEFENDER and defender_move_id is None:
            defender_move_id = event.move_id
    return attacker_move_id, defender_move_id


def _bucket_json(bucket: _ActionPairAccumulator) -> dict[str, Any]:
    """把一个行动簇累计器转换为稳定 JSON 字典。"""
    return {
        "attacker_move_id": bucket.attacker_move_id,
        "defender_move_id": bucket.defender_move_id,
        "probability": _fraction_json(bucket.probability),
        "attacker_win_contribution": _fraction_json(bucket.attacker_win_contribution),
        "defender_win_contribution": _fraction_json(bucket.defender_win_contribution),
        "draw_contribution": _fraction_json(bucket.draw_contribution),
        "conditional_attacker_win": _fraction_json(
            _conditional(bucket.attacker_win_contribution, bucket.probability)
        ),
        "conditional_defender_win": _fraction_json(
            _conditional(bucket.defender_win_contribution, bucket.probability)
        ),
        "conditional_draw": _fraction_json(
            _conditional(bucket.draw_contribution, bucket.probability)
        ),
        "representative_target_node_id": bucket.representative_target_node_id,
        "path_count": bucket.path_count,
    }


def _conditional(numerator: Fraction, denominator: Fraction) -> Fraction:
    """计算条件概率；空概率质量返回 0。"""
    if denominator == 0:
        return Fraction(0)
    return numerator / denominator


def _fraction_json(value: Fraction) -> dict[str, str | float]:
    """把精确分数转换为前端展示友好的 JSON 片段。"""
    return {
        "numerator": str(value.numerator),
        "denominator": str(value.denominator),
        "decimal": float(value),
    }


__all__ = ["build_root_action_pair_explanation"]
