"""验证状态图根读取、lazy 分组、前进、回退和稳定错误语义。"""

from __future__ import annotations

from typing import cast

import pytest

from pokeop.application.battle_graph_store import (
    BattleGraphExpired,
    BattleGraphNotFound,
)
from pokeop.application.solver.models import GraphEdgeId, GraphNodeId
from pokeop.application.state_graph_exploration import (
    ExplorationCursor,
    ExplorationPathStep,
)
from pokeop.application.use_cases.battle_exploration import (
    AdvanceBattleExplorationUseCase,
    BacktrackBattleExplorationUseCase,
    EdgeNotInCurrentNodeError,
    IncompatibleCalculationRevisionError,
    InvalidExplorationCursorError,
    ListTransitionGroupsUseCase,
    LoadBattleNodeUseCase,
    LoadTransitionGroupOutcomesUseCase,
    TerminalBattleNodeAdvanceError,
    TransitionGroupNotFoundError,
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
from tests.application.use_cases.battle_exploration_test_helpers import (
    GRAPH_ID,
    REVISION,
    Executor,
    MemoryStore,
    advance,
    build_graph,
    stored_store,
)


def test_root_load_and_group_list_do_not_construct_outcomes(monkeypatch) -> None:
    """根节点无需客户端伪造 cursor，折叠 group 也不得调用 outcome projector。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION)

    def fail_if_outcome_is_projected(*args, **kwargs):
        """在 summary-only 路径错误构造 outcome 时立即让测试失败。"""
        del args, kwargs
        raise AssertionError("collapsed group listing must not project outcomes")

    from pokeop.application.use_cases.battle_exploration import _support

    monkeypatch.setattr(
        _support.projection,
        "_project_outcome",
        fail_if_outcome_is_projected,
    )
    result = ListTransitionGroupsUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        root.cursor,
    )

    assert root.cursor.depth == 0
    assert root.cursor.current_node_id == GraphNodeId(0)
    assert root.cumulative_probability.numerator == "1"
    assert root.cumulative_probability.denominator == "1"
    assert len(result.transition_groups) == 1
    group = result.transition_groups[0]
    assert group.expanded is False
    assert group.outcomes == ()
    assert group.raw_result_count == 3
    assert group.distinct_outcome_count == 2
    assert group.summary.minimum_damage == 10
    assert group.summary.maximum_damage == 21
    assert group.summary.minimum_hp_loss == 10
    assert group.summary.maximum_hp_loss == 20


def test_expand_only_requested_group_and_reject_unknown_group(monkeypatch) -> None:
    """合流节点存在两个 group 时，只允许明确 group 构造自身 outcomes。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    merged = advance(store, advance(store, root, 0), 2)
    listed = ListTransitionGroupsUseCase(store).execute(GRAPH_ID, REVISION, merged)
    requested = listed.transition_groups[0]

    from pokeop.application.use_cases.battle_exploration import _support

    original_project_outcome = _support.projection._project_outcome
    projected_edge_ids: list[int] = []

    def record_projected_edge(*, node, edge, cumulative_probability):
        """记录真正被展开的正式边，再调用 #58 原始 outcome projector。"""
        projected_edge_ids.append(int(edge.edge_id))
        return original_project_outcome(
            node=node,
            edge=edge,
            cumulative_probability=cumulative_probability,
        )

    monkeypatch.setattr(
        _support.projection,
        "_project_outcome",
        record_projected_edge,
    )
    expanded = LoadTransitionGroupOutcomesUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        merged,
        requested.group_id,
    )

    assert len(listed.transition_groups) == 2
    assert expanded.transition_group.expanded is True
    assert len(expanded.transition_group.outcomes) == 1
    assert projected_edge_ids == [expanded.transition_group.outcomes[0].edge_id]

    with pytest.raises(TransitionGroupNotFoundError):
        LoadTransitionGroupOutcomesUseCase(store).execute(
            GRAPH_ID,
            REVISION,
            merged,
            "tg-3-does-not-exist",
        )


