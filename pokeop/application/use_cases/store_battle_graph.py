"""把固定推演产生的完整图保存到可替换 BattleGraphStore。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol, runtime_checkable

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
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


@dataclass(slots=True)
class StoreBackedInferOneOnOneBattleUseCase:
    """装饰固定推演用例，在不重新构图的前提下保存完整 graph artifact。

    该 application 用例只依赖 ``BattleGraphStore`` port，不知道 TTL、锁、UUID、Redis
    或数据库实现细节。若下层已经返回 graph handle，则直接保留结果，避免重复写入。

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
        exploration = result.exploration

        # 已接入其他 store 的结果保持幂等，避免同一次调用链重复保存完整图。
        if exploration.graph_handle is not None:
            return result
        if exploration.graph_artifact is None:
            raise BattleGraphArtifactUnavailable(
                "fixed battle inference did not retain a graph artifact"
            )

        artifact = BattleGraphArtifact(
            graph=exploration.graph_artifact,
            calculation_revision=exploration.calculation_revision,
        )
        handle = self.graph_store.put(artifact)
        if handle.root_node_id != exploration.root_node_id:
            raise BattleGraphStoreError(
                "battle graph store returned a handle with a different root node"
            )
        if handle.calculation_revision != exploration.calculation_revision:
            raise BattleGraphStoreError(
                "battle graph store returned a handle with a different calculation revision"
            )

        # 保存成功后移除结果中的完整图引用，后续生命周期只由 store 和显式读取方管理。
        stored_exploration = BattleExplorationEntry(
            root_node_id=exploration.root_node_id,
            calculation_revision=exploration.calculation_revision,
            expandable=exploration.expandable,
            graph_artifact=None,
            graph_handle=handle.graph_id,
        )
        return replace(result, exploration=stored_exploration)


__all__ = [
    "BattleGraphArtifactUnavailable",
    "FixedOneOnOneBattleExecutor",
    "StoreBackedInferOneOnOneBattleUseCase",
]
