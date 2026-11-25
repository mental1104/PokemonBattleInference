from __future__ import annotations

from collections import deque
from dataclasses import replace

from pokeop.domain.battle.inference_outcome import TerminationReason
from pokeop.domain.battle.inference_rules import CycleResolution

from .models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphEdge,
    StateGraphNode,
    StrongComponent,
    StrongComponentId,
    StrongComponentKind,
)


def analyze_strong_components(
    nodes: list[StateGraphNode],
    edges: list[StateGraphEdge],
) -> tuple[StrongComponent, ...]:
    """使用迭代 Kosaraju 算法识别全部强连通分量。

    Args:
        nodes: 已完成 BFS 构建的连续节点列表。
        edges: 已完成 BFS 构建的连续有向边列表。

    Returns:
        覆盖全部节点的 SCC 元组；算法只使用显式栈，不依赖递归调用深度。
    """
    adjacency, reverse_adjacency = _build_adjacency(len(nodes), edges)
    finish_order = _iterative_finish_order(adjacency)
    component_members = _collect_reverse_components(
        reverse_adjacency,
        finish_order,
    )
    component_by_node: dict[GraphNodeId, StrongComponentId] = {}
    for component_id, members in enumerate(component_members):
        typed_component_id = StrongComponentId(component_id)
        for node_id in members:
            component_by_node[node_id] = typed_component_id

    outgoing_by_component: list[set[StrongComponentId]] = [
        set() for _ in component_members
    ]
    has_self_loop = [False for _ in component_members]
    for edge in edges:
        source_component = component_by_node[edge.source_node_id]
        target_component = component_by_node[edge.target_node_id]
        if source_component == target_component:
            if edge.source_node_id == edge.target_node_id:
                has_self_loop[int(source_component)] = True
            continue
        outgoing_by_component[int(source_component)].add(target_component)

    cyclic = tuple(
        len(members) > 1 or has_self_loop[component_id]
        for component_id, members in enumerate(component_members)
    )
    closed_components = {
        StrongComponentId(component_id)
        for component_id, is_cyclic in enumerate(cyclic)
        if is_cyclic and not outgoing_by_component[component_id]
    }
    resolved_closed_components = {
        component_id
        for component_id in closed_components
        if all(
            nodes[int(node_id)].state.rules.cycle_resolution
            is CycleResolution.DECLARE_DRAW
            for node_id in component_members[int(component_id)]
        )
    }
    terminal_components = {
        component_by_node[node.node_id]
        for node in nodes
        if node.is_terminal
    } | resolved_closed_components
    terminal_reachable = _reverse_reachable_components(
        outgoing_by_component,
        terminal_components,
    )

    components: list[StrongComponent] = []
    for component_id, members in enumerate(component_members):
        typed_component_id = StrongComponentId(component_id)
        outgoing = tuple(sorted(outgoing_by_component[component_id], key=int))
        if not cyclic[component_id]:
            kind = StrongComponentKind.ACYCLIC
        elif typed_component_id in closed_components:
            kind = StrongComponentKind.CLOSED_CYCLE
        elif typed_component_id in terminal_reachable:
            kind = StrongComponentKind.TERMINAL_REACHABLE_CYCLE
        else:
            kind = StrongComponentKind.OPEN_UNRESOLVED_CYCLE
        components.append(
            StrongComponent(
                component_id=typed_component_id,
                node_ids=tuple(sorted(members, key=int)),
                kind=kind,
                outgoing_component_ids=outgoing,
                reaches_terminal=typed_component_id in terminal_reachable,
            )
        )
    return tuple(components)


def _build_adjacency(
    node_count: int,
    edges: list[StateGraphEdge],
) -> tuple[list[list[GraphNodeId]], list[list[GraphNodeId]]]:
    """构造正向与反向邻接表，供两次显式 DFS 复用。

    Args:
        node_count: 唯一状态节点数量。
        edges: 图中的全部有向边。

    Returns:
        正向邻接表和反向邻接表；列表下标与 ``GraphNodeId`` 一致。
    """
    adjacency = [[] for _ in range(node_count)]
    reverse_adjacency = [[] for _ in range(node_count)]
    for edge in edges:
        adjacency[int(edge.source_node_id)].append(edge.target_node_id)
        reverse_adjacency[int(edge.target_node_id)].append(edge.source_node_id)
    return adjacency, reverse_adjacency


