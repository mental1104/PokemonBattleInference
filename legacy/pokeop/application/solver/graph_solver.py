from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Protocol, runtime_checkable

from pokeop.domain.battle.inference_outcome import BattleSide

from .models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StrongComponentKind,
)


class BattleGraphSolveError(ValueError):
    """表示状态图或求解器配置违反稳定求解合同。"""


class BattleGraphSolveStatus(str, Enum):
    """表示一次状态图求解的完成状态。"""

    SOLVED = "solved"
    INCOMPLETE_GRAPH = "incomplete-graph"
    RESOURCE_LIMIT_EXCEEDED = "resource-limit-exceeded"
    SINGULAR_SYSTEM = "singular-system"
    NOT_CONVERGED = "not-converged"


class ExpectedTurnsStatus(str, Enum):
    """表示期望回合数是否可有限表示。"""

    FINITE = "finite"
    INFINITE = "infinite"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ExpectedTurns:
    """保存期望回合数及其有限性语义。

    Args:
        status: 有限、无限或因求解失败而不可用。
        value: ``FINITE`` 时的精确期望回合数；其他状态必须为 None。
    """

    status: ExpectedTurnsStatus
    value: Fraction | None = None

    def __post_init__(self) -> None:
        """校验状态与数值是否一致。"""
        if not isinstance(self.status, ExpectedTurnsStatus):
            raise BattleGraphSolveError("expected turns status must be explicit")
        if self.status is ExpectedTurnsStatus.FINITE:
            if not isinstance(self.value, Fraction) or self.value < 0:
                raise BattleGraphSolveError(
                    "finite expected turns must use a non-negative Fraction"
                )
            return
        if self.value is not None:
            raise BattleGraphSolveError(
                "infinite or unavailable expected turns cannot carry a value"
            )


@dataclass(frozen=True, slots=True)
class BattleGraphSolveResult:
    """保存固定观察方视角下的状态图求解结果。

    Args:
        status: 求解是否完成，或失败/不完整的稳定原因分类。
        observer: 胜负概率所采用的观察方。
        win_probability: 观察方最终获胜概率；未完成求解时为 None。
        loss_probability: 观察方最终失败概率；未完成求解时为 None。
        draw_probability: 最终平局概率，包括无出口封闭 SCC；未完成时为 None。
        closed_cycle_probability: 进入正概率永不结束封闭 SCC 的概率。
        expected_turns: 期望回合数的有限、无限或不可用结果。
        probability_tolerance: 概率守恒允许误差；精确 Fraction 求解固定为 0。
        diagnostics: 不完整、资源限制或方程失败的稳定诊断信息。
    """

    status: BattleGraphSolveStatus
    observer: BattleSide
    win_probability: Fraction | None
    loss_probability: Fraction | None
    draw_probability: Fraction | None
    closed_cycle_probability: Fraction | None
    expected_turns: ExpectedTurns
    probability_tolerance: Fraction = Fraction(0, 1)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """校验完整结果的概率守恒与未完成结果的空值语义。"""
        if not isinstance(self.status, BattleGraphSolveStatus):
            raise BattleGraphSolveError("solve status must be explicit")
        if not isinstance(self.observer, BattleSide):
            raise BattleGraphSolveError("observer must be a BattleSide")
        if self.probability_tolerance != Fraction(0, 1):
            raise BattleGraphSolveError(
                "pure exact graph results require zero probability tolerance"
            )

        probabilities = (
            self.win_probability,
            self.loss_probability,
            self.draw_probability,
            self.closed_cycle_probability,
        )
        if self.status is BattleGraphSolveStatus.SOLVED:
            if any(not isinstance(value, Fraction) for value in probabilities):
                raise BattleGraphSolveError(
                    "solved graph results must contain exact probabilities"
                )
            typed_probabilities = tuple(
                value for value in probabilities if value is not None
            )
            if any(value < 0 or value > 1 for value in typed_probabilities):
                raise BattleGraphSolveError("solved probabilities must be in [0, 1]")
            if self.probability_total != Fraction(1, 1):
                raise BattleGraphSolveError(
                    "win, loss and draw probabilities must sum exactly to 1"
                )
            closed_cycle_probability = self.closed_cycle_probability
            if closed_cycle_probability is None:
                raise BattleGraphSolveError(
                    "solved result requires closed-cycle probability"
                )
            if (
                closed_cycle_probability > 0
                and self.expected_turns.status is not ExpectedTurnsStatus.INFINITE
            ):
                raise BattleGraphSolveError(
                    "positive closed-cycle probability requires infinite expected turns"
                )
            if (
                closed_cycle_probability == 0
                and self.expected_turns.status is not ExpectedTurnsStatus.FINITE
            ):
                raise BattleGraphSolveError(
                    "zero closed-cycle probability requires finite expected turns"
                )
            return

        if any(value is not None for value in probabilities):
            raise BattleGraphSolveError(
                "unsolved graph results cannot expose partial probabilities"
            )
        if self.expected_turns.status is not ExpectedTurnsStatus.UNAVAILABLE:
            raise BattleGraphSolveError(
                "unsolved graph results require unavailable expected turns"
            )

    @property
    def probability_total(self) -> Fraction | None:
        """返回胜、负、平概率总和；未完成求解时返回 None。"""
        if (
            self.win_probability is None
            or self.loss_probability is None
            or self.draw_probability is None
        ):
            return None
        return self.win_probability + self.loss_probability + self.draw_probability

    @classmethod
    def unavailable(
        cls,
        *,
        status: BattleGraphSolveStatus,
        observer: BattleSide,
        diagnostics: tuple[str, ...],
    ) -> BattleGraphSolveResult:
        """创建不暴露部分概率的未完成求解结果。

        Args:
            status: 除 ``SOLVED`` 外的失败或不完整状态。
            observer: 调用方请求的观察方。
            diagnostics: 可供日志和上层结果展示的稳定诊断信息。

        Returns:
            所有概率均为 None、期望回合不可用的结果对象。
        """
        if status is BattleGraphSolveStatus.SOLVED:
            raise BattleGraphSolveError("unavailable result cannot use solved status")
        return cls(
            status=status,
            observer=observer,
            win_probability=None,
            loss_probability=None,
            draw_probability=None,
            closed_cycle_probability=None,
            expected_turns=ExpectedTurns(ExpectedTurnsStatus.UNAVAILABLE),
            diagnostics=diagnostics,
        )


