"""验证进程内 BattleGraphStore 的 TTL、容量、释放和并发语义。"""

from __future__ import annotations

import gc
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from uuid import UUID

import pytest

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
    BattleGraphCapacityExceeded,
    BattleGraphExpired,
    BattleGraphIdentifierCollision,
    BattleGraphNotFound,
)
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.domain.battle.transitions import TransitionEventSummary
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore


@dataclass(slots=True)
class _FakeClock:
    """提供可手动推进的 timezone-aware 测试时钟。"""

    current: datetime

    def __call__(self) -> datetime:
        """返回当前测试时间。

        Returns:
            由测试显式控制的带时区时间。
        """
        return self.current

    def advance(self, delta: timedelta) -> None:
        """按指定时长推进测试时钟。

        Args:
            delta: 需要增加到当前时间的时长。
        """
        self.current += delta


class _GraphState:
    """作为 synthetic graph 节点载荷，并允许 weakref 验证对象释放。"""



def _graph(
    node_count: int = 1,
    edge_count: int = 0,
    *,
    first_state: _GraphState | None = None,
) -> StateGraphBuildResult:
    """创建只用于 store 生命周期测试的最小完整图。

    Args:
        node_count: synthetic graph 的节点数量，必须大于零。
        edge_count: synthetic graph 的边数量，可以为零。
        first_state: 可选的首节点载荷，用于 weakref 释放断言。

    Returns:
        节点、边和统计数量一致的 ``StateGraphBuildResult``。
    """
    if node_count <= 0:
        raise ValueError("node_count must be greater than 0")
    states = [first_state or _GraphState()]
    states.extend(_GraphState() for _ in range(node_count - 1))
    nodes = tuple(
        StateGraphNode(
            node_id=GraphNodeId(index),
            state=state,  # type: ignore[arg-type]
            state_key=("synthetic", index),  # type: ignore[arg-type]
            outcome=GraphNodeOutcome.NON_TERMINAL,
            termination_reason=None,
        )
        for index, state in enumerate(states)
    )
    edges = tuple(
        StateGraphEdge(
            edge_id=GraphEdgeId(index),
            source_node_id=GraphNodeId(index % node_count),
            target_node_id=GraphNodeId((index + 1) % node_count),
            probability=Fraction(1),
            event_summary=TransitionEventSummary.empty(),
            source_key="test.synthetic",
        )
        for index in range(edge_count)
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=node_count,
            edge_count=edge_count,
            max_turn_number=0,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=0,
                defender_wins=0,
                draws=0,
                non_terminal=node_count,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )


def _artifact(
    node_count: int = 1,
    edge_count: int = 0,
    *,
    first_state: _GraphState | None = None,
) -> BattleGraphArtifact:
    """创建使用固定计算版本的 synthetic graph artifact。

    Args:
        node_count: 完整图节点数量。
        edge_count: 完整图边数量。
        first_state: 可选的首节点载荷。

    Returns:
        可直接交给 ``InMemoryBattleGraphStore.put`` 的 artifact。
    """
    return BattleGraphArtifact(
        graph=_graph(node_count, edge_count, first_state=first_state),
        calculation_revision="battle-inference.test.v1",
    )


def test_put_get_and_delete_preserve_complete_graph_and_usage() -> None:
    """写入应返回 UUID 句柄，读取保持同一图实例，删除后容量计数归零。"""
    store = InMemoryBattleGraphStore(max_graphs=2, max_nodes=10, max_edges=10)
    artifact = _artifact(node_count=2, edge_count=1)

    handle = store.put(artifact)
    stored = store.get(handle.graph_id)

    assert UUID(handle.graph_id).version == 4
    assert stored.graph is artifact.graph
    assert stored.handle == handle
    assert store.graph_count == 1
    assert store.total_node_count == 2
    assert store.total_edge_count == 1

    store.delete(handle.graph_id)

    assert store.graph_count == 0
    assert store.total_node_count == 0
    assert store.total_edge_count == 0
    with pytest.raises(BattleGraphNotFound):
        store.get(handle.graph_id)


def test_expired_graph_raises_expired_once_and_releases_strong_reference() -> None:
    """首次过期读取应报告 expired 并移除图，后续读取稳定退化为 not-found。"""
    clock = _FakeClock(datetime(2026, 7, 24, tzinfo=timezone.utc))
    state = _GraphState()
    state_reference = weakref.ref(state)
    artifact = _artifact(first_state=state)
    store = InMemoryBattleGraphStore(
        ttl=timedelta(seconds=10),
        clock=clock,
        max_graphs=2,
    )
    handle = store.put(artifact)
    del state
    del artifact

    clock.advance(timedelta(seconds=10))
    with pytest.raises(BattleGraphExpired):
        store.get(handle.graph_id)

    gc.collect()
    assert state_reference() is None
    assert store.graph_count == 0
    with pytest.raises(BattleGraphNotFound):
        store.get(handle.graph_id)


