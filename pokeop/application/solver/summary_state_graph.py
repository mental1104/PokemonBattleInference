"""为固定配置精确摘要构建不携带探索元数据的轻量状态图。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Hashable, Iterable

from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import (
    TransitionEventSummary,
    WeightedTransition,
    validate_transition_distribution,
)

from .models import (
    BattleStateTransitionExpander,
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    GraphTruncationReason,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphError,
    StateGraphLimits,
    StateGraphNode,
)
from .state_graph import _build_statistics, _classify_battle_state
from .strong_components import analyze_strong_components, apply_closed_cycle_resolution


@dataclass(slots=True)
class _ProbabilityAccumulator:
    """暂存一个等价后继状态及其累计精确概率。"""

    state: BattleState
    probability: Fraction


def merge_summary_transitions(
    transitions: Iterable[WeightedTransition[BattleState]],
) -> tuple[WeightedTransition[BattleState], ...]:
    """按 ``StateKey`` 合并后继概率，同时主动丢弃事件路径元数据。

    固定配置摘要只需要状态和概率来求解胜负平，不需要为每条边保留伤害档位、
    行动说明和替代事件路径。该函数避免 ``TransitionEventSummary`` 在大量等价分支
    归并期间反复做路径复制、条件概率重算和 ``Fraction`` 约分。

    Args:
        transitions: 同一状态的完整精确后继分布，概率必须严格归一化。

    Returns:
        按首次出现顺序保存的唯一后继状态；每条边只携带空事件摘要。

    Raises:
        TransitionError: 输入为空、概率未归一化或后继状态键非法时由领域合同抛出。
    """
    materialized = validate_transition_distribution(transitions)
    accumulators: dict[Hashable, _ProbabilityAccumulator] = {}

    for transition in materialized:
        state_key = transition.state.state_key
        existing = accumulators.get(state_key)
        if existing is None:
            accumulators[state_key] = _ProbabilityAccumulator(
                state=transition.state,
                probability=transition.probability,
            )
            continue
        existing.probability += transition.probability

    merged = tuple(
        WeightedTransition(
            probability=accumulator.probability,
            state=accumulator.state,
            event_summary=TransitionEventSummary.empty(),
            source_key=None,
        )
        for accumulator in accumulators.values()
    )
    return validate_transition_distribution(merged)


@dataclass(frozen=True, slots=True)
class SummaryStateGraphBuilder:
    """构建供精确概率摘要使用的紧凑状态图。

    该 application solver 与正式 ``StateGraphBuilder`` 使用相同 ``StateKey``、SCC 和
    精确边概率语义，但不保存前驱、事件路径或来源键。达到节点/边预算后会立即把当前
    未展开队列标为未知并停止，避免继续执行注定不会进入结果的昂贵回合解析。

    Args:
        expander: 为每个非终局状态提供完整精确后继分布的扩展器。
        limits: 单次固定配置允许使用的节点、边和回合保护。
    """

    expander: BattleStateTransitionExpander
    limits: StateGraphLimits = StateGraphLimits()

    def __post_init__(self) -> None:
        """校验扩展器与限制模型使用正式 application 协议。"""
        if not isinstance(self.expander, BattleStateTransitionExpander):
            raise StateGraphError(
                "expander must implement BattleStateTransitionExpander"
            )
        if not isinstance(self.limits, StateGraphLimits):
            raise StateGraphError("limits must be a StateGraphLimits instance")

    def build(self, initial_state: BattleState) -> StateGraphBuildResult:
        """从初始状态构建精确摘要所需的最小完整图。

        Args:
            initial_state: 满足固定 1v1 规则的不可变初始战斗状态。

        Returns:
            可直接交给现有精确图求解器的 ``StateGraphBuildResult``。触发预算时结果
            保留明确截断原因，不返回貌似完整的部分概率。

        Raises:
            StateGraphError: 初始状态或扩展器返回值违反状态图合同时抛出。
        """
        if not isinstance(initial_state, BattleState):
            raise StateGraphError("initial_state must be a BattleState")

        root_outcome, root_reason = _classify_battle_state(initial_state)
        nodes: list[StateGraphNode] = [
            StateGraphNode(
                node_id=GraphNodeId(0),
                state=initial_state,
                state_key=initial_state.state_key,
                outcome=root_outcome,
                termination_reason=root_reason,
            )
        ]
        edges: list[StateGraphEdge] = []
        node_ids_by_key: dict[StateKey, GraphNodeId] = {
            initial_state.state_key: GraphNodeId(0)
        }
        work_queue: deque[GraphNodeId] = deque()
        if root_outcome is GraphNodeOutcome.NON_TERMINAL:
            work_queue.append(GraphNodeId(0))

        truncation_reasons: list[GraphTruncationReason] = []
        max_turns = (
            self.limits.max_turns
            if self.limits.max_turns is not None
            else initial_state.rules.max_turns
        )

        while work_queue:
            node_id = work_queue.popleft()
            node = nodes[int(node_id)]
            if node.outcome is not GraphNodeOutcome.NON_TERMINAL:
                continue

            if max_turns is not None and node.state.turn_number > max_turns:
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.UNKNOWN,
                    termination_reason=GraphTruncationReason.MAX_TURNS,
                )
                self._append_once(
                    truncation_reasons,
                    GraphTruncationReason.MAX_TURNS,
                )
                continue

            raw_transitions = tuple(self.expander.expand(node.state))
            if not raw_transitions:
                # 与正式构图器保持一致：整体没有后继代表异常无合法行动平局，
                # 不能把领域允许的空分布误报为概率合同异常。
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.DRAW,
                    termination_reason=TerminationReason.NO_LEGAL_ACTION,
                )
                continue
            transitions = merge_summary_transitions(raw_transitions)
            new_keys = tuple(
                transition.state.state_key
                for transition in transitions
                if transition.state.state_key not in node_ids_by_key
            )
            if len(set(new_keys)) != len(new_keys):
                raise StateGraphError(
                    "merged transitions must contain at most one branch per StateKey"
                )

            if (
                self.limits.max_nodes is not None
                and len(nodes) + len(new_keys) > self.limits.max_nodes
            ):
                self._stop_for_budget(
                    nodes,
                    work_queue,
                    node_id,
                    GraphTruncationReason.MAX_NODES,
                    truncation_reasons,
                )
                break
            if (
                self.limits.max_edges is not None
                and len(edges) + len(transitions) > self.limits.max_edges
            ):
                self._stop_for_budget(
                    nodes,
                    work_queue,
                    node_id,
                    GraphTruncationReason.MAX_EDGES,
                    truncation_reasons,
                )
                break

            for transition in transitions:
                target_key = transition.state.state_key
                target_node_id = node_ids_by_key.get(target_key)
                if target_node_id is None:
                    target_node_id = GraphNodeId(len(nodes))
                    target_outcome, target_reason = _classify_battle_state(
                        transition.state
                    )
                    nodes.append(
                        StateGraphNode(
                            node_id=target_node_id,
                            state=transition.state,
                            state_key=target_key,
                            outcome=target_outcome,
                            termination_reason=target_reason,
                        )
                    )
                    node_ids_by_key[target_key] = target_node_id
                    if target_outcome is GraphNodeOutcome.NON_TERMINAL:
                        work_queue.append(target_node_id)

                edges.append(
                    StateGraphEdge(
                        edge_id=GraphEdgeId(len(edges)),
                        source_node_id=node_id,
                        target_node_id=target_node_id,
                        probability=transition.probability,
                        event_summary=TransitionEventSummary.empty(),
                        source_key=None,
                    )
                )

        components = analyze_strong_components(nodes, edges)
        nodes, components = apply_closed_cycle_resolution(nodes, components)
        return StateGraphBuildResult(
            root_node_id=GraphNodeId(0),
            nodes=tuple(nodes),
            edges=tuple(edges),
            components=components,
            statistics=_build_statistics(nodes, edges, components),
            truncation_reasons=tuple(truncation_reasons),
        )

    @staticmethod
    def _stop_for_budget(
        nodes: list[StateGraphNode],
        work_queue: deque[GraphNodeId],
        current_node_id: GraphNodeId,
        reason: GraphTruncationReason,
        truncation_reasons: list[GraphTruncationReason],
    ) -> None:
        """把尚未展开的节点统一标为未知并立即停止昂贵扩展。

        Args:
            nodes: 当前已经发现的全部图节点，会原地更新未展开节点。
            work_queue: 尚未展开的节点队列；调用结束后会被清空。
            current_node_id: 本次发现预算不足的当前节点。
            reason: 节点或边预算对应的稳定截断原因。
            truncation_reasons: 当前构图已触发的原因列表，会保持首次出现顺序。
        """
        pending_ids = (current_node_id, *tuple(work_queue))
        for node_id in pending_ids:
            node = nodes[int(node_id)]
            if node.outcome is GraphNodeOutcome.NON_TERMINAL:
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.UNKNOWN,
                    termination_reason=reason,
                )
        work_queue.clear()
        SummaryStateGraphBuilder._append_once(truncation_reasons, reason)

    @staticmethod
    def _append_once(
        values: list[GraphTruncationReason],
        value: GraphTruncationReason,
    ) -> None:
        """按首次触发顺序记录一个唯一截断原因。"""
        if value not in values:
            values.append(value)


__all__ = ["SummaryStateGraphBuilder", "merge_summary_transitions"]