@runtime_checkable
class BattleGraphSolver(Protocol):
    """把完整带权状态图求解为固定观察方胜、负、平概率。"""

    @property
    def solver_id(self) -> str:
        """返回可写入结果或日志的稳定求解器标识。"""

    def solve(
        self,
        graph: StateGraphBuildResult,
        observer: BattleSide = BattleSide.ATTACKER,
    ) -> BattleGraphSolveResult:
        """求解状态图的吸收概率和期望回合数。

        Args:
            graph: #24 构建的完整或明确截断状态图。
            observer: 胜负概率所采用的观察方。

        Returns:
            完整精确解，或不会伪造部分概率的显式失败结果。
        """


class _SingularLinearSystem(Exception):
    """表示精确高斯消元没有找到非零主元。"""


@dataclass(frozen=True, slots=True)
class _NodeValues:
    """保存一个节点相对攻击方的概率和到吸收边界的期望步数。

    每条状态图边按一个完整回合计数；调用方必须使用完整回合级 expander
    构建待求解图，不能把回合内部阶段节点混入同一图中。

    Args:
        attacker_win: 从当前节点最终攻击方获胜的概率。
        defender_win: 从当前节点最终防守方获胜的概率。
        draw: 从当前节点最终平局的概率。
        closed_cycle: 从当前节点进入永不结束封闭 SCC 的概率。
        expected_steps_to_boundary: 到任一终局或封闭 SCC 边界的期望边数。
    """

    attacker_win: Fraction
    defender_win: Fraction
    draw: Fraction
    closed_cycle: Fraction
    expected_steps_to_boundary: Fraction


