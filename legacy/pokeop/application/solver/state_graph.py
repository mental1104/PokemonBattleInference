from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattlePhase, BattleState, StateKey
from pokeop.domain.battle.transitions import merge_equivalent_transitions

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
    StateGraphStatistics,
    StateGraphTerminalCounts,
    StrongComponent,
    StrongComponentId,
    StrongComponentKind,
)
from .strong_components import (
    analyze_strong_components,
    apply_closed_cycle_resolution,
)


@dataclass(frozen=True, slots=True)
class StateGraphBuildProgress:
    """表示状态图构建过程中的一帧轻量进度。

    Args:
        phase: 构图阶段标识，当前固定为 ``building_graph`` 或 ``graph_built``。
        discovered_node_count: 当前已经发现并去重后的节点数量。
        edge_count: 当前已经写入的正式边数量。
        expanded_node_count: 已经展开后继的非终局节点数量。
        frontier_count: FIFO 队列中等待展开的节点数量。
        max_nodes: 节点上限；None 表示没有显式上限。
        max_edges: 边上限；None 表示没有显式上限。
    """

    phase: str
    discovered_node_count: int
    edge_count: int
    expanded_node_count: int
    frontier_count: int
    max_nodes: int | None
    max_edges: int | None


@runtime_checkable
class StateGraphProgressObserver(Protocol):
    """接收状态图构建进度事件的 application 层观察者端口。"""

    def write_graph_progress(self, progress: StateGraphBuildProgress) -> None:
        """接收一帧构图进度。

        Args:
            progress: 当前 builder 在同一线程内同步产生的轻量统计。
        """
        ...


@dataclass(frozen=True, slots=True)
class DiscardStateGraphProgressObserver:
    """默认丢弃构图进度，保持同步求解调用方零额外副作用。"""

    def write_graph_progress(self, progress: StateGraphBuildProgress) -> None:
        """忽略一帧构图进度。

        Args:
            progress: 当前 builder 产生的进度事件。
        """


