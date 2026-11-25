"""提供基于有序边序列的状态图探索游标与不可变导航行为。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphError,
    StateGraphNode,
)


class ExplorationCursorError(ValueError):
    """表示状态图探索游标违反 application 层稳定合同。"""


class ExplorationGraphMismatchError(ExplorationCursorError):
    """表示游标所属图与当前探索用例绑定的图不一致。"""


class ExplorationPathError(ExplorationCursorError):
    """表示游标中的根节点、步骤连续性或边映射不合法。"""


class ExplorationEdgeError(ExplorationCursorError):
    """表示请求的边不存在，或不是当前节点的一条合法出边。"""


class ExplorationDepthError(ExplorationCursorError):
    """表示回退或祖先截断深度超出当前路径范围。"""


@dataclass(frozen=True, slots=True)
class ExplorationPathStep:
    """记录用户实际选择的一条图边及其两端节点。

    Args:
        source_node_id: 当前步骤开始时所在的图节点 ID，必须为非负整数。
        edge_id: 用户选择的图边 ID，必须为非负整数。
        target_node_id: 当前步骤结束后到达的图节点 ID，必须为非负整数。
    """

    source_node_id: GraphNodeId
    edge_id: GraphEdgeId
    target_node_id: GraphNodeId

    def __post_init__(self) -> None:
        """拒绝不能稳定定位图元素的负数、布尔值和非整数 ID。

        Raises:
            ExplorationPathError: 任一节点或边 ID 不是合法非负整数时抛出。
        """
        _require_non_negative_id("source_node_id", self.source_node_id)
        _require_non_negative_id("edge_id", self.edge_id)
        _require_non_negative_id("target_node_id", self.target_node_id)


@dataclass(frozen=True, slots=True)
class ExplorationCursor:
    """使用根节点和有序边步骤表达一条真实用户浏览路径。

    游标故意不保存节点的 ``predecessor_*`` 字段，也不限制节点或边重复出现，
    因此状态合流和循环回边都能保留用户实际选择的路径。

    Args:
        graph_id: 当前路径所属图的稳定 application 标识，必须非空且已规范化。
        root_node_id: 路径起点的图根节点 ID。
        steps: 从根节点开始按选择顺序保存的不可变边步骤。
    """

    graph_id: str
    root_node_id: GraphNodeId
    steps: tuple[ExplorationPathStep, ...] = ()

    def __post_init__(self) -> None:
        """校验图标识、根节点和相邻步骤能够组成一条连续路径。

        Raises:
            ExplorationPathError: 图标识、根节点、步骤类型或步骤连续性非法时抛出。
        """
        _require_graph_id(self.graph_id)
        _require_non_negative_id("root_node_id", self.root_node_id)
        if not isinstance(self.steps, tuple):
            raise ExplorationPathError("steps must be an immutable tuple")

        expected_source = self.root_node_id
        for index, step in enumerate(self.steps):
            if not isinstance(step, ExplorationPathStep):
                raise ExplorationPathError(
                    f"steps[{index}] must be ExplorationPathStep"
                )
            if step.source_node_id != expected_source:
                raise ExplorationPathError(
                    "exploration path is discontinuous at "
                    f"depth {index}: expected source {int(expected_source)}, "
                    f"got {int(step.source_node_id)}"
                )
            expected_source = step.target_node_id

    @property
    def depth(self) -> int:
        """返回当前路径包含的边数量；根游标深度为 0。"""
        return len(self.steps)

    @property
    def current_node_id(self) -> GraphNodeId:
        """返回当前路径最终到达的节点；空路径返回根节点。"""
        if not self.steps:
            return self.root_node_id
        return self.steps[-1].target_node_id

    def back(self) -> ExplorationCursor:
        """返回移除最后一步的新游标。

        Returns:
            深度减少 1 的新不可变游标。

        Raises:
            ExplorationDepthError: 当前游标已经位于根节点时抛出。
        """
        if not self.steps:
            raise ExplorationDepthError("cannot move back from the root cursor")
        return ExplorationCursor(
            graph_id=self.graph_id,
            root_node_id=self.root_node_id,
            steps=self.steps[:-1],
        )

    def truncate(self, depth: int) -> ExplorationCursor:
        """跳回指定祖先深度并返回新的不可变游标。

        Args:
            depth: 需要保留的边数量，必须位于 ``0..current_depth``。

        Returns:
            仅保留前 ``depth`` 个步骤的新游标；0 表示根游标。

        Raises:
            ExplorationDepthError: 深度不是整数或超出当前路径范围时抛出。
        """
        if isinstance(depth, bool) or not isinstance(depth, int):
            raise ExplorationDepthError("depth must be an integer")
        if depth < 0 or depth > self.depth:
            raise ExplorationDepthError(
                f"depth {depth} is outside 0..{self.depth}"
            )
        return ExplorationCursor(
            graph_id=self.graph_id,
            root_node_id=self.root_node_id,
            steps=self.steps[:depth],
        )


@dataclass(frozen=True, slots=True)
class StateGraphExplorationUseCase:
    """在一份完整状态图上校验并执行用户路径导航。

    该 application 用例只读取 ``StateGraphBuildResult``，不依赖 HTTP、DOM、
    组件实例、graph store 或节点首次发现前驱。

    Args:
        graph_id: 调用方为当前图分配的稳定标识，用于拒绝跨图游标。
        graph: #52 保留在 application 层的完整状态图 artifact。
    """

    graph_id: str
    graph: StateGraphBuildResult

    def __post_init__(self) -> None:
        """校验图标识、artifact 类型和根节点能够被稳定读取。

        Raises:
            ExplorationPathError: 图标识、artifact 或根节点合同非法时抛出。
        """
        _require_graph_id(self.graph_id)
        if not isinstance(self.graph, StateGraphBuildResult):
            raise ExplorationPathError("graph must be StateGraphBuildResult")
        try:
            self.graph.node(self.graph.root_node_id)
        except StateGraphError as error:
            raise ExplorationPathError("graph root node is invalid") from error

    def create_root_cursor(self) -> ExplorationCursor:
        """从当前图根节点创建深度为 0 的新游标。

        Returns:
            绑定当前 ``graph_id`` 和图根节点的不可变游标。
        """
        return ExplorationCursor(
            graph_id=self.graph_id,
            root_node_id=self.graph.root_node_id,
        )

    def advance(
        self,
        cursor: ExplorationCursor,
        edge_id: GraphEdgeId,
    ) -> ExplorationCursor:
        """沿当前节点的一条合法出边前进一步。

        Args:
            cursor: 当前用户路径，必须属于本用例绑定的同一份图。
            edge_id: 待选择的图边 ID，必须从 ``cursor.current_node_id`` 出发。

        Returns:
            在原步骤末尾追加一条边的新不可变游标；原游标保持不变。

        Raises:
            ExplorationCursorError: 游标非法、跨图、边不存在或不是当前出边时抛出。
        """
        self.validate(cursor)
        edge = self._edge(edge_id)
        if edge.source_node_id != cursor.current_node_id:
            raise ExplorationEdgeError(
                f"edge {int(edge.edge_id)} does not leave current node "
                f"{int(cursor.current_node_id)}"
            )
        return ExplorationCursor(
            graph_id=cursor.graph_id,
            root_node_id=cursor.root_node_id,
            steps=cursor.steps
            + (
                ExplorationPathStep(
                    source_node_id=edge.source_node_id,
                    edge_id=edge.edge_id,
                    target_node_id=edge.target_node_id,
                ),
            ),
        )

    def back(self, cursor: ExplorationCursor) -> ExplorationCursor:
        """校验游标属于当前图后返回其上一级路径。

        Args:
            cursor: 需要回退一步的当前用户路径。

        Returns:
            深度减少 1 的新不可变游标。

        Raises:
            ExplorationCursorError: 游标非法、跨图或已位于根节点时抛出。
        """
        self.validate(cursor)
        return cursor.back()

    def truncate(
        self,
        cursor: ExplorationCursor,
        depth: int,
    ) -> ExplorationCursor:
        """校验游标属于当前图后跳回指定祖先深度。

        Args:
            cursor: 需要跳转的当前用户路径。
            depth: 需要保留的边数量，0 表示图根节点。

        Returns:
            保留前 ``depth`` 个步骤的新不可变游标。

        Raises:
            ExplorationCursorError: 游标非法、跨图或深度越界时抛出。
        """
        self.validate(cursor)
        return cursor.truncate(depth)

    def current_node(self, cursor: ExplorationCursor) -> StateGraphNode:
        """读取游标当前所在的正式状态图节点。

        Args:
            cursor: 需要读取当前位置的同图合法游标。

        Returns:
            ``cursor.current_node_id`` 对应的不可变 ``StateGraphNode``。

        Raises:
            ExplorationCursorError: 游标非法、跨图或节点不存在时抛出。
        """
        self.validate(cursor)
        try:
            return self.graph.node(cursor.current_node_id)
        except StateGraphError as error:
            raise ExplorationPathError(
                f"current node {int(cursor.current_node_id)} is outside the graph"
            ) from error

    def cumulative_probability(self, cursor: ExplorationCursor) -> Fraction:
        """计算根节点到当前步骤的精确累计路径概率。

        Args:
            cursor: 需要计算概率的同图合法游标。

        Returns:
            逐边概率相乘得到的 ``Fraction``；根游标返回 ``Fraction(1, 1)``。

        Raises:
            ExplorationCursorError: 游标非法、跨图或任一步骤不属于图时抛出。
        """
        edges = self._validated_edges(cursor)
        probability = Fraction(1, 1)
        for edge in edges:
            probability *= edge.probability
        return probability

    def validate(self, cursor: ExplorationCursor) -> None:
        """验证游标完整路径与当前图的根、节点和边严格一致。

        Args:
            cursor: 待验证的不可变探索游标。

        Raises:
            ExplorationCursorError: 类型、图标识、根节点或任一步骤不合法时抛出。
        """
        self._validated_edges(cursor)

    def _validated_edges(
        self,
        cursor: ExplorationCursor,
    ) -> tuple[StateGraphEdge, ...]:
        """校验游标并返回与每个步骤一一对应的正式图边。

        Args:
            cursor: 待校验的探索游标。

        Returns:
            与 ``cursor.steps`` 同序的不可变正式图边元组。

        Raises:
            ExplorationCursorError: 游标不属于当前图或步骤映射不一致时抛出。
        """
        if not isinstance(cursor, ExplorationCursor):
            raise ExplorationPathError("cursor must be ExplorationCursor")
        if cursor.graph_id != self.graph_id:
            raise ExplorationGraphMismatchError(
                f"cursor graph_id {cursor.graph_id!r} does not match "
                f"{self.graph_id!r}"
            )
        if cursor.root_node_id != self.graph.root_node_id:
            raise ExplorationPathError(
                f"cursor root {int(cursor.root_node_id)} does not match graph root "
                f"{int(self.graph.root_node_id)}"
            )

        validated_edges: list[StateGraphEdge] = []
        for depth, step in enumerate(cursor.steps):
            edge = self._edge(step.edge_id)
            if (
                edge.source_node_id != step.source_node_id
                or edge.target_node_id != step.target_node_id
            ):
                raise ExplorationPathError(
                    f"step at depth {depth} does not match edge "
                    f"{int(step.edge_id)}"
                )
            self._node(step.source_node_id)
            self._node(step.target_node_id)
            validated_edges.append(edge)
        return tuple(validated_edges)

    def _edge(self, edge_id: GraphEdgeId) -> StateGraphEdge:
        """按连续边 ID 读取正式图边并转换为稳定探索异常。

        Args:
            edge_id: 需要读取的边 ID，必须是非负整数并位于图边范围内。

        Returns:
            对应的不可变 ``StateGraphEdge``。

        Raises:
            ExplorationEdgeError: 边 ID 类型、范围或图内连续索引合同非法时抛出。
        """
        try:
            _require_non_negative_id("edge_id", edge_id)
        except ExplorationPathError as error:
            raise ExplorationEdgeError(str(error)) from error
        index = int(edge_id)
        if index >= len(self.graph.edges):
            raise ExplorationEdgeError(f"edge_id {index} is outside the graph")
        edge = self.graph.edges[index]
        if int(edge.edge_id) != index:
            raise ExplorationEdgeError(
                f"graph edge index {index} contains edge_id {int(edge.edge_id)}"
            )
        return edge

    def _node(self, node_id: GraphNodeId) -> StateGraphNode:
        """按节点 ID 读取正式图节点并转换为稳定探索异常。

        Args:
            node_id: 需要读取的节点 ID。

        Returns:
            对应的不可变 ``StateGraphNode``。

        Raises:
            ExplorationPathError: 节点不属于当前图时抛出。
        """
        try:
            return self.graph.node(node_id)
        except StateGraphError as error:
            raise ExplorationPathError(
                f"node_id {int(node_id)} is outside the graph"
            ) from error


def _require_graph_id(graph_id: str) -> None:
    """校验图标识是非空且未携带首尾空白的字符串。

    Args:
        graph_id: application 调用方为一份状态图分配的标识。

    Raises:
        ExplorationPathError: 图标识类型错误、为空或未规范化时抛出。
    """
    if (
        not isinstance(graph_id, str)
        or not graph_id
        or graph_id != graph_id.strip()
    ):
        raise ExplorationPathError("graph_id must be non-empty and normalized")


def _require_non_negative_id(field_name: str, value: object) -> None:
    """校验图节点或边 ID 是非负整数，并显式拒绝布尔值。

    Args:
        field_name: 用于稳定错误消息的字段名称。
        value: 待校验的运行期值。

    Raises:
        ExplorationPathError: 值不是合法非负整数时抛出。
    """
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExplorationPathError(
            f"{field_name} must be a non-negative integer"
        )


__all__ = [
    "ExplorationCursor",
    "ExplorationCursorError",
    "ExplorationDepthError",
    "ExplorationEdgeError",
    "ExplorationGraphMismatchError",
    "ExplorationPathError",
    "ExplorationPathStep",
    "StateGraphExplorationUseCase",
]
