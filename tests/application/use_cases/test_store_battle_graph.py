"""验证固定推演图只构建一次，并通过可替换 store 转换为稳定 handle。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
    BattleGraphHandle,
    BattleGraphNotFound,
    BattleGraphStore,
    StoredBattleGraph,
)
from pokeop.application.solver.models import (
    GraphNodeId,
    GraphNodeOutcome,
    StateGraphBuildResult,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleExplorationEntry,
    BattleInferenceSummary,
    FixedOneOnOneBattleResult,
    InferFixedOneOnOneBattleCommand,
)
from pokeop.application.use_cases.store_battle_graph import (
    StoreBackedInferOneOnOneBattleUseCase,
)


class _GraphState:
    """作为 application 包装用例测试中的 synthetic graph 节点载荷。"""



def _graph() -> StateGraphBuildResult:
    """创建包含一个非终局根节点的最小完整图。

    Returns:
        可用于验证对象身份和根节点语义的 ``StateGraphBuildResult``。
    """
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=(
            StateGraphNode(
                node_id=GraphNodeId(0),
                state=_GraphState(),  # type: ignore[arg-type]
                state_key=("synthetic", 0),  # type: ignore[arg-type]
                outcome=GraphNodeOutcome.NON_TERMINAL,
                termination_reason=None,
            ),
        ),
        edges=(),
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=1,
            edge_count=0,
            max_turn_number=0,
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=0,
                defender_wins=0,
                draws=0,
                non_terminal=1,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=0,
        ),
    )


def _result(
    graph: StateGraphBuildResult | None,
    *,
    graph_handle: str | None = None,
) -> FixedOneOnOneBattleResult:
    """创建只关注 exploration 字段的固定推演结果。

    Args:
        graph: 下层推演保留的完整图；已保存结果可以使用 None。
        graph_handle: 已存在的稳定 graph ID。

    Returns:
        summary 使用不参与本测试的占位对象，exploration 保持真实合同。
    """
    return FixedOneOnOneBattleResult(
        summary=cast(BattleInferenceSummary, object()),
        exploration=BattleExplorationEntry(
            root_node_id=0,
            calculation_revision="battle-inference.test.v1",
            expandable=True,
            graph_artifact=graph,
            graph_handle=graph_handle,
        ),
    )


@dataclass(slots=True)
class _Executor:
    """返回预构造结果并记录固定推演执行次数的 fake executor。"""

    result: FixedOneOnOneBattleResult
    call_count: int = 0

    def execute_fixed(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedOneOnOneBattleResult:
        """记录调用并返回同一预构造结果。

        Args:
            command: 包装用例透传的固定推演命令，本 fake 不读取字段。

        Returns:
            测试预先配置的固定推演结果。
        """
        del command
        self.call_count += 1
        return self.result


@dataclass(slots=True)
class _Store:
    """记录写入 artifact 的 fake store，并返回固定生命周期句柄。"""

    artifact: BattleGraphArtifact | None = None
    put_count: int = 0

    def put(self, artifact: BattleGraphArtifact) -> BattleGraphHandle:
        """保存最后一次 artifact，并返回与其根节点和版本一致的固定句柄。

        Args:
            artifact: 包装用例从下层 exploration 提取的完整图。

        Returns:
            graph ID 固定为 ``stored-graph`` 的测试句柄。
        """
        self.artifact = artifact
        self.put_count += 1
        created_at = datetime(2026, 7, 24, tzinfo=timezone.utc)
        return BattleGraphHandle(
            graph_id="stored-graph",
            root_node_id=int(artifact.graph.root_node_id),
            calculation_revision=artifact.calculation_revision,
            created_at=created_at,
            expires_at=created_at + timedelta(minutes=5),
        )

    def get(self, graph_id: str) -> StoredBattleGraph:
        """本 fake 不承担读取职责，调用时按稳定 not-found 语义失败。

        Args:
            graph_id: 调用方尝试读取的 graph ID。

        Raises:
            BattleGraphNotFound: 始终抛出，表明测试只验证写入编排。
        """
        raise BattleGraphNotFound(graph_id)

    def delete(self, graph_id: str) -> None:
        """清空已记录 artifact；graph ID 仅用于满足 store 协议。

        Args:
            graph_id: 调用方请求删除的 graph ID。
        """
        del graph_id
        self.artifact = None



def test_store_backed_use_case_saves_same_graph_and_returns_only_handle() -> None:
    """包装用例应只执行一次下层推演，并把同一图实例交给 fake store。"""
    graph = _graph()
    executor = _Executor(_result(graph))
    store = _Store()
    use_case = StoreBackedInferOneOnOneBattleUseCase(executor, store)

    result = use_case.execute_fixed(cast(InferFixedOneOnOneBattleCommand, object()))

    assert isinstance(store, BattleGraphStore)
    assert executor.call_count == 1
    assert store.put_count == 1
    assert store.artifact is not None
    assert store.artifact.graph is graph
    assert result.summary is executor.result.summary
    assert result.exploration.graph_artifact is None
    assert result.exploration.graph_handle == "stored-graph"
    assert result.exploration.root_node_id == 0
    assert result.exploration.calculation_revision == "battle-inference.test.v1"


def test_store_backed_use_case_is_idempotent_for_existing_handle() -> None:
    """下层已经返回 handle 时不得再次写入或替换既有 exploration。"""
    original = _result(None, graph_handle="already-stored")
    executor = _Executor(original)
    store = _Store()
    use_case = StoreBackedInferOneOnOneBattleUseCase(executor, store)

    result = use_case.execute_fixed(cast(InferFixedOneOnOneBattleCommand, object()))

    assert result is original
    assert executor.call_count == 1
    assert store.put_count == 0
    assert store.artifact is None