@dataclass(frozen=True, slots=True)
class PurePythonBattleGraphSolver:
    """使用纯 Python 与 ``Fraction`` 精确求解有限带权状态图。

    无环图优先使用逆拓扑动态规划；存在有出口循环时，针对全部非吸收节点
    建立 ``(I - Q)X = B`` 并使用精确高斯消元。无出口封闭 SCC 作为平局
    吸收边界，同时单独累计其概率，用于判断真实期望回合是否为无限。

    Args:
        max_equation_nodes: 允许进入高斯消元的非吸收节点上限；None 表示不限制。
            该限制不影响无环图的逆序动态规划路径。
    """

    max_equation_nodes: int | None = None

    def __post_init__(self) -> None:
        """拒绝布尔值、零值和负数方程规模限制。"""
        if self.max_equation_nodes is not None and (
            isinstance(self.max_equation_nodes, bool)
            or self.max_equation_nodes <= 0
        ):
            raise BattleGraphSolveError(
                "max_equation_nodes must be greater than 0"
            )

    @property
    def solver_id(self) -> str:
        """返回纯 Python 精确求解器的稳定版本标识。"""
        return "pure-python-exact-v1"

    def solve(
        self,
        graph: StateGraphBuildResult,
        observer: BattleSide = BattleSide.ATTACKER,
    ) -> BattleGraphSolveResult:
        """求解完整状态图；截断图只返回显式不完整状态。

        Args:
            graph: 节点 ID、边概率和 SCC 元数据均来自 #24 的状态图结果。
            observer: 胜负概率所采用的观察方。

        Returns:
            精确概率、封闭循环概率和期望回合语义；不完整、资源受限或
            奇异方程不会返回貌似完整的数字。

        Raises:
            BattleGraphSolveError: 图索引、边概率、非终局分布或观察方非法。
        """
        if not isinstance(graph, StateGraphBuildResult):
            raise BattleGraphSolveError("graph must be a StateGraphBuildResult")
        if not isinstance(observer, BattleSide):
            raise BattleGraphSolveError("observer must be a BattleSide")

        _validate_graph_structure(graph)
        if not graph.is_complete or any(
            node.outcome is GraphNodeOutcome.UNKNOWN for node in graph.nodes
        ):
            diagnostics = tuple(
                f"graph truncated: {reason.value}"
                for reason in graph.truncation_reasons
            )
            if not diagnostics:
                diagnostics = ("graph contains unknown nodes",)
            return BattleGraphSolveResult.unavailable(
                status=BattleGraphSolveStatus.INCOMPLETE_GRAPH,
                observer=observer,
                diagnostics=diagnostics,
            )

        closed_cycle_nodes = _closed_cycle_node_ids(graph)
        boundary_values = _build_boundary_values(graph, closed_cycle_nodes)
        transient_node_ids = tuple(
            node.node_id
            for node in graph.nodes
            if node.node_id not in boundary_values
        )
        outgoing = _build_outgoing_edges(graph)
        transient_order = _topological_order(transient_node_ids, outgoing)

        if transient_order is not None:
            values_by_node = _solve_acyclic_graph(
                graph,
                outgoing,
                boundary_values,
                transient_order,
            )
        else:
            if (
                self.max_equation_nodes is not None
                and len(transient_node_ids) > self.max_equation_nodes
            ):
                return BattleGraphSolveResult.unavailable(
                    status=BattleGraphSolveStatus.RESOURCE_LIMIT_EXCEEDED,
                    observer=observer,
                    diagnostics=(
                        "transient equation node count "
                        f"{len(transient_node_ids)} exceeds limit "
                        f"{self.max_equation_nodes}",
                    ),
                )
            try:
                values_by_node = _solve_cyclic_graph(
                    graph,
                    outgoing,
                    boundary_values,
                    transient_node_ids,
                )
            except _SingularLinearSystem:
                return BattleGraphSolveResult.unavailable(
                    status=BattleGraphSolveStatus.SINGULAR_SYSTEM,
                    observer=observer,
                    diagnostics=(
                        "exact absorption equation is singular; "
                        "check SCC classification and closed recurrent classes",
                    ),
                )

        root_values = values_by_node[graph.root_node_id]
        if observer is BattleSide.ATTACKER:
            win_probability = root_values.attacker_win
            loss_probability = root_values.defender_win
        else:
            win_probability = root_values.defender_win
            loss_probability = root_values.attacker_win

        expected_turns = (
            ExpectedTurns(ExpectedTurnsStatus.INFINITE)
            if root_values.closed_cycle > 0
            else ExpectedTurns(
                ExpectedTurnsStatus.FINITE,
                root_values.expected_steps_to_boundary,
            )
        )
        return BattleGraphSolveResult(
            status=BattleGraphSolveStatus.SOLVED,
            observer=observer,
            win_probability=win_probability,
            loss_probability=loss_probability,
            draw_probability=root_values.draw,
            closed_cycle_probability=root_values.closed_cycle,
            expected_turns=expected_turns,
        )


