from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import NewType, Protocol, runtime_checkable

from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import TransitionEventSummary, WeightedTransition


GraphNodeId = NewType("GraphNodeId", int)
GraphEdgeId = NewType("GraphEdgeId", int)
StrongComponentId = NewType("StrongComponentId", int)


class StateGraphError(ValueError):
    """表示状态图输入、限制或内部索引违反稳定合同。"""


class GraphNodeOutcome(str, Enum):
    """表示图节点当前已知的终局或求解状态。"""

    ATTACKER_WIN = "attacker-win"
    DEFENDER_WIN = "defender-win"
    DRAW = "draw"
    NON_TERMINAL = "non-terminal"
    UNKNOWN = "unknown"


class GraphTruncationReason(str, Enum):
    """表示状态图没有完整展开的运行保护原因。"""

    MAX_TURNS = "max-turns"
    MAX_NODES = "max-nodes"
    MAX_EDGES = "max-edges"


class StrongComponentKind(str, Enum):
    """表示强连通分量在求解语义中的类别。"""

    ACYCLIC = "acyclic"
    CLOSED_CYCLE = "closed-cycle"
    TERMINAL_REACHABLE_CYCLE = "terminal-reachable-cycle"
    OPEN_UNRESOLVED_CYCLE = "open-unresolved-cycle"


@dataclass(frozen=True, slots=True)
class StateGraphLimits:
    """限制单次状态图构建允许消耗的图规模。

    Args:
        max_nodes: 允许创建的唯一状态节点上限；None 表示不限制节点数量。
        max_edges: 允许创建的带权有向边上限；None 表示不限制边数量。
        max_turns: 允许完整执行的最大回合号；None 时继承初始状态规则中的
            ``BattleInferenceRules.max_turns``。
    """

    max_nodes: int | None = None
    max_edges: int | None = None
    max_turns: int | None = None

    def __post_init__(self) -> None:
        """拒绝布尔值、零值和负数限制。"""
        for field_name, value in (
            ("max_nodes", self.max_nodes),
            ("max_edges", self.max_edges),
            ("max_turns", self.max_turns),
        ):
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise StateGraphError(f"{field_name} must be greater than 0")


@dataclass(frozen=True, slots=True)
class StateGraphNode:
    """表示一个按 ``StateKey`` 去重后的战斗状态节点。

    Args:
        node_id: 当前图内从 0 开始连续分配的节点 ID。
        state: 首次发现该语义状态时保存的不可变 ``BattleState``。
        state_key: 排除绝对回合号等展示字段后的稳定去重键。
        outcome: 当前节点已确认的胜负、平局、非终局或未知状态。
        termination_reason: 终局或未知状态的稳定原因；普通非终局节点为 None。
        predecessor_node_id: 首次发现当前节点时的前驱节点；根节点为 None。
        predecessor_edge_id: 首次发现当前节点时使用的边；根节点为 None。
    """

    node_id: GraphNodeId
    state: BattleState
    state_key: StateKey
    outcome: GraphNodeOutcome
    termination_reason: TerminationReason | GraphTruncationReason | None
    predecessor_node_id: GraphNodeId | None = None
    predecessor_edge_id: GraphEdgeId | None = None

    @property
    def is_terminal(self) -> bool:
        """返回当前节点是否已经具有确定的胜、负或平局语义。"""
        return self.outcome in {
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
            GraphNodeOutcome.DRAW,
        }


@dataclass(frozen=True, slots=True)
class StateGraphEdge:
    """表示两个唯一状态节点之间的一条精确带权有向边。

    Args:
        edge_id: 当前图内从 0 开始连续分配的边 ID。
        source_node_id: 转移发生前的唯一状态节点。
        target_node_id: 转移发生后的唯一状态节点。
        probability: 当前完整随机事件中该后继状态的精确概率。
        event_summary: #23 定义的轻量随机事件路径摘要。
        source_key: 可选的稳定解释来源键。
    """

    edge_id: GraphEdgeId
    source_node_id: GraphNodeId
    target_node_id: GraphNodeId
    probability: Fraction
    event_summary: TransitionEventSummary
    source_key: str | None = None


