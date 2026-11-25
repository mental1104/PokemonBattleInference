"""实现状态图根读取、分支展开、前进与回退的窄 application use cases。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.application.solver.models import GraphEdgeId
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationCursorError,
    ExplorationEdgeError,
)
from pokeop.application.use_cases.battle_exploration._support import (
    current_node,
    expand_group,
    list_group_summaries,
    load_context,
    outgoing_edges,
    position,
    require_graph_store,
    require_identifier,
)
from pokeop.application.use_cases.battle_exploration.errors import (
    EdgeNotInCurrentNodeError,
    InvalidExplorationCursorError,
    TerminalBattleNodeAdvanceError,
)
from pokeop.application.use_cases.battle_exploration.models import (
    BattleExplorationPosition,
    BattleTransitionGroupOutcomesResult,
    BattleTransitionGroupsResult,
)


@dataclass(frozen=True, slots=True)
class LoadBattleNodeUseCase:
    """从 graph store 加载根节点或合法 cursor 的当前节点详情。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def load_root(
        self,
        graph_id: str,
        calculation_revision: str,
    ) -> BattleExplorationPosition:
        """创建根游标并加载根节点，不要求调用方伪造空路径。

        Args:
            graph_id: ``BattleGraphStore.put`` 返回的稳定图标识。
            calculation_revision: 调用方支持的精确计算语义版本。

        Returns:
            深度为 0 的游标、根节点详情和概率 1。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        return position(context, context.explorer.create_root_cursor())

    def load_current(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
    ) -> BattleExplorationPosition:
        """校验真实边序列后加载 cursor 当前节点。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 从同一图根节点开始的不可变实际边序列。

        Returns:
            原 cursor、当前节点详情和逐边相乘的精确累计概率投影。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        return position(context, cursor)


@dataclass(frozen=True, slots=True)
class ListTransitionGroupsUseCase:
    """只读取当前节点分支统计，不构造任何 ``TransitionOutcome``。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def execute(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
    ) -> BattleTransitionGroupsResult:
        """列出当前节点默认折叠的全部分支组。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 决定当前 source node 的真实边序列。

        Returns:
            当前节点位置与 ``outcomes=()`` 的稳定分支组摘要。

        Notes:
            该路径只读取边概率、事件路径数量和伤害摘要。完整 outcome、标签字段与
            battle event path 仅在 ``LoadTransitionGroupOutcomesUseCase`` 中构造。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        current_position = position(context, cursor)
        node = current_node(context, cursor)
        return BattleTransitionGroupsResult(
            position=current_position,
            transition_groups=list_group_summaries(
                node,
                outgoing_edges(context.graph, node.node_id),
            ),
        )


@dataclass(frozen=True, slots=True)
class LoadTransitionGroupOutcomesUseCase:
    """只为调用方明确指定的当前节点分支组构造 outcome 详情。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def execute(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
        group_id: str,
    ) -> BattleTransitionGroupOutcomesResult:
        """展开当前 source node 中唯一匹配的分支组。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 决定当前 source node 和累计概率的真实边序列。
            group_id: group 列表返回的稳定分支组 ID。

        Returns:
            当前节点位置和 ``expanded=True`` 的单个分支组。
        """
        require_identifier(group_id, "group_id")
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        current_position = position(context, cursor)
        node = current_node(context, cursor)
        group = expand_group(
            graph_id=graph_id,
            node=node,
            edges=outgoing_edges(context.graph, node.node_id),
            cumulative_probability=context.explorer.cumulative_probability(cursor),
            group_id=group_id,
        )
        return BattleTransitionGroupOutcomesResult(
            position=current_position,
            transition_group=group,
        )


@dataclass(frozen=True, slots=True)
class AdvanceBattleExplorationUseCase:
    """验证终局和当前出边后，沿指定正式边生成新游标。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def execute(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
        edge_id: GraphEdgeId,
    ) -> BattleExplorationPosition:
        """从 cursor 当前节点沿一条正式出边前进一步。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 前进前的真实边序列。
            edge_id: 必须从 cursor 当前节点出发的正式边 ID。

        Returns:
            追加该边后的新游标、目标节点详情和新累计概率。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        node = current_node(context, cursor)
        if node.is_terminal:
            # 终局语义优先于边合法性，避免 API 把“战斗结束”误报为普通非法边。
            raise TerminalBattleNodeAdvanceError(graph_id, node.node_id)
        try:
            advanced = context.explorer.advance(cursor, edge_id)
        except ExplorationEdgeError as error:
            raise EdgeNotInCurrentNodeError(
                graph_id,
                cursor.current_node_id,
                edge_id,
            ) from error
        except ExplorationCursorError as error:
            raise InvalidExplorationCursorError(graph_id, str(error)) from error
        return position(context, advanced)


@dataclass(frozen=True, slots=True)
class BacktrackBattleExplorationUseCase:
    """基于 cursor 的实际 edge prefix 返回上一级或任意祖先深度。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def back(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
    ) -> BattleExplorationPosition:
        """移除 cursor 最后一步并返回上一级节点。"""
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        try:
            backtracked = context.explorer.back(cursor)
        except ExplorationCursorError as error:
            raise InvalidExplorationCursorError(graph_id, str(error)) from error
        return position(context, backtracked)

    def truncate(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
        depth: int,
    ) -> BattleExplorationPosition:
        """保留 cursor 前 ``depth`` 条边并跳回对应祖先。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 当前完整真实边序列。
            depth: 需要保留的边数量，0 表示根节点。

        Returns:
            以 cursor edge prefix 表达的新祖先位置；重复节点不会被特殊处理。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        try:
            truncated = context.explorer.truncate(cursor, depth)
        except ExplorationCursorError as error:
            raise InvalidExplorationCursorError(graph_id, str(error)) from error
        return position(context, truncated)