def _validate_graph_structure(graph: StateGraphBuildResult) -> None:
    """校验连续节点 ID、根节点、边端点和非终局概率分布。

    Args:
        graph: 待求解的状态图结果。

    Raises:
        BattleGraphSolveError: 图结构不连续、概率非法或非终局分布不守恒。
    """
    if not graph.nodes:
        raise BattleGraphSolveError("graph must contain at least one node")
    expected_node_ids = tuple(GraphNodeId(index) for index in range(len(graph.nodes)))
    actual_node_ids = tuple(node.node_id for node in graph.nodes)
    if actual_node_ids != expected_node_ids:
        raise BattleGraphSolveError("graph node IDs must be contiguous and ordered")
    if int(graph.root_node_id) < 0 or int(graph.root_node_id) >= len(graph.nodes):
        raise BattleGraphSolveError("root node ID is outside the graph")

    outgoing_totals = [Fraction(0, 1) for _ in graph.nodes]
    for edge in graph.edges:
        _validate_edge(edge, len(graph.nodes))
        outgoing_totals[int(edge.source_node_id)] += edge.probability
    for node in graph.nodes:
        if node.outcome is GraphNodeOutcome.NON_TERMINAL:
            total = outgoing_totals[int(node.node_id)]
            if total != Fraction(1, 1):
                raise BattleGraphSolveError(
                    f"non-terminal node {int(node.node_id)} outgoing probability "
                    f"must sum exactly to 1, got {total}"
                )


def _validate_edge(edge: StateGraphEdge, node_count: int) -> None:
    """校验一条边使用精确正概率并且端点位于当前图中。

    Args:
        edge: 待校验的带权有向边。
        node_count: 当前图的唯一节点数量。

    Raises:
        BattleGraphSolveError: 概率不是合法 Fraction 或端点越界。
    """
    if not isinstance(edge.probability, Fraction):
        raise BattleGraphSolveError("edge probability must use fractions.Fraction")
    if not 0 < edge.probability <= 1:
        raise BattleGraphSolveError("edge probability must be in the interval (0, 1]")
    for endpoint_name, node_id in (
        ("source", edge.source_node_id),
        ("target", edge.target_node_id),
    ):
        if int(node_id) < 0 or int(node_id) >= node_count:
            raise BattleGraphSolveError(
                f"edge {endpoint_name} node ID is outside the graph"
            )


def _closed_cycle_node_ids(graph: StateGraphBuildResult) -> frozenset[GraphNodeId]:
    """返回全部无出口封闭 SCC 的节点集合。

    Args:
        graph: 已完成 SCC 分类的状态图。

    Returns:
        需要作为数学平局吸收边界处理的节点 ID 集合。
    """
    return frozenset(
        node_id
        for component in graph.components
        if component.kind is StrongComponentKind.CLOSED_CYCLE
        for node_id in component.node_ids
    )


def _build_boundary_values(
    graph: StateGraphBuildResult,
    closed_cycle_nodes: frozenset[GraphNodeId],
) -> dict[GraphNodeId, _NodeValues]:
    """为胜、负、显式平局和封闭循环建立吸收边界值。

    Args:
        graph: 待求解状态图。
        closed_cycle_nodes: 无出口封闭 SCC 的全部节点。

    Returns:
        已具有确定概率向量的吸收节点映射。
    """
    values: dict[GraphNodeId, _NodeValues] = {}
    for node in graph.nodes:
        if node.outcome is GraphNodeOutcome.ATTACKER_WIN:
            values[node.node_id] = _NodeValues(
                Fraction(1), Fraction(0), Fraction(0), Fraction(0), Fraction(0)
            )
        elif node.outcome is GraphNodeOutcome.DEFENDER_WIN:
            values[node.node_id] = _NodeValues(
                Fraction(0), Fraction(1), Fraction(0), Fraction(0), Fraction(0)
            )
        elif node.outcome is GraphNodeOutcome.DRAW:
            closed_probability = (
                Fraction(1) if node.node_id in closed_cycle_nodes else Fraction(0)
            )
            values[node.node_id] = _NodeValues(
                Fraction(0),
                Fraction(0),
                Fraction(1),
                closed_probability,
                Fraction(0),
            )
        elif node.node_id in closed_cycle_nodes:
            # 图构建器在 SOLVE_ABSORPTION_PROBABILITY 模式下保留非终局节点。
            # 求解器仍需把无出口 SCC 作为平局边界，同时记录无限循环概率。
            values[node.node_id] = _NodeValues(
                Fraction(0), Fraction(0), Fraction(1), Fraction(1), Fraction(0)
            )
    return values


