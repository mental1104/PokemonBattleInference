"""提供完整战斗状态图的并发安全进程内 TTL 存储适配器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
    BattleGraphCapacityExceeded,
    BattleGraphExpired,
    BattleGraphHandle,
    BattleGraphIdentifierCollision,
    BattleGraphNotFound,
    StoredBattleGraph,
)


Clock = Callable[[], datetime]
GraphIdFactory = Callable[[], str]


def _utc_now() -> datetime:
    """返回带 UTC 时区的当前时间。

    Returns:
        可直接参与 TTL 比较的 timezone-aware ``datetime``。
    """
    return datetime.now(timezone.utc)


def _uuid_graph_id() -> str:
    """生成不依赖对象地址或进程内自增序列的 graph ID。

    Returns:
        使用 UUID4 随机位生成的 32 位十六进制标识。
    """
    return uuid4().hex


@dataclass(slots=True)
class InMemoryBattleGraphStore:
    """使用有界字典保存完整图，并通过锁保护全部生命周期状态。

    容量不足时会按写入顺序淘汰最早的仍有效图；单个 artifact 自身超过节点或边
    上限时直接拒绝写入。实现不启动后台线程，过期清理由 ``put``、目标 ``get``、
    ``delete`` 或调用方显式执行 ``cleanup_expired`` 时完成。

    Args:
        ttl: 每个 graph 从写入时刻开始允许读取的时长，必须大于零。
        max_graphs: store 同时保存的 graph 数量上限，必须为正整数。
        max_nodes: 全部已保存 graph 的节点总量上限；None 表示不按节点限制。
        max_edges: 全部已保存 graph 的边总量上限；None 表示不按边限制。
        clock: 返回带时区时间的可注入时钟，测试可使用 fake clock。
        graph_id_factory: 生成不可猜测 graph ID 的可注入工厂。
        max_id_generation_attempts: 单次写入遇到重复 ID 时允许重试的次数。
    """

    ttl: timedelta = timedelta(minutes=15)
    max_graphs: int = 64
    max_nodes: int | None = 200_000
    max_edges: int | None = 800_000
    clock: Clock = _utc_now
    graph_id_factory: GraphIdFactory = _uuid_graph_id
    max_id_generation_attempts: int = 16
    _entries: dict[str, StoredBattleGraph] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )
    _total_nodes: int = field(init=False, default=0, repr=False)
    _total_edges: int = field(init=False, default=0, repr=False)
    _lock: RLock = field(init=False, default_factory=RLock, repr=False)

    def __post_init__(self) -> None:
        """校验 TTL、容量和依赖注入参数不会形成无界或不可运行实现。

        Raises:
            ValueError: TTL、容量、重试次数或可调用依赖非法时抛出。
        """
        if not isinstance(self.ttl, timedelta) or self.ttl <= timedelta(0):
            raise ValueError("ttl must be a positive timedelta")
        if isinstance(self.max_graphs, bool) or self.max_graphs <= 0:
            raise ValueError("max_graphs must be greater than 0")
        self._validate_optional_capacity(self.max_nodes, "max_nodes")
        self._validate_optional_capacity(self.max_edges, "max_edges")
        if (
            isinstance(self.max_id_generation_attempts, bool)
            or self.max_id_generation_attempts <= 0
        ):
            raise ValueError("max_id_generation_attempts must be greater than 0")
        if not callable(self.clock):
            raise ValueError("clock must be callable")
        if not callable(self.graph_id_factory):
            raise ValueError("graph_id_factory must be callable")

    def put(self, artifact: BattleGraphArtifact) -> BattleGraphHandle:
        """保存完整图，并在写入前清理过期项和执行最早写入淘汰。

        Args:
            artifact: application 已构建完成的图和计算版本。

        Returns:
            包含唯一 graph ID、根节点和生命周期边界的轻量句柄。

        Raises:
            ValueError: artifact 类型或注入时钟返回值非法时抛出。
            BattleGraphCapacityExceeded: 单个 artifact 超过节点或边上限时抛出。
            BattleGraphIdentifierCollision: 连续无法生成唯一 graph ID 时抛出。
        """
        if not isinstance(artifact, BattleGraphArtifact):
            raise ValueError("artifact must be BattleGraphArtifact")
        now = self._now()
        node_count = len(artifact.graph.nodes)
        edge_count = len(artifact.graph.edges)
        self._validate_artifact_capacity(node_count, edge_count)

        # ID 分配、容量淘汰和写入必须处于同一临界区，避免并发写入越过上限。
        with self._lock:
            self._evict_expired_locked(now)
            graph_id = self._allocate_graph_id_locked()
            self._evict_for_capacity_locked(node_count, edge_count)
            stored = StoredBattleGraph(
                graph_id=graph_id,
                graph=artifact.graph,
                calculation_revision=artifact.calculation_revision,
                created_at=now,
                expires_at=now + self.ttl,
            )
            self._entries[graph_id] = stored
            self._total_nodes += node_count
            self._total_edges += edge_count
            return stored.handle

    def get(self, graph_id: str) -> StoredBattleGraph:
        """读取一个尚未过期的完整图，并在发现过期时立即释放强引用。

        Args:
            graph_id: ``put`` 返回的规范化稳定标识。

        Returns:
            store 内保存的不可变完整图对象。

        Raises:
            BattleGraphNotFound: graph ID 不存在或输入不是规范化标识时抛出。
            BattleGraphExpired: graph 在本次读取时首次被确认已过期时抛出。
        """
        normalized = self._normalized_graph_id(graph_id)
        now = self._now()
        with self._lock:
            stored = self._entries.get(normalized)
            if stored is None:
                raise BattleGraphNotFound(normalized)
            if stored.expires_at <= now:
                # 先移除再抛出，保证异常对象不会间接持有完整 graph。
                self._remove_locked(normalized)
                raise BattleGraphExpired(normalized)
            return stored

    def delete(self, graph_id: str) -> None:
        """显式删除一个图，并同步更新节点和边容量计数。

        Args:
            graph_id: ``put`` 返回的规范化稳定标识。

        Raises:
            BattleGraphNotFound: graph ID 不存在或输入不是规范化标识时抛出。
            BattleGraphExpired: graph 在删除时已经过期时抛出。
        """
        normalized = self._normalized_graph_id(graph_id)
        now = self._now()
        with self._lock:
            stored = self._entries.get(normalized)
            if stored is None:
                raise BattleGraphNotFound(normalized)
            if stored.expires_at <= now:
                self._remove_locked(normalized)
                raise BattleGraphExpired(normalized)
            self._remove_locked(normalized)

    def cleanup_expired(self) -> int:
        """显式清理当前时刻已经过期的全部图。

        Returns:
            本次从 store 移除的 graph 数量。
        """
        now = self._now()
        with self._lock:
            return self._evict_expired_locked(now)

    @property
    def graph_count(self) -> int:
        """返回当前仍由 store 持有强引用的 graph 数量。"""
        with self._lock:
            return len(self._entries)

    @property
    def total_node_count(self) -> int:
        """返回当前全部已保存 graph 的节点总数。"""
        with self._lock:
            return self._total_nodes

    @property
    def total_edge_count(self) -> int:
        """返回当前全部已保存 graph 的边总数。"""
        with self._lock:
            return self._total_edges

    @staticmethod
    def _validate_optional_capacity(value: int | None, field_name: str) -> None:
        """校验可选节点或边容量为 None 或正整数。

        Args:
            value: 待校验容量；None 表示关闭该维度限制。
            field_name: 用于稳定错误文本的字段名称。

        Raises:
            ValueError: 容量不是 None 或正整数时抛出。
        """
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            raise ValueError(f"{field_name} must be greater than 0 or None")

    def _now(self) -> datetime:
        """读取并校验注入时钟，避免 naive datetime 破坏 TTL 比较。

        Returns:
            带时区的当前时间。

        Raises:
            ValueError: 时钟没有返回 timezone-aware ``datetime`` 时抛出。
        """
        now = self.clock()
        if not isinstance(now, datetime):
            raise ValueError("clock must return datetime")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("clock must return timezone-aware datetime")
        return now

    @staticmethod
    def _normalized_graph_id(graph_id: str) -> str:
        """校验调用方 graph ID 为非空且首尾无空白的字符串。

        Args:
            graph_id: 待读取或删除的标识。

        Returns:
            原样返回的规范化 graph ID。

        Raises:
            BattleGraphNotFound: 输入无法表示有效 graph ID 时抛出。
        """
        if (
            not isinstance(graph_id, str)
            or not graph_id
            or graph_id != graph_id.strip()
        ):
            raise BattleGraphNotFound(str(graph_id))
        return graph_id

    def _validate_artifact_capacity(self, node_count: int, edge_count: int) -> None:
        """拒绝单个 artifact 自身超过 store 节点或边上限。

        Args:
            node_count: 待写入完整图的节点数量。
            edge_count: 待写入完整图的边数量。

        Raises:
            BattleGraphCapacityExceeded: 单个图无法在清空 store 后容纳时抛出。
        """
        if self.max_nodes is not None and node_count > self.max_nodes:
            raise BattleGraphCapacityExceeded(
                f"battle graph has {node_count} nodes, exceeding max_nodes={self.max_nodes}"
            )
        if self.max_edges is not None and edge_count > self.max_edges:
            raise BattleGraphCapacityExceeded(
                f"battle graph has {edge_count} edges, exceeding max_edges={self.max_edges}"
            )

    def _allocate_graph_id_locked(self) -> str:
        """在锁内生成未被占用的规范化 graph ID。

        Returns:
            当前 ``_entries`` 中不存在的新 graph ID。

        Raises:
            BattleGraphIdentifierCollision: 工厂连续返回重复或非法标识时抛出。
        """
        for _ in range(self.max_id_generation_attempts):
            candidate = self.graph_id_factory()
            if (
                isinstance(candidate, str)
                and candidate
                and candidate == candidate.strip()
                and candidate not in self._entries
            ):
                return candidate
        raise BattleGraphIdentifierCollision(
            "could not allocate a unique normalized battle graph id"
        )

    def _evict_expired_locked(self, now: datetime) -> int:
        """在锁内移除全部已过期图并返回移除数量。

        Args:
            now: 本次清理使用的统一带时区时间快照。

        Returns:
            从 ``_entries`` 中移除的 graph 数量。
        """
        expired_ids = [
            graph_id
            for graph_id, stored in self._entries.items()
            if stored.expires_at <= now
        ]
        for graph_id in expired_ids:
            self._remove_locked(graph_id)
        return len(expired_ids)

    def _evict_for_capacity_locked(self, node_count: int, edge_count: int) -> None:
        """在锁内按最早写入顺序淘汰图，直到新 artifact 可以放入。

        Args:
            node_count: 新 graph 的节点数量。
            edge_count: 新 graph 的边数量。
        """
        while self._would_exceed_capacity_locked(node_count, edge_count):
            oldest_graph_id = next(iter(self._entries), None)
            if oldest_graph_id is None:
                # 单图容量已提前校验；该分支只保护计数不变量被意外破坏的情况。
                raise BattleGraphCapacityExceeded(
                    "battle graph store capacity could not be satisfied"
                )
            self._remove_locked(oldest_graph_id)

    def _would_exceed_capacity_locked(self, node_count: int, edge_count: int) -> bool:
        """判断加入新 graph 后是否会超过任一配置上限。

        Args:
            node_count: 新 graph 的节点数量。
            edge_count: 新 graph 的边数量。

        Returns:
            graph 数量、节点总数或边总数任一越界时返回 True。
        """
        if len(self._entries) + 1 > self.max_graphs:
            return True
        if self.max_nodes is not None and self._total_nodes + node_count > self.max_nodes:
            return True
        if self.max_edges is not None and self._total_edges + edge_count > self.max_edges:
            return True
        return False

    def _remove_locked(self, graph_id: str) -> None:
        """在锁内移除 graph，并保证容量计数与强引用同时更新。

        Args:
            graph_id: 当前 ``_entries`` 中存在的 graph ID。
        """
        stored = self._entries.pop(graph_id)
        self._total_nodes -= len(stored.graph.nodes)
        self._total_edges -= len(stored.graph.edges)


__all__ = ["Clock", "GraphIdFactory", "InMemoryBattleGraphStore"]
