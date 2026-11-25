"""把固定推演产生的完整图保存到可替换 BattleGraphStore。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
    BattleGraphHandle,
    BattleGraphStore,
    BattleGraphStoreError,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleExplorationEntry,
    FixedOneOnOneBattleResult,
    InferFixedOneOnOneBattleCommand,
)


class BattleGraphArtifactUnavailable(BattleGraphStoreError):
    """表示被包装的固定推演结果没有可交给 store 的完整图。"""


@runtime_checkable
class FixedOneOnOneBattleExecutor(Protocol):
    """定义能够执行固定 1v1 推演的窄 application 协议。"""

    def execute_fixed(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedOneOnOneBattleResult:
        """执行一次固定配置推演并返回完整图或既有 graph handle。

        Args:
            command: 规则、双方固定配置、行动策略和图限制。

        Returns:
            同时包含全局 summary 与 exploration 入口的固定推演结果。
        """


@dataclass(frozen=True, slots=True)
class StoredFixedOneOnOneBattleResult:
    """保存完成 graph store 接线后的固定推演结果和完整句柄元数据。

    Args:
        result: exploration 已只保留稳定 graph ID 的固定推演结果。
        handle: 同一次写入对应的 graph ID、根节点、计算版本和 TTL 生命周期。
    """

    result: FixedOneOnOneBattleResult
    handle: BattleGraphHandle


@dataclass(slots=True)
class StoreBackedInferOneOnOneBattleUseCase:
    """装饰固定推演用例，在不重新构图的前提下保存完整 graph artifact。

    该 application 用例只依赖 ``BattleGraphStore`` port，不知道 TTL、锁、UUID、Redis
    或数据库实现细节。若下层已经返回 graph handle，普通 ``execute_fixed`` 保持幂等；
    需要 HTTP 暴露过期时间时，可使用 ``execute_fixed_with_handle`` 读取句柄元数据。

    Args:
        inference_use_case: 负责读取配置、构建状态图和精确求解的固定推演执行器。
        graph_store: 保存完整状态图并返回稳定 graph ID 的 application port。
    """

    inference_use_case: FixedOneOnOneBattleExecutor
    graph_store: BattleGraphStore

    def __post_init__(self) -> None:
        """校验执行器和 store 均满足可替换 application 协议。

        Raises:
            ValueError: 任一依赖没有实现所需协议时抛出。
        """
        if not isinstance(self.inference_use_case, FixedOneOnOneBattleExecutor):
            raise ValueError("inference_use_case must implement FixedOneOnOneBattleExecutor")
        if not isinstance(self.graph_store, BattleGraphStore):
            raise ValueError("graph_store must implement BattleGraphStore")

    def execute_fixed(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedOneOnOneBattleResult:
        """执行一次固定推演，保存其完整图并只向上层返回稳定 handle。

        Args:
            command: 规则、双方固定配置、行动策略和图限制。

        Returns:
            summary 保持不变，exploration 改为 graph handle 且不重复持有完整图的结果。

        Raises:
            BattleGraphArtifactUnavailable: 下层既没有 artifact 也没有既有 handle 时抛出。
            BattleGraphStoreError: store 拒绝写入或返回不一致句柄时抛出。
        """
        result = self.inference_use_case.execute_fixed(command)
        if result.exploration.graph_handle is not None:
            # 普通执行入口保留原有幂等语义，不为已经保存的结果增加一次额外读取。
            return result
        return self._store_new_result(result).result

    def execute_fixed_with_handle(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> StoredFixedOneOnOneBattleResult:
        """执行固定推演并返回 HTTP exploration 合同需要的完整句柄元数据。

        Args:
            command: 规则、双方固定配置、行动策略和图限制。

        Returns:
            exploration 仅保留 graph ID 的推演结果，以及包含 ``expires_at`` 的句柄。

        Raises:
            BattleGraphArtifactUnavailable: 下层结果无法定位完整图时抛出。
            BattleGraphStoreError: store 写入、读取或句柄一致性校验失败时抛出。
        """
        result = self.inference_use_case.execute_fixed(command)
        exploration = result.exploration
        if exploration.graph_handle is not None:
            # 已有 handle 必须从同一个 store 重新读取生命周期，避免 API 猜测 TTL。
            handle = self.graph_store.get(exploration.graph_handle).handle
            self._require_matching_handle(exploration, handle)
            return StoredFixedOneOnOneBattleResult(result=result, handle=handle)
        return self._store_new_result(result)

    def _store_new_result(
        self,
        result: FixedOneOnOneBattleResult,
    ) -> StoredFixedOneOnOneBattleResult:
        """保存尚未入库的完整图，并移除返回结果中的 graph 强引用。

        Args:
            result: 下层刚完成构建、仍持有完整 graph artifact 的固定推演结果。

        Returns:
            已替换 exploration 的结果，以及 store 返回的稳定句柄。

        Raises:
            BattleGraphArtifactUnavailable: exploration 没有可保存的完整图。
            BattleGraphStoreError: store 返回的根节点或计算版本与 artifact 不一致。
        """
        exploration = result.exploration
        if exploration.graph_artifact is None:
            raise BattleGraphArtifactUnavailable(
                "fixed battle inference did not retain a graph artifact"
            )

        artifact = BattleGraphArtifact(
            graph=exploration.graph_artifact,
            calculation_revision=exploration.calculation_revision,
        )
        handle = self.graph_store.put(artifact)
        self._require_matching_handle(exploration, handle)

        # 保存成功后移除结果中的完整图引用，后续生命周期只由 store 和显式读取方管理。
        stored_exploration = BattleExplorationEntry(
            root_node_id=exploration.root_node_id,
            calculation_revision=exploration.calculation_revision,
            expandable=exploration.expandable,
            graph_artifact=None,
            graph_handle=handle.graph_id,
        )
        stored_result = replace(result, exploration=stored_exploration)
        return StoredFixedOneOnOneBattleResult(
            result=stored_result,
            handle=handle,
        )

    @staticmethod
    def _require_matching_handle(
        exploration: BattleExplorationEntry,
        handle: BattleGraphHandle,
    ) -> None:
        """校验句柄仍定位 exploration 声明的同一根节点和计算版本。

        Args:
            exploration: 下层推演返回的稳定探索入口。
            handle: store 写入或读取后返回的完整句柄。

        Raises:
            BattleGraphStoreError: 根节点或计算版本不一致时抛出。
        """
        if handle.root_node_id != exploration.root_node_id:
            raise BattleGraphStoreError(
                "battle graph store returned a handle with a different root node"
            )
        if handle.calculation_revision != exploration.calculation_revision:
            raise BattleGraphStoreError(
                "battle graph store returned a handle with a different calculation revision"
            )


__all__ = [
    "BattleGraphArtifactUnavailable",
    "FixedOneOnOneBattleExecutor",
    "StoreBackedInferOneOnOneBattleUseCase",
    "StoredFixedOneOnOneBattleResult",
]
