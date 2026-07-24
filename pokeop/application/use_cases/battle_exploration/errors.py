"""定义状态图渐进探索可由 API 稳定映射的 application 异常。"""

from __future__ import annotations

from pokeop.application.solver.models import GraphEdgeId, GraphNodeId


class BattleExplorationUseCaseError(RuntimeError):
    """表示渐进探索 application 编排无法完成稳定业务操作。"""


class IncompatibleCalculationRevisionError(BattleExplorationUseCaseError):
    """表示调用方请求的计算版本与已保存图的版本不兼容。"""

    def __init__(
        self,
        graph_id: str,
        requested_revision: str,
        stored_revision: str,
    ) -> None:
        """保存冲突版本，供未来 API 层生成结构化错误响应。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            requested_revision: 调用方认为兼容的计算版本。
            stored_revision: 图 artifact 实际保存的计算版本。
        """
        self.graph_id = graph_id
        self.requested_revision = requested_revision
        self.stored_revision = stored_revision
        super().__init__(
            "battle graph calculation revision mismatch: "
            f"requested {requested_revision!r}, stored {stored_revision!r}"
        )


class BattleNodeNotFoundError(BattleExplorationUseCaseError):
    """表示游标或图句柄指向的节点不存在于完整图。"""

    def __init__(self, graph_id: str, node_id: GraphNodeId) -> None:
        """保存缺失节点信息。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            node_id: 无法读取的节点 ID。
        """
        self.graph_id = graph_id
        self.node_id = int(node_id)
        super().__init__(
            f"battle graph {graph_id!r} does not contain node {int(node_id)}"
        )


class TransitionGroupNotFoundError(BattleExplorationUseCaseError):
    """表示指定分支组不属于游标当前节点。"""

    def __init__(
        self,
        graph_id: str,
        node_id: GraphNodeId,
        group_id: str,
    ) -> None:
        """保存缺失分支组及其 source node。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            node_id: 调用方尝试展开分支组时所在节点。
            group_id: 未在当前节点找到的稳定分支组 ID。
        """
        self.graph_id = graph_id
        self.node_id = int(node_id)
        self.group_id = group_id
        super().__init__(
            f"transition group {group_id!r} was not found on node {int(node_id)}"
        )


class EdgeNotInCurrentNodeError(BattleExplorationUseCaseError):
    """表示请求边不存在，或不是游标当前节点的一条正式出边。"""

    def __init__(
        self,
        graph_id: str,
        current_node_id: GraphNodeId,
        edge_id: GraphEdgeId,
    ) -> None:
        """保存非法边和当前 source node。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            current_node_id: 前进一步前的游标当前节点。
            edge_id: 调用方请求选择的正式边 ID。
        """
        self.graph_id = graph_id
        self.current_node_id = int(current_node_id)
        self.edge_id = int(edge_id)
        super().__init__(
            f"edge {int(edge_id)} does not leave current node "
            f"{int(current_node_id)} in graph {graph_id!r}"
        )


class InvalidExplorationCursorError(BattleExplorationUseCaseError):
    """表示游标跨图、根节点错误或边序列与完整图不连续。"""

    def __init__(self, graph_id: str, reason: str) -> None:
        """保存非法游标的稳定诊断文本。

        Args:
            graph_id: 当前读取的已保存状态图标识。
            reason: 原始 cursor 合同给出的可诊断原因。
        """
        self.graph_id = graph_id
        self.reason = reason
        super().__init__(f"invalid exploration cursor for graph {graph_id!r}: {reason}")


class TerminalBattleNodeAdvanceError(BattleExplorationUseCaseError):
    """表示调用方尝试从已经终局的节点继续前进。"""

    def __init__(self, graph_id: str, node_id: GraphNodeId) -> None:
        """保存禁止继续前进的终局节点。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            node_id: 已经具有终局语义的当前节点 ID。
        """
        self.graph_id = graph_id
        self.node_id = int(node_id)
        super().__init__(
            f"terminal node {int(node_id)} in graph {graph_id!r} cannot advance"
        )
