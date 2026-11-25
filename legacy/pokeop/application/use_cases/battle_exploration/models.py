"""定义渐进探索 use cases 返回的不可变 application DTO。"""

from __future__ import annotations

from dataclasses import dataclass

from pokeop.application.state_graph_exploration import ExplorationCursor
from pokeop.application.state_graph_projection import (
    BattleNodeDetail,
    ProbabilityProjection,
    TransitionEventPathDetail,
    TransitionGroup,
)


@dataclass(frozen=True, slots=True)
class BattleExplorationPosition:
    """保存一次探索操作完成后的游标、节点和精确累计概率。

    Args:
        graph_id: 当前已保存状态图的稳定标识。
        calculation_revision: 图 artifact 使用的计算语义版本。
        cursor: 从根节点开始的真实 edge 序列。
        node: cursor 当前节点的 JSON 友好详情。
        cumulative_probability: 根到当前 cursor 的精确概率投影。
    """

    graph_id: str
    calculation_revision: str
    cursor: ExplorationCursor
    node: BattleNodeDetail
    cumulative_probability: ProbabilityProjection


@dataclass(frozen=True, slots=True)
class BattleTransitionGroupsResult:
    """保存当前节点位置以及真正按摘要读取的折叠分支组。"""

    position: BattleExplorationPosition
    transition_groups: tuple[TransitionGroup, ...]


@dataclass(frozen=True, slots=True)
class BattleTransitionGroupOutcomesResult:
    """保存当前节点位置和调用方明确请求展开的单个分支组。"""

    position: BattleExplorationPosition
    transition_group: TransitionGroup


@dataclass(frozen=True, slots=True)
class BattleReportStep:
    """保存 cursor 中一条实际选择边对应的结构化战报阶段。

    ``event_paths`` 只表示同一正式边保留的替代事件解释，不与其他步骤做
    笛卡尔积。该合同既保留状态归并前的事实，也避免长路径产生指数级报告体积。
    """

    depth: int
    source_node_id: int
    edge_id: int
    target_node_id: int
    edge_probability: ProbabilityProjection
    cumulative_probability: ProbabilityProjection
    event_paths: tuple[TransitionEventPathDetail, ...]


@dataclass(frozen=True, slots=True)
class BattleReport:
    """按照用户实际 edge 序列保存可重复节点的完整结构化战报。"""

    graph_id: str
    calculation_revision: str
    root_node_id: int
    current_node_id: int
    depth: int
    cumulative_probability: ProbabilityProjection
    steps: tuple[BattleReportStep, ...]
