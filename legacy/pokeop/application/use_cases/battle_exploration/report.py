"""按照真实 exploration cursor 构建结构化战斗报告。"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from pokeop.application import state_graph_projection as projection
from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.application.state_graph_exploration import ExplorationCursor
from pokeop.application.state_graph_projection import ProbabilityProjection
from pokeop.application.use_cases.battle_exploration._support import (
    edge_by_id,
    load_context,
    node_by_id,
    require_graph_store,
    validate_cursor,
)
from pokeop.application.use_cases.battle_exploration.models import (
    BattleReport,
    BattleReportStep,
)


@dataclass(frozen=True, slots=True)
class BuildBattleReportUseCase:
    """按照 cursor.steps 的 edge 顺序构造不依赖代表前驱的结构化战报。"""

    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验依赖实现 application 定义的可替换图存储端口。"""
        require_graph_store(self.graph_store)

    def execute(
        self,
        graph_id: str,
        calculation_revision: str,
        cursor: ExplorationCursor,
    ) -> BattleReport:
        """逐边读取用户实际路径并保留每条边的全部替代事件解释。

        Args:
            graph_id: 当前已保存状态图的稳定标识。
            calculation_revision: 调用方支持的精确计算语义版本。
            cursor: 从根节点开始、允许合流和循环回边的真实边序列。

        Returns:
            按 cursor 深度排序的结构化步骤，以及逐边 ``Fraction`` 累乘的总概率。

        Notes:
            战报不会读取 ``StateGraphNode.predecessor_*``，也不会把不同 edge 的替代
            event path 组合成全局笛卡尔积，因此循环路径和长路径仍保持线性步骤规模。
        """
        context = load_context(
            self.graph_store,
            graph_id=graph_id,
            calculation_revision=calculation_revision,
        )
        validate_cursor(context, cursor)

        cumulative_probability = Fraction(1, 1)
        report_steps: list[BattleReportStep] = []
        for depth, cursor_step in enumerate(cursor.steps, start=1):
            edge = edge_by_id(context, cursor_step.edge_id)
            source_node = node_by_id(context, cursor_step.source_node_id)
            cumulative_probability *= edge.probability
            event_paths = tuple(
                projection._event_path_detail(node=source_node, path=path)
                for path in edge.event_summary.paths
            )
            report_steps.append(
                BattleReportStep(
                    depth=depth,
                    source_node_id=int(edge.source_node_id),
                    edge_id=int(edge.edge_id),
                    target_node_id=int(edge.target_node_id),
                    edge_probability=ProbabilityProjection.from_fraction(
                        edge.probability
                    ),
                    cumulative_probability=ProbabilityProjection.from_fraction(
                        cumulative_probability
                    ),
                    event_paths=event_paths,
                )
            )

        return BattleReport(
            graph_id=graph_id,
            calculation_revision=calculation_revision,
            root_node_id=int(cursor.root_node_id),
            current_node_id=int(cursor.current_node_id),
            depth=cursor.depth,
            cumulative_probability=ProbabilityProjection.from_fraction(
                cumulative_probability
            ),
            steps=tuple(report_steps),
        )