def _iterative_finish_order(
    adjacency: list[list[GraphNodeId]],
) -> tuple[GraphNodeId, ...]:
    """使用显式 DFS 栈计算 Kosaraju 第一遍的完成顺序。

    Args:
        adjacency: 正向有向图邻接表。

    Returns:
        节点完成顺序，越晚完成的节点越靠后。
    """
    visited: set[GraphNodeId] = set()
    finish_order: list[GraphNodeId] = []
    for start_index in range(len(adjacency)):
        start = GraphNodeId(start_index)
        if start in visited:
            continue
        visited.add(start)
        stack: list[tuple[GraphNodeId, int]] = [(start, 0)]
        while stack:
            node_id, next_child_index = stack[-1]
            neighbours = adjacency[int(node_id)]
            if next_child_index < len(neighbours):
                child = neighbours[next_child_index]
                stack[-1] = (node_id, next_child_index + 1)
                if child not in visited:
                    visited.add(child)
                    stack.append((child, 0))
                continue
            stack.pop()
            finish_order.append(node_id)
    return tuple(finish_order)


def _collect_reverse_components(
    reverse_adjacency: list[list[GraphNodeId]],
    finish_order: tuple[GraphNodeId, ...],
) -> tuple[tuple[GraphNodeId, ...], ...]:
    """按完成顺序逆序遍历反向图并收集 SCC 成员。

    Args:
        reverse_adjacency: 原图所有边反向后的邻接表。
        finish_order: 第一遍显式 DFS 产生的完成顺序。

    Returns:
        每个节点恰好出现一次的强连通分量成员元组。
    """
    assigned: set[GraphNodeId] = set()
    components: list[tuple[GraphNodeId, ...]] = []
    for start in reversed(finish_order):
        if start in assigned:
            continue
        assigned.add(start)
        members: list[GraphNodeId] = []
        stack = [start]
        while stack:
            node_id = stack.pop()
            members.append(node_id)
            for neighbour in reverse_adjacency[int(node_id)]:
                if neighbour in assigned:
                    continue
                assigned.add(neighbour)
                stack.append(neighbour)
        components.append(tuple(members))
    return tuple(components)


def _reverse_reachable_components(
    outgoing_by_component: list[set[StrongComponentId]],
    terminal_components: set[StrongComponentId],
) -> set[StrongComponentId]:
    """从终局分量沿凝聚图反向边找出全部可到达终局的分量。

    Args:
        outgoing_by_component: 每个 SCC 直接指向的其他 SCC 集合。
        terminal_components: 已含确定终局节点或封闭循环平局的 SCC。

    Returns:
        包含终局分量自身以及所有能够沿有向路径到达它们的分量集合。
    """
    incoming_by_component: list[set[StrongComponentId]] = [
        set() for _ in outgoing_by_component
    ]
    for source_index, targets in enumerate(outgoing_by_component):
        source = StrongComponentId(source_index)
        for target in targets:
            incoming_by_component[int(target)].add(source)

    reachable = set(terminal_components)
    work_queue: deque[StrongComponentId] = deque(terminal_components)
    while work_queue:
        target = work_queue.popleft()
        for predecessor in incoming_by_component[int(target)]:
            if predecessor in reachable:
                continue
            reachable.add(predecessor)
            work_queue.append(predecessor)
    return reachable


def apply_closed_cycle_resolution(
    nodes: list[StateGraphNode],
    components: tuple[StrongComponent, ...],
) -> tuple[list[StateGraphNode], tuple[StrongComponent, ...]]:
    """按每个节点规则把无出口 SCC 转换为确定平局。

    Args:
        nodes: SCC 分析前的图节点列表，会复制后返回。
        components: 已确认的强连通分量分类。

    Returns:
        应用 ``CycleResolution.DECLARE_DRAW`` 后的节点列表和原 SCC 结果。
        若规则要求未来吸收概率求解，则节点保持非终局，不冒充平局。
    """
    resolved_nodes = list(nodes)
    for component in components:
        if component.kind is not StrongComponentKind.CLOSED_CYCLE:
            continue
        for node_id in component.node_ids:
            node = resolved_nodes[int(node_id)]
            if node.outcome is not GraphNodeOutcome.NON_TERMINAL:
                continue
            if node.state.rules.cycle_resolution is not CycleResolution.DECLARE_DRAW:
                continue
            resolved_nodes[int(node_id)] = replace(
                node,
                outcome=GraphNodeOutcome.DRAW,
                termination_reason=TerminationReason.CYCLE_GUARD,
            )
    return resolved_nodes, components


__all__ = ["analyze_strong_components", "apply_closed_cycle_resolution"]