def _build_outgoing_edges(
    graph: StateGraphBuildResult,
) -> tuple[tuple[StateGraphEdge, ...], ...]:
    """按源节点索引全部出边，保留每条边的精确概率。

    Args:
        graph: 待求解状态图。

    Returns:
        下标与 ``GraphNodeId`` 一致的不可变出边表。
    """
    outgoing: list[list[StateGraphEdge]] = [[] for _ in graph.nodes]
    for edge in graph.edges:
        outgoing[int(edge.source_node_id)].append(edge)
    return tuple(tuple(edges) for edges in outgoing)


def _topological_order(
    transient_node_ids: tuple[GraphNodeId, ...],
    outgoing: tuple[tuple[StateGraphEdge, ...], ...],
) -> tuple[GraphNodeId, ...] | None:
    """尝试对非吸收子图做拓扑排序。

    Args:
        transient_node_ids: 仍需递推或解方程的节点 ID。
        outgoing: 全图按源节点索引的出边表。

    Returns:
        成功时返回从源到汇的拓扑顺序；存在回边时返回 None。
    """
    transient_set = set(transient_node_ids)
    indegree = {node_id: 0 for node_id in transient_node_ids}
    for source_node_id in transient_node_ids:
        for edge in outgoing[int(source_node_id)]:
            if edge.target_node_id in transient_set:
                indegree[edge.target_node_id] += 1

    queue: deque[GraphNodeId] = deque(
        node_id for node_id in transient_node_ids if indegree[node_id] == 0
    )
    ordered: list[GraphNodeId] = []
    while queue:
        node_id = queue.popleft()
        ordered.append(node_id)
        for edge in outgoing[int(node_id)]:
            if edge.target_node_id not in transient_set:
                continue
            indegree[edge.target_node_id] -= 1
            if indegree[edge.target_node_id] == 0:
                queue.append(edge.target_node_id)
    if len(ordered) != len(transient_node_ids):
        return None
    return tuple(ordered)


def _solve_acyclic_graph(
    graph: StateGraphBuildResult,
    outgoing: tuple[tuple[StateGraphEdge, ...], ...],
    boundary_values: dict[GraphNodeId, _NodeValues],
    transient_order: tuple[GraphNodeId, ...],
) -> dict[GraphNodeId, _NodeValues]:
    """使用逆拓扑动态规划求解无环非吸收子图。

    Args:
        graph: 待求解状态图。
        outgoing: 全图出边表。
        boundary_values: 已知吸收节点概率向量。
        transient_order: 非吸收节点从源到汇的拓扑顺序。

    Returns:
        覆盖全部节点的精确概率和期望步数映射。
    """
    values_by_node = dict(boundary_values)
    for node_id in reversed(transient_order):
        values_by_node[node_id] = _weighted_successor_values(
            outgoing[int(node_id)],
            values_by_node,
        )
    if graph.root_node_id not in values_by_node:
        raise BattleGraphSolveError("root node did not receive an acyclic solution")
    return values_by_node


def _weighted_successor_values(
    edges: tuple[StateGraphEdge, ...],
    values_by_node: dict[GraphNodeId, _NodeValues],
) -> _NodeValues:
    """按出边概率汇总后继值，并为当前非吸收节点增加一个回合。

    Args:
        edges: 当前节点的完整精确后继分布。
        values_by_node: 已经求出的后继节点值。

    Returns:
        当前节点的胜负平概率、封闭循环概率和期望步数。
    """
    attacker_win = Fraction(0)
    defender_win = Fraction(0)
    draw = Fraction(0)
    closed_cycle = Fraction(0)
    expected_steps = Fraction(1)
    for edge in edges:
        successor = values_by_node[edge.target_node_id]
        attacker_win += edge.probability * successor.attacker_win
        defender_win += edge.probability * successor.defender_win
        draw += edge.probability * successor.draw
        closed_cycle += edge.probability * successor.closed_cycle
        expected_steps += edge.probability * successor.expected_steps_to_boundary
    return _NodeValues(
        attacker_win,
        defender_win,
        draw,
        closed_cycle,
        expected_steps,
    )