def test_advance_rejects_wrong_source_and_terminal_node() -> None:
    """普通非法边与终局节点继续前进必须使用不同稳定异常。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor

    with pytest.raises(EdgeNotInCurrentNodeError) as wrong_edge:
        AdvanceBattleExplorationUseCase(store).execute(
            GRAPH_ID,
            REVISION,
            root,
            GraphEdgeId(2),
        )
    assert wrong_edge.value.current_node_id == 0
    assert wrong_edge.value.edge_id == 2

    terminal = advance(store, advance(store, advance(store, root, 0), 2), 5)
    with pytest.raises(TerminalBattleNodeAdvanceError) as terminal_error:
        AdvanceBattleExplorationUseCase(store).execute(
            GRAPH_ID,
            REVISION,
            terminal,
            GraphEdgeId(0),
        )
    assert terminal_error.value.node_id == 4


def test_backtrack_truncate_and_cycle_use_real_edge_prefix() -> None:
    """循环回到 root 后仍保留深度，返回和祖先跳转只截断 edge prefix。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    merged = advance(store, advance(store, root, 0), 2)
    cycled_root = advance(store, merged, 4)

    assert cycled_root.current_node_id == GraphNodeId(0)
    assert cycled_root.depth == 3
    cycled_position = LoadBattleNodeUseCase(store).load_current(
        GRAPH_ID,
        REVISION,
        cycled_root,
    )
    assert cycled_position.cumulative_probability.numerator == "1"
    assert cycled_position.cumulative_probability.denominator == "12"

    backtracked = BacktrackBattleExplorationUseCase(store).back(
        GRAPH_ID,
        REVISION,
        cycled_root,
    )
    assert backtracked.cursor == merged
    assert backtracked.node.node_id == 3

    truncated = BacktrackBattleExplorationUseCase(store).truncate(
        GRAPH_ID,
        REVISION,
        cycled_root,
        0,
    )
    assert truncated.cursor == root
    assert truncated.node.node_id == 0


def test_terminal_node_has_reason_and_no_transition_groups() -> None:
    """终局只由正式节点 outcome 判定，并返回明确原因与空 group 集合。"""
    store = stored_store()
    root = LoadBattleNodeUseCase(store).load_root(GRAPH_ID, REVISION).cursor
    terminal = advance(store, advance(store, advance(store, root, 0), 2), 5)

    position = LoadBattleNodeUseCase(store).load_current(
        GRAPH_ID,
        REVISION,
        terminal,
    )
    groups = ListTransitionGroupsUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        terminal,
    )

    assert position.node.terminal is True
    assert position.node.termination_reason == "knockout"
    assert groups.transition_groups == ()


def test_revision_store_lifecycle_and_invalid_cursor_errors_are_stable() -> None:
    """版本、not-found、expired 和三类 cursor 破坏必须保持独立语义。"""
    store = stored_store()

    with pytest.raises(IncompatibleCalculationRevisionError) as revision_error:
        LoadBattleNodeUseCase(store).load_root(GRAPH_ID, "other-revision")
    assert revision_error.value.requested_revision == "other-revision"
    assert revision_error.value.stored_revision == REVISION

    with pytest.raises(BattleGraphNotFound):
        LoadBattleNodeUseCase(MemoryStore()).load_root(GRAPH_ID, REVISION)

    expired_store = MemoryStore(get_error=BattleGraphExpired(GRAPH_ID))
    with pytest.raises(BattleGraphExpired):
        LoadBattleNodeUseCase(expired_store).load_root(GRAPH_ID, REVISION)

    invalid_cursors = (
        ExplorationCursor(graph_id="other-graph", root_node_id=GraphNodeId(0)),
        ExplorationCursor(graph_id=GRAPH_ID, root_node_id=GraphNodeId(1)),
        ExplorationCursor(
            graph_id=GRAPH_ID,
            root_node_id=GraphNodeId(0),
            steps=(
                ExplorationPathStep(
                    source_node_id=GraphNodeId(0),
                    edge_id=GraphEdgeId(0),
                    target_node_id=GraphNodeId(2),
                ),
            ),
        ),
    )
    for cursor in invalid_cursors:
        with pytest.raises(InvalidExplorationCursorError):
            LoadBattleNodeUseCase(store).load_current(GRAPH_ID, REVISION, cursor)


def test_store_backed_inference_handle_is_readable_without_fastapi() -> None:
    """现有保存包装用例产生的 handle 可直接作为新根节点读取入口。"""
    graph = build_graph()
    store = MemoryStore()
    executor = Executor(
        FixedOneOnOneBattleResult(
            summary=cast(BattleInferenceSummary, object()),
            exploration=BattleExplorationEntry(
                root_node_id=0,
                calculation_revision=REVISION,
                expandable=True,
                graph_artifact=graph,
                graph_handle=None,
            ),
        )
    )
    result = StoreBackedInferOneOnOneBattleUseCase(executor, store).execute_fixed(
        cast(InferFixedOneOnOneBattleCommand, object())
    )

    assert result.exploration.graph_handle == GRAPH_ID
    assert result.exploration.graph_handle is not None
    loaded = LoadBattleNodeUseCase(store).load_root(
        result.exploration.graph_handle,
        result.exploration.calculation_revision,
    )
    assert loaded.node.node_id == 0
    assert loaded.cursor.depth == 0
    assert loaded.cumulative_probability.numerator == "1"
    assert loaded.cumulative_probability.denominator == "1"