@dataclass(frozen=True, slots=True)
class StrongComponent:
    """表示迭代 SCC 分析得到的一个强连通分量。

    Args:
        component_id: 当前结果内稳定的分量 ID。
        node_ids: 按节点 ID 升序保存的分量成员。
        kind: 无环、封闭循环、可到达终局循环或开放未决循环。
        outgoing_component_ids: 当前分量直接指向的其他分量 ID。
        reaches_terminal: 是否存在一条有向路径可到达确定终局分量。
    """

    component_id: StrongComponentId
    node_ids: tuple[GraphNodeId, ...]
    kind: StrongComponentKind
    outgoing_component_ids: tuple[StrongComponentId, ...]
    reaches_terminal: bool


@dataclass(frozen=True, slots=True)
class StateGraphTerminalCounts:
    """按节点分类统计当前图中的终局和未决状态数量。"""

    attacker_wins: int
    defender_wins: int
    draws: int
    non_terminal: int
    unknown: int

    @property
    def total(self) -> int:
        """返回全部唯一状态节点数量。"""
        return (
            self.attacker_wins
            + self.defender_wins
            + self.draws
            + self.non_terminal
            + self.unknown
        )


@dataclass(frozen=True, slots=True)
class StateGraphStatistics:
    """记录状态图规模、最大回合和终局分布。"""

    unique_state_count: int
    edge_count: int
    max_turn_number: int
    terminal_counts: StateGraphTerminalCounts
    closed_cycle_count: int
    terminal_reachable_cycle_count: int


@dataclass(frozen=True, slots=True)
class StateGraphBuildResult:
    """保存一次去重状态图构建与循环分析的完整结果。

    Args:
        root_node_id: 初始状态对应的节点 ID，首版始终为 0。
        nodes: 按 ``node_id`` 连续排列的唯一状态节点。
        edges: 按 ``edge_id`` 连续排列的精确带权有向边。
        components: 覆盖全部节点且互不重叠的强连通分量。
        statistics: 图规模、最大回合和节点终局分布。
        truncation_reasons: 触发过的去重运行保护原因，按首次出现顺序保存。
    """

    root_node_id: GraphNodeId
    nodes: tuple[StateGraphNode, ...]
    edges: tuple[StateGraphEdge, ...]
    components: tuple[StrongComponent, ...]
    statistics: StateGraphStatistics
    truncation_reasons: tuple[GraphTruncationReason, ...] = ()

    @property
    def is_complete(self) -> bool:
        """返回状态图是否未触发任何运行保护截断。"""
        return not self.truncation_reasons

    def node(self, node_id: GraphNodeId) -> StateGraphNode:
        """按连续节点 ID 读取一个图节点。

        Args:
            node_id: 需要读取的节点 ID。

        Returns:
            对应的不可变 ``StateGraphNode``。

        Raises:
            StateGraphError: 节点 ID 超出当前结果范围。
        """
        index = int(node_id)
        if index < 0 or index >= len(self.nodes):
            raise StateGraphError(f"node_id {index} is outside the graph")
        return self.nodes[index]

    def representative_path(self, node_id: GraphNodeId) -> tuple[GraphNodeId, ...]:
        """沿首次发现前驱重建从根节点到目标节点的一条代表性路径。

        Args:
            node_id: 需要重建路径的目标节点。

        Returns:
            从根节点开始、以目标节点结束的节点 ID 元组。
        """
        current = self.node(node_id)
        reversed_path: list[GraphNodeId] = []
        while True:
            reversed_path.append(current.node_id)
            if current.predecessor_node_id is None:
                break
            current = self.node(current.predecessor_node_id)
        reversed_path.reverse()
        return tuple(reversed_path)


@runtime_checkable
class BattleStateTransitionExpander(Protocol):
    """把一个非终局 ``BattleState`` 展开为完整精确后继分布。"""

    def expand(
        self,
        state: BattleState,
    ) -> Iterable[WeightedTransition[BattleState]]:
        """返回当前节点的完整随机后继集合。

        Args:
            state: 待展开的不可变战斗状态。

        Returns:
            完整且可归一化的 ``WeightedTransition`` 可迭代对象。
            空集合表示异常地没有任何合法行动，图构建器会按确定平局处理。
        """


__all__ = [
    "BattleStateTransitionExpander",
    "GraphEdgeId",
    "GraphNodeId",
    "GraphNodeOutcome",
    "GraphTruncationReason",
    "StateGraphBuildResult",
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
