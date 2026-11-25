"""定义完整战斗状态图 artifact 的 application 存储端口与稳定 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pokeop.application.solver.models import StateGraphBuildResult


class BattleGraphStoreError(RuntimeError):
    """表示图 artifact 存储、读取或生命周期管理失败。"""


class BattleGraphNotFound(BattleGraphStoreError):
    """表示指定 graph ID 当前不存在于 store。"""

    def __init__(self, graph_id: str) -> None:
        """保存缺失的 graph ID，并生成稳定错误文本。

        Args:
            graph_id: 调用方请求读取或删除的规范化 graph ID。
        """
        self.graph_id = graph_id
        super().__init__(f"battle graph {graph_id!r} was not found")


class BattleGraphExpired(BattleGraphStoreError):
    """表示指定 graph ID 曾存在，但其 TTL 已到期。"""

    def __init__(self, graph_id: str) -> None:
        """保存过期的 graph ID，并生成稳定错误文本。

        Args:
            graph_id: 已达到过期时间的规范化 graph ID。
        """
        self.graph_id = graph_id
        super().__init__(f"battle graph {graph_id!r} has expired")


class BattleGraphCapacityExceeded(BattleGraphStoreError):
    """表示单个 artifact 无法放入配置好的有界 store。"""


class BattleGraphIdentifierCollision(BattleGraphStoreError):
    """表示 graph ID 生成器连续返回已占用或非法标识。"""


@dataclass(frozen=True, slots=True)
class BattleGraphArtifact:
    """保存一次完整推演准备交给 store 的不可变图结果。

    Args:
        graph: 已完成构建与循环分析的完整 ``StateGraphBuildResult``。
        calculation_revision: 标识节点、边和求解语义的规范化稳定版本。
    """

    graph: StateGraphBuildResult
    calculation_revision: str

    def __post_init__(self) -> None:
        """校验 artifact 使用完整图类型和规范化计算版本。

        Raises:
            ValueError: 图类型或计算版本不满足 application 合同时抛出。
        """
        if not isinstance(self.graph, StateGraphBuildResult):
            raise ValueError("graph must be StateGraphBuildResult")
        _validate_identifier(self.calculation_revision, "calculation_revision")


@dataclass(frozen=True, slots=True)
class BattleGraphHandle:
    """返回一次成功写入后的稳定图句柄和生命周期信息。

    Args:
        graph_id: store 分配的不可猜测稳定标识。
        root_node_id: 完整图的根节点 ID。
        calculation_revision: 与保存 artifact 一致的计算语义版本。
        created_at: artifact 进入 store 的带时区时间。
        expires_at: artifact 不再允许读取的带时区时间。
    """

    graph_id: str
    root_node_id: int
    calculation_revision: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """校验句柄标识、根节点和时间范围。

        Raises:
            ValueError: 任一字段无法形成稳定可读取句柄时抛出。
        """
        _validate_identifier(self.graph_id, "graph_id")
        _validate_root_node_id(self.root_node_id)
        _validate_identifier(self.calculation_revision, "calculation_revision")
        _validate_lifetime(self.created_at, self.expires_at)


@dataclass(frozen=True, slots=True)
class StoredBattleGraph:
    """表示 store 返回的完整图对象及其稳定生命周期元数据。

    Args:
        graph_id: store 分配的不可猜测稳定标识。
        graph: 与顶部 summary 同一次构建得到的完整状态图。
        calculation_revision: 标识图计算语义的稳定版本。
        created_at: artifact 进入 store 的带时区时间。
        expires_at: artifact 不再允许读取的带时区时间。
    """

    graph_id: str
    graph: StateGraphBuildResult
    calculation_revision: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """校验已保存图与句柄可观察字段保持一致。

        Raises:
            ValueError: 标识、图、版本或生命周期字段非法时抛出。
        """
        _validate_identifier(self.graph_id, "graph_id")
        if not isinstance(self.graph, StateGraphBuildResult):
            raise ValueError("graph must be StateGraphBuildResult")
        _validate_identifier(self.calculation_revision, "calculation_revision")
        _validate_lifetime(self.created_at, self.expires_at)

    @property
    def handle(self) -> BattleGraphHandle:
        """返回不暴露完整图对象的轻量稳定句柄。

        Returns:
            与当前已保存图共享 graph ID、根节点、版本和生命周期的句柄。
        """
        return BattleGraphHandle(
            graph_id=self.graph_id,
            root_node_id=int(self.graph.root_node_id),
            calculation_revision=self.calculation_revision,
            created_at=self.created_at,
            expires_at=self.expires_at,
        )


@runtime_checkable
class BattleGraphStore(Protocol):
    """定义 application 保存和读取完整战斗状态图的可替换端口。"""

    def put(self, artifact: BattleGraphArtifact) -> BattleGraphHandle:
        """保存完整图并返回稳定句柄。

        Args:
            artifact: 与顶部 summary 来自同一次构建的完整图 artifact。

        Returns:
            包含 graph ID、根节点和 TTL 边界的轻量句柄。

        Raises:
            BattleGraphCapacityExceeded: artifact 无法放入有界实现时抛出。
            BattleGraphIdentifierCollision: 无法分配唯一 graph ID 时抛出。
        """

    def get(self, graph_id: str) -> StoredBattleGraph:
        """按 graph ID 读取尚未过期的完整图。

        Args:
            graph_id: ``put`` 返回的规范化稳定标识。

        Returns:
            包含完整图和生命周期元数据的不可变对象。

        Raises:
            BattleGraphNotFound: graph ID 当前不存在时抛出。
            BattleGraphExpired: graph ID 已达到过期时间时抛出。
        """

    def delete(self, graph_id: str) -> None:
        """显式删除一个尚未过期的完整图并释放 store 强引用。

        Args:
            graph_id: ``put`` 返回的规范化稳定标识。

        Raises:
            BattleGraphNotFound: graph ID 当前不存在时抛出。
            BattleGraphExpired: graph ID 在删除时已经过期时抛出。
        """


def _validate_identifier(value: str, field_name: str) -> None:
    """校验稳定标识使用非空且首尾无空白的字符串。

    Args:
        value: 待校验的字符串值。
        field_name: 用于稳定错误文本的字段名称。

    Raises:
        ValueError: 值不是规范化非空字符串时抛出。
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and normalized")


def _validate_root_node_id(root_node_id: int) -> None:
    """校验根节点 ID 为非负整数且拒绝布尔值。

    Args:
        root_node_id: 待校验的图根节点 ID。

    Raises:
        ValueError: 根节点 ID 非法时抛出。
    """
    if isinstance(root_node_id, bool) or not isinstance(root_node_id, int) or root_node_id < 0:
        raise ValueError("root_node_id must be a non-negative integer")


def _validate_lifetime(created_at: datetime, expires_at: datetime) -> None:
    """校验创建和过期时间均带时区且形成正向生命周期。

    Args:
        created_at: artifact 写入 store 的时间。
        expires_at: artifact 不再允许读取的时间。

    Raises:
        ValueError: 时间缺少时区或过期时间不晚于创建时间时抛出。
    """
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise ValueError("expires_at must be timezone-aware")
    if expires_at <= created_at:
        raise ValueError("expires_at must be later than created_at")


__all__ = [
    "BattleGraphArtifact",
    "BattleGraphCapacityExceeded",
    "BattleGraphExpired",
    "BattleGraphHandle",
    "BattleGraphIdentifierCollision",
    "BattleGraphNotFound",
    "BattleGraphStore",
    "BattleGraphStoreError",
    "StoredBattleGraph",
]