@dataclass(frozen=True, slots=True)
class StateGraphBuilder:
    """使用显式 FIFO 队列构建按 ``StateKey`` 去重的战斗状态图。

    该 application solver 只依赖 ``BattleState -> WeightedTransition`` 扩展合同，
    不理解具体招式、特性、道具或 Pokémon 名称。
    强连通分量也使用显式栈，因此深链和长期循环都不会消耗
    Python 递归栈。

    Args:
        expander: 为每个非终局状态提供完整带权后继分布的稳定边界。
        limits: 节点、边和回合运行保护；None 时使用默认限制模型。
        progress_observer: 构图过程中接收轻量进度的观察者。
        progress_interval_nodes: 每展开多少个节点至少发出一次进度事件。
    """

    expander: BattleStateTransitionExpander
    limits: StateGraphLimits = StateGraphLimits()
    progress_observer: StateGraphProgressObserver = DiscardStateGraphProgressObserver()
    progress_interval_nodes: int = 200

    def __post_init__(self) -> None:
        """校验扩展器满足结构化协议并且限制模型类型正确。"""
        if not isinstance(self.expander, BattleStateTransitionExpander):
            raise StateGraphError(
                "expander must implement BattleStateTransitionExpander"
            )
        if not isinstance(self.limits, StateGraphLimits):
            raise StateGraphError("limits must be a StateGraphLimits instance")
        if not isinstance(self.progress_observer, StateGraphProgressObserver):
            raise StateGraphError("progress_observer must implement StateGraphProgressObserver")
        if (
            isinstance(self.progress_interval_nodes, bool)
            or not isinstance(self.progress_interval_nodes, int)
            or self.progress_interval_nodes <= 0
        ):
            raise StateGraphError("progress_interval_nodes must be a positive integer")

    def build(self, initial_state: BattleState) -> StateGraphBuildResult:
        """从一个初始战斗状态构建完整或明确截断的去重状态图。

        Args:
            initial_state: 图根节点，必须是正式不可变 ``BattleState``。

        Returns:
            包含唯一节点、精确边、SCC、统计和截断原因的不可变结果。

        Raises:
            StateGraphError: 初始状态类型错误或扩展器产生非法后继状态时
                抛出。
            TransitionError: 扩展器返回非归一化或非法概率分支时由 #23
                合同抛出。
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
        expanded_node_count = 0
        next_progress_at = self.progress_interval_nodes
        max_turns = (
            self.limits.max_turns
            if self.limits.max_turns is not None
            else initial_state.rules.max_turns
        )
        self._emit_progress(
            phase="building_graph",
            nodes=nodes,
            edges=edges,
            expanded_node_count=expanded_node_count,
            frontier_count=len(work_queue),
        )

        while work_queue:
            node_id = work_queue.popleft()
            node = nodes[int(node_id)]
            if node.outcome is not GraphNodeOutcome.NON_TERMINAL:
                continue

            if max_turns is not None and node.state.turn_number > max_turns:
                # 回合上限只是运行保护。
                # 必须标为 unknown，不能伪装为数学平局。
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.UNKNOWN,
                    termination_reason=GraphTruncationReason.MAX_TURNS,
                )
                _append_once(truncation_reasons, GraphTruncationReason.MAX_TURNS)
                continue

            transitions = tuple(self.expander.expand(node.state))
            expanded_node_count += 1
            if not transitions:
                # 整个状态没有任何后继时无法推断责任侧。
                # 稳定语义为异常平局。
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.DRAW,
                    termination_reason=TerminationReason.NO_LEGAL_ACTION,
                )
                continue

            merged = merge_equivalent_transitions(transitions)
            new_keys = tuple(
                transition.state.state_key
                for transition in merged
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
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.UNKNOWN,
                    termination_reason=GraphTruncationReason.MAX_NODES,
                )
                _append_once(truncation_reasons, GraphTruncationReason.MAX_NODES)
                continue
            if (
                self.limits.max_edges is not None
                and len(edges) + len(merged) > self.limits.max_edges
            ):
                nodes[int(node_id)] = replace(
                    node,
                    outcome=GraphNodeOutcome.UNKNOWN,
                    termination_reason=GraphTruncationReason.MAX_EDGES,
                )
                _append_once(truncation_reasons, GraphTruncationReason.MAX_EDGES)
                continue

            for transition in merged:
                target_key = transition.state.state_key
                target_node_id = node_ids_by_key.get(target_key)
                edge_id = GraphEdgeId(len(edges))
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
                            predecessor_node_id=node_id,
                            predecessor_edge_id=edge_id,
                        )
                    )
                    node_ids_by_key[target_key] = target_node_id
                    if target_outcome is GraphNodeOutcome.NON_TERMINAL:
                        work_queue.append(target_node_id)

                edges.append(
                    StateGraphEdge(
                        edge_id=edge_id,
                        source_node_id=node_id,
                        target_node_id=target_node_id,
                        probability=transition.probability,
                        event_summary=transition.event_summary,
                        source_key=transition.source_key,
                    )
                )
            if expanded_node_count >= next_progress_at:
                self._emit_progress(
                    phase="building_graph",
                    nodes=nodes,
                    edges=edges,
                    expanded_node_count=expanded_node_count,
                    frontier_count=len(work_queue),
                )
                next_progress_at = expanded_node_count + self.progress_interval_nodes

        components = analyze_strong_components(nodes, edges)
        nodes, components = apply_closed_cycle_resolution(nodes, components)
        statistics = _build_statistics(nodes, edges, components)
        self._emit_progress(
            phase="graph_built",
            nodes=nodes,
            edges=edges,
            expanded_node_count=expanded_node_count,
            frontier_count=0,
        )
        return StateGraphBuildResult(
            root_node_id=GraphNodeId(0),
            nodes=tuple(nodes),
            edges=tuple(edges),
            components=components,
            statistics=statistics,
            truncation_reasons=tuple(truncation_reasons),
        )

    def _emit_progress(
        self,
        *,
        phase: str,
        nodes: list[StateGraphNode],
        edges: list[StateGraphEdge],
        expanded_node_count: int,
        frontier_count: int,
    ) -> None:
        """同步发布一帧构图进度。

        Args:
            phase: 当前构图阶段。
            nodes: 当前已发现节点列表。
            edges: 当前已写入边列表。
            expanded_node_count: 已展开节点数量。
            frontier_count: 待展开队列长度。
        """
        self.progress_observer.write_graph_progress(
            StateGraphBuildProgress(
                phase=phase,
                discovered_node_count=len(nodes),
                edge_count=len(edges),
                expanded_node_count=expanded_node_count,
                frontier_count=frontier_count,
                max_nodes=self.limits.max_nodes,
                max_edges=self.limits.max_edges,
            )
        )


def _classify_battle_state(
    state: BattleState,
) -> tuple[GraphNodeOutcome, TerminationReason | None]:
    """根据双方 HP 和显式终局阶段判定节点的基础终局语义。

    Args:
        state: 需要分类的不可变战斗状态。

    Returns:
        节点分类和可选终止原因。双方同时濒死为平局；
        单方濒死时另一方获胜；
        ``TERMINAL`` 阶段但双方均存活时按异常无合法行动平局处理。
    """
    attacker_fainted = state.attacker.current_hp == 0
    defender_fainted = state.defender.current_hp == 0
    if attacker_fainted and defender_fainted:
        return GraphNodeOutcome.DRAW, TerminationReason.MUTUAL_KNOCKOUT
    if attacker_fainted:
        return GraphNodeOutcome.DEFENDER_WIN, TerminationReason.KNOCKOUT
    if defender_fainted:
        return GraphNodeOutcome.ATTACKER_WIN, TerminationReason.KNOCKOUT
    if state.phase is BattlePhase.TERMINAL:
        return GraphNodeOutcome.DRAW, TerminationReason.NO_LEGAL_ACTION
    return GraphNodeOutcome.NON_TERMINAL, None


def _append_once(
    values: list[GraphTruncationReason],
    value: GraphTruncationReason,
) -> None:
    """按首次出现顺序记录一个截断原因，避免结果中重复枚举。

    Args:
        values: 当前正在构建的截断原因列表，会被原地更新。
        value: 本次触发的截断原因。
    """
    if value not in values:
        values.append(value)


def _build_statistics(
    nodes: list[StateGraphNode],
    edges: list[StateGraphEdge],
    components: tuple[StrongComponent, ...],
) -> StateGraphStatistics:
    """根据最终节点分类和 SCC 结果汇总图构建统计。

    Args:
        nodes: 已应用封闭循环规则的唯一状态节点。
        edges: 图中的全部精确带权边。
        components: 已分类的强连通分量。

    Returns:
        节点、边、最大回合、终局分布和循环数量统计。
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
    "BattleStateTransitionExpander",
    "GraphEdgeId",
    "GraphNodeId",
    "GraphNodeOutcome",
    "GraphTruncationReason",
    "StateGraphBuildResult",
    "StateGraphBuilder",
    "StateGraphEdge",
    "StateGraphError",
    "StateGraphLimits",
    "StateGraphNode",
    "StateGraphStatistics",
    "StateGraphTerminalCounts",
    "StrongComponent",
    "StrongComponentId",
    "StrongComponentKind",
]