def test_cleanup_expired_removes_all_due_entries_without_background_thread() -> None:
    """显式清理入口应一次移除所有到期图并更新节点、边计数。"""
    clock = _FakeClock(datetime(2026, 7, 24, tzinfo=timezone.utc))
    identifiers = iter(("graph-a", "graph-b"))
    store = InMemoryBattleGraphStore(
        ttl=timedelta(minutes=1),
        clock=clock,
        graph_id_factory=lambda: next(identifiers),
        max_graphs=4,
        max_nodes=10,
        max_edges=10,
    )
    store.put(_artifact(node_count=2, edge_count=1))
    store.put(_artifact(node_count=3, edge_count=2))

    clock.advance(timedelta(minutes=1))

    assert store.cleanup_expired() == 2
    assert store.graph_count == 0
    assert store.total_node_count == 0
    assert store.total_edge_count == 0


def test_graph_count_capacity_evicts_oldest_live_entry() -> None:
    """达到 graph 数量上限时应淘汰最早写入项，而不是无界增长。"""
    identifiers = iter(("graph-a", "graph-b", "graph-c"))
    store = InMemoryBattleGraphStore(
        max_graphs=2,
        max_nodes=None,
        max_edges=None,
        graph_id_factory=lambda: next(identifiers),
    )
    first = store.put(_artifact())
    second = store.put(_artifact())
    third = store.put(_artifact())

    with pytest.raises(BattleGraphNotFound):
        store.get(first.graph_id)
    assert store.get(second.graph_id).graph_id == second.graph_id
    assert store.get(third.graph_id).graph_id == third.graph_id
    assert store.graph_count == 2


def test_node_capacity_evicts_oldest_and_rejects_single_oversized_graph() -> None:
    """节点总量越界时应先淘汰旧图，单图本身越界则稳定拒绝写入。"""
    identifiers = iter(("graph-a", "graph-b", "graph-c"))
    store = InMemoryBattleGraphStore(
        max_graphs=4,
        max_nodes=3,
        max_edges=None,
        graph_id_factory=lambda: next(identifiers),
    )
    first = store.put(_artifact(node_count=2))
    second = store.put(_artifact(node_count=2))

    with pytest.raises(BattleGraphNotFound):
        store.get(first.graph_id)
    assert store.get(second.graph_id).graph_id == second.graph_id
    assert store.total_node_count == 2

    with pytest.raises(BattleGraphCapacityExceeded):
        store.put(_artifact(node_count=4))

    assert store.get(second.graph_id).graph_id == second.graph_id
    assert store.graph_count == 1


def test_duplicate_graph_ids_never_overwrite_existing_artifact() -> None:
    """ID 工厂持续碰撞时应拒绝第二次写入，并保留原有 graph。"""
    store = InMemoryBattleGraphStore(
        max_graphs=2,
        graph_id_factory=lambda: "duplicate-id",
        max_id_generation_attempts=3,
    )
    first_artifact = _artifact(node_count=1)
    first = store.put(first_artifact)

    with pytest.raises(BattleGraphIdentifierCollision):
        store.put(_artifact(node_count=2))

    assert store.graph_count == 1
    assert store.get(first.graph_id).graph is first_artifact.graph


def test_concurrent_put_and_get_keep_unique_ids_and_consistent_usage() -> None:
    """并发读写应保持 ID 唯一、字典完整和容量计数一致。"""
    graph_total = 64
    store = InMemoryBattleGraphStore(
        max_graphs=graph_total,
        max_nodes=graph_total,
        max_edges=graph_total,
    )

    def put_and_read(_: int) -> str:
        """在一个工作线程中写入并立即读取同一 synthetic graph。

        Args:
            _: 线程池提供但本测试不需要使用的任务序号。

        Returns:
            成功写入和读取的 graph ID。
        """
        handle = store.put(_artifact())
        return store.get(handle.graph_id).graph_id

    with ThreadPoolExecutor(max_workers=8) as executor:
        graph_ids = tuple(executor.map(put_and_read, range(graph_total)))

    assert len(set(graph_ids)) == graph_total
    assert store.graph_count == graph_total
    assert store.total_node_count == graph_total
    assert store.total_edge_count == 0