def _solve_cyclic_graph(
    graph: StateGraphBuildResult,
    outgoing: tuple[tuple[StateGraphEdge, ...], ...],
    boundary_values: dict[GraphNodeId, _NodeValues],
    transient_node_ids: tuple[GraphNodeId, ...],
) -> dict[GraphNodeId, _NodeValues]:
    """建立并精确求解有出口循环的吸收概率方程。

    Args:
        graph: 待求解状态图。
        outgoing: 全图出边表。
        boundary_values: 胜、负、平和封闭循环吸收边界。
        transient_node_ids: 需要进入 ``(I - Q)X = B`` 的节点。

    Returns:
        覆盖全部节点的精确概率和到吸收边界期望步数。

    Raises:
        _SingularLinearSystem: 非吸收子图仍包含未识别的封闭常返类。
    """
    index_by_node = {
        node_id: index for index, node_id in enumerate(transient_node_ids)
    }
    matrix = [
        [Fraction(int(row == column)) for column in range(len(transient_node_ids))]
        for row in range(len(transient_node_ids))
    ]
    right_hand_sides = [
        [Fraction(0) for _ in range(5)] for _ in transient_node_ids
    ]
    for row, node_id in enumerate(transient_node_ids):
        right_hand_sides[row][4] = Fraction(1)
        for edge in outgoing[int(node_id)]:
            target_index = index_by_node.get(edge.target_node_id)
            if target_index is not None:
                matrix[row][target_index] -= edge.probability
                continue
            boundary = boundary_values[edge.target_node_id]
            right_hand_sides[row][0] += edge.probability * boundary.attacker_win
            right_hand_sides[row][1] += edge.probability * boundary.defender_win
            right_hand_sides[row][2] += edge.probability * boundary.draw
            right_hand_sides[row][3] += edge.probability * boundary.closed_cycle

    solutions = _gaussian_elimination(matrix, right_hand_sides)
    values_by_node = dict(boundary_values)
    for row, node_id in enumerate(transient_node_ids):
        values_by_node[node_id] = _NodeValues(
            attacker_win=solutions[row][0],
            defender_win=solutions[row][1],
            draw=solutions[row][2],
            closed_cycle=solutions[row][3],
            expected_steps_to_boundary=solutions[row][4],
        )
    if graph.root_node_id not in values_by_node:
        raise BattleGraphSolveError("root node did not receive a cyclic solution")
    return values_by_node


def _gaussian_elimination(
    matrix: list[list[Fraction]],
    right_hand_sides: list[list[Fraction]],
) -> tuple[tuple[Fraction, ...], ...]:
    """使用全消元形式的精确高斯消元求解多个右端向量。

    Args:
        matrix: 方形系数矩阵；函数会复制后消元，不修改调用方列表。
        right_hand_sides: 与矩阵行数一致的一个或多个右端列。

    Returns:
        每行对应一个未知量、每列对应一个右端向量的精确解。

    Raises:
        BattleGraphSolveError: 矩阵或右端维度不一致。
        _SingularLinearSystem: 某一列无法找到非零主元。
    """
    size = len(matrix)
    if size == 0:
        return ()
    if any(len(row) != size for row in matrix):
        raise BattleGraphSolveError("linear coefficient matrix must be square")
    if len(right_hand_sides) != size:
        raise BattleGraphSolveError("linear right-hand side row count must match")
    rhs_width = len(right_hand_sides[0])
    if rhs_width == 0 or any(len(row) != rhs_width for row in right_hand_sides):
        raise BattleGraphSolveError("linear right-hand sides must have equal width")

    augmented = [
        list(matrix[row]) + list(right_hand_sides[row]) for row in range(size)
    ]
    width = size + rhs_width
    for pivot_column in range(size):
        pivot_row = next(
            (
                row
                for row in range(pivot_column, size)
                if augmented[row][pivot_column] != 0
            ),
            None,
        )
        if pivot_row is None:
            raise _SingularLinearSystem
        if pivot_row != pivot_column:
            augmented[pivot_column], augmented[pivot_row] = (
                augmented[pivot_row],
                augmented[pivot_column],
            )

        pivot = augmented[pivot_column][pivot_column]
        for column in range(pivot_column, width):
            augmented[pivot_column][column] /= pivot
        for row in range(size):
            if row == pivot_column:
                continue
            factor = augmented[row][pivot_column]
            if factor == 0:
                continue
            for column in range(pivot_column, width):
                augmented[row][column] -= factor * augmented[pivot_column][column]

    return tuple(tuple(augmented[row][size:]) for row in range(size))


__all__ = [
    "BattleGraphSolveError",
    "BattleGraphSolveResult",
    "BattleGraphSolveStatus",
    "BattleGraphSolver",
    "ExpectedTurns",
    "ExpectedTurnsStatus",
    "PurePythonBattleGraphSolver",
]
