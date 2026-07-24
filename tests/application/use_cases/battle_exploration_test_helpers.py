"""提供渐进探索 application 测试共享的真实状态图和 fake store。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from pokeop.application.battle_graph_store import (
    BattleGraphArtifact,
    BattleGraphHandle,
    BattleGraphNotFound,
    StoredBattleGraph,
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
from pokeop.application.state_graph_exploration import ExplorationCursor
from pokeop.application.use_cases.battle_exploration import (
    AdvanceBattleExplorationUseCase,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    FixedOneOnOneBattleResult,
    InferFixedOneOnOneBattleCommand,
)
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.state import BattleState
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
)
from tests.domain.battle.effect_test_helpers import build_effect_test_battle_state


REVISION = "battle-inference.test.v1"
GRAPH_ID = "stored-graph"
CREATED_AT = datetime(2026, 7, 24, tzinfo=timezone.utc)


def node(
    node_id: int,
    state: BattleState,
    *,
    outcome: GraphNodeOutcome = GraphNodeOutcome.NON_TERMINAL,
    termination_reason: TerminationReason | None = None,
) -> StateGraphNode:
    """构造使用真实 BattleState 的连续状态图节点。

    Args:
        node_id: 当前测试图中的连续节点 ID。
        state: 节点持有的完整不可变战斗状态。
        outcome: 节点终局分类。
        termination_reason: 终局节点的稳定结束原因。

    Returns:
        可供 projection 和 cursor 校验共同读取的正式状态图节点。
    """
    return StateGraphNode(
        node_id=GraphNodeId(node_id),
        state=state,
        state_key=state.state_key,
        outcome=outcome,
        termination_reason=termination_reason,
    )


def edge(
    edge_id: int,
    source_node_id: int,
    target_node_id: int,
    probability: Fraction,
    paths: tuple[tuple[TransitionEvent, ...], ...],
    *,
    source_key: str | None = None,
) -> StateGraphEdge:
    """构造一条保留全部替代事件路径的正式图边。"""
    return StateGraphEdge(
        edge_id=GraphEdgeId(edge_id),
        source_node_id=GraphNodeId(source_node_id),
        target_node_id=GraphNodeId(target_node_id),
        probability=probability,
        event_summary=TransitionEventSummary(paths),
        source_key=source_key,
    )


def damage_path(
    roll_index: int,
    final_damage: int,
    actual_hp_loss: int,
    *,
    event_id: str = "root-damage",
) -> tuple[TransitionEvent, ...]:
    """构造一条伤害档位与结构化 DAMAGE 事实按顺序出现的路径。"""
    return (
        TransitionEvent(
            event_type=TransitionEventType.DAMAGE_ROLL,
            event_id=event_id,
            outcome_id=f"roll-{roll_index}",
            numeric_value=final_damage,
        ),
        BattleEvent(
            kind=BattleEventKind.DAMAGE,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier="move",
            value=actual_hp_loss,
        ),
    )


def battle_path(
    kind: BattleEventKind,
    source_identifier: str,
) -> tuple[TransitionEvent, ...]:
    """构造一条只包含结构化业务事实的确定性事件路径。"""
    return (
        BattleEvent(
            kind=kind,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            target=BattleSide.DEFENDER,
            move_id=418,
            source_identifier=source_identifier,
        ),
    )


def _state_with_defender_hp(state: BattleState, hp: int) -> BattleState:
    """返回只替换防守方当前 HP 的不可变测试状态。"""
    return state.with_battler(
        BattleSide.DEFENDER,
        state.defender.with_current_hp(hp),
    )


def build_graph() -> StateGraphBuildResult:
    """构建包含分叉、合流、循环回边和终局出口的真实战斗状态图。

    Returns:
        路径为 ``root -> left/right -> merged -> root/terminal`` 的完整图。
    """
    root_state = build_effect_test_battle_state()
    defender_hp = root_state.defender.current_hp
    nodes = (
        node(0, root_state),
        node(1, _state_with_defender_hp(root_state, defender_hp - 10)),
        node(2, _state_with_defender_hp(root_state, defender_hp - 20)),
        node(3, _state_with_defender_hp(root_state, defender_hp - 30)),
        node(
            4,
            _state_with_defender_hp(root_state, 0),
            outcome=GraphNodeOutcome.ATTACKER_WIN,
            termination_reason=TerminationReason.KNOCKOUT,
        ),
    )
    edges = (
        edge(
            0,
            0,
            1,
            Fraction(1, 3),
            (damage_path(0, 10, 10),),
            source_key="damage.random-roll",
        ),
        edge(
            1,
            0,
            2,
            Fraction(2, 3),
            (
                damage_path(1, 20, 20),
                damage_path(2, 21, 20),
            ),
            source_key="damage.random-roll",
        ),
        edge(
            2,
            1,
            3,
            Fraction(1, 1),
            (battle_path(BattleEventKind.MOVE_USED, "left-merge"),),
            source_key="left-merge",
        ),
        edge(
            3,
            2,
            3,
            Fraction(1, 1),
            (battle_path(BattleEventKind.MOVE_USED, "right-merge"),),
            source_key="right-merge",
        ),
        edge(
            4,
            3,
            0,
            Fraction(1, 4),
            (battle_path(BattleEventKind.TURN_ENDED, "cycle-to-root"),),
            source_key="cycle-to-root",
        ),
        edge(
            5,
            3,
            4,
            Fraction(3, 4),
            (
                battle_path(BattleEventKind.FAINTED, "terminal-primary"),
                battle_path(BattleEventKind.FAINTED, "terminal-alternative"),
            ),
            source_key="terminal-exit",
        ),
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=(),
        statistics=StateGraphStatistics(
            unique_state_count=len(nodes),
            edge_count=len(edges),
            max_turn_number=max(item.state.turn_number for item in nodes),
            terminal_counts=StateGraphTerminalCounts(
                attacker_wins=1,
                defender_wins=0,
                draws=0,
                non_terminal=4,
                unknown=0,
            ),
            closed_cycle_count=0,
            terminal_reachable_cycle_count=1,
        ),
    )


@dataclass(slots=True)
class MemoryStore:
    """提供测试所需 put/get/delete、生命周期和稳定异常语义。"""

    stored_graph: StoredBattleGraph | None = None
    get_error: Exception | None = None

    def put(self, artifact: BattleGraphArtifact) -> BattleGraphHandle:
        """保存完整图并返回与 artifact 一致的固定句柄。"""
        self.stored_graph = StoredBattleGraph(
            graph_id=GRAPH_ID,
            graph=artifact.graph,
            calculation_revision=artifact.calculation_revision,
            created_at=CREATED_AT,
            expires_at=CREATED_AT + timedelta(minutes=5),
        )
        return self.stored_graph.handle

    def get(self, graph_id: str) -> StoredBattleGraph:
        """返回已保存图，或按测试配置抛出 not-found/expired。"""
        if self.get_error is not None:
            raise self.get_error
        if self.stored_graph is None or graph_id != self.stored_graph.graph_id:
            raise BattleGraphNotFound(graph_id)
        return self.stored_graph

    def delete(self, graph_id: str) -> None:
        """删除固定图；错误 graph ID 按 not-found 处理。"""
        if self.stored_graph is None or graph_id != self.stored_graph.graph_id:
            raise BattleGraphNotFound(graph_id)
        self.stored_graph = None


@dataclass(slots=True)
class Executor:
    """返回预构造固定推演结果的窄 fake executor。"""

    result: FixedOneOnOneBattleResult

    def execute_fixed(
        self,
        command: InferFixedOneOnOneBattleCommand,
    ) -> FixedOneOnOneBattleResult:
        """忽略占位 command 并返回同一次构建的完整图结果。"""
        del command
        return self.result


def stored_store(graph: StateGraphBuildResult | None = None) -> MemoryStore:
    """创建已经保存标准测试图的内存 store。"""
    store = MemoryStore()
    store.put(
        BattleGraphArtifact(
            graph=graph or build_graph(),
            calculation_revision=REVISION,
        )
    )
    return store


def advance(
    store: MemoryStore,
    cursor: ExplorationCursor,
    edge_id: int,
) -> ExplorationCursor:
    """使用正式 advance use case 简化测试路径构造。"""
    return AdvanceBattleExplorationUseCase(store).execute(
        GRAPH_ID,
        REVISION,
        cursor,
        GraphEdgeId(edge_id),
    ).cursor
