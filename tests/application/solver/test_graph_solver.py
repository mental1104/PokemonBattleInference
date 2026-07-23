from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import cast

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    BattleGraphSolveStatus,
    ExpectedTurns,
    ExpectedTurnsStatus,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import (
    GraphEdgeId,
    GraphNodeId,
    GraphNodeOutcome,
    GraphTruncationReason,
    StateGraphBuildResult,
    StateGraphEdge,
    StateGraphNode,
    StateGraphStatistics,
    StateGraphTerminalCounts,
    StrongComponent,
    StrongComponentId,
    StrongComponentKind,
)
from pokeop.application.use_cases.solve_battle_graph import SolveBattleGraphUseCase
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import TransitionEventSummary


@dataclass(frozen=True, slots=True)
class _GraphSpec:
    """声明测试图节点分类、边和 SCC 分类。

    Args:
        outcomes: 按节点 ID 排列的节点求解分类。
        edges: ``(source, target, probability)`` 形式的精确带权边。
        components: ``(kind, node_ids)`` 形式的 SCC 分类。
        truncation_reasons: 状态图构建阶段记录的截断原因。
    """

    outcomes: tuple[GraphNodeOutcome, ...]
    edges: tuple[tuple[int, int, Fraction], ...]
    components: tuple[tuple[StrongComponentKind, tuple[int, ...]], ...]
    truncation_reasons: tuple[GraphTruncationReason, ...] = ()


def _graph(spec: _GraphSpec) -> StateGraphBuildResult:
    """根据紧凑测试声明构造状态图结果。

    Args:
        spec: 测试所需的节点、边、SCC 和截断信息。

    Returns:
        可直接交给 ``BattleGraphSolver`` 的不可变状态图结果。
    """
    nodes = tuple(
        StateGraphNode(
            node_id=GraphNodeId(index),
            state=cast(BattleState, object()),
            state_key=cast(StateKey, (index,)),
            outcome=outcome,
        )
        for index, outcome in enumerate(spec.outcomes)
    )
    edges = tuple(
        StateGraphEdge(
            edge_id=GraphEdgeId(index),
            source_node_id=GraphNodeId(source),
            target_node_id=GraphNodeId(target),
            probability=probability,
            event_summary=TransitionEventSummary.empty(),
        )
        for index, (source, target, probability) in enumerate(spec.edges)
    )
    components = tuple(
        StrongComponent(
            component_id=StrongComponentId(index),
            node_ids=tuple(GraphNodeId(node_id) for node_id in node_ids),
            kind=kind,
            outgoing_component_ids=(),
            reaches_terminal=kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE,
        )
        for index, (kind, node_ids) in enumerate(spec.components)
    )
    counts = StateGraphTerminalCounts(
        attacker_wins=sum(
            outcome is GraphNodeOutcome.ATTACKER_WIN for outcome in spec.outcomes
        ),
        defender_wins=sum(
            outcome is GraphNodeOutcome.DEFENDER_WIN for outcome in spec.outcomes
        ),
        draws=sum(outcome is GraphNodeOutcome.DRAW for outcome in spec.outcomes),
        non_terminal=sum(
            outcome is GraphNodeOutcome.NON_TERMINAL for outcome in spec.outcomes
        ),
        unknown=sum(outcome is GraphNodeOutcome.UNKNOWN for outcome in spec.outcomes),
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=nodes,
        edges=edges,
        components=components,
        statistics=StateGraphStatistics(
            unique_state_count=len(nodes),
            edge_count=len(edges),
            max_turn_number=1,
            terminal_counts=counts,
            closed_cycle_count=sum(
                kind is StrongComponentKind.CLOSED_CYCLE
                for kind, _ in spec.components
            ),
            terminal_reachable_cycle_count=sum(
                kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE
                for kind, _ in spec.components
            ),
        ),
        truncation_reasons=spec.truncation_reasons,
    )


def test_solves_dag_with_exact_probabilities_and_expected_turns() -> None:
    """DAG 应使用精确概率得到手工可验证的 1/4、1/4、1/2。"""
    graph = _graph(
        _GraphSpec(
            outcomes=(
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.ATTACKER_WIN,
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.DEFENDER_WIN,
                GraphNodeOutcome.DRAW,
            ),
            edges=(
                (0, 1, Fraction(1, 4)),
                (0, 2, Fraction(3, 4)),
                (2, 3, Fraction(1, 3)),
                (2, 4, Fraction(2, 3)),
            ),
            components=tuple(
                (StrongComponentKind.ACYCLIC, (index,)) for index in range(5)
            ),
        )
    )

    result = PurePythonBattleGraphSolver().solve(graph)

    assert result.status is BattleGraphSolveStatus.SOLVED
    assert result.win_probability == Fraction(1, 4)
    assert result.loss_probability == Fraction(1, 4)
    assert result.draw_probability == Fraction(1, 2)
    assert result.probability_total == Fraction(1)
    assert result.probability_tolerance == Fraction(0)
    assert result.closed_cycle_probability == Fraction(0)
    assert result.expected_turns == ExpectedTurns(
        ExpectedTurnsStatus.FINITE,
        Fraction(7, 4),
    )


def test_closed_cycle_is_draw_with_infinite_expected_turns() -> None:
    """无出口双节点环应全部计入平局，并显式返回无限期望回合。"""
    graph = _graph(
        _GraphSpec(
            outcomes=(
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.NON_TERMINAL,
            ),
            edges=((0, 1, Fraction(1)), (1, 0, Fraction(1))),
            components=((StrongComponentKind.CLOSED_CYCLE, (0, 1)),),
        )
    )

    result = PurePythonBattleGraphSolver().solve(graph)

    assert result.win_probability == Fraction(0)
    assert result.loss_probability == Fraction(0)
    assert result.draw_probability == Fraction(1)
    assert result.closed_cycle_probability == Fraction(1)
    assert result.expected_turns.status is ExpectedTurnsStatus.INFINITE
    assert result.expected_turns.value is None


def test_geometric_exit_cycle_solves_absorption_and_expected_turns() -> None:
    """每回合一半退出的自环最终必胜，期望回合为 2。"""
    graph = _graph(
        _GraphSpec(
            outcomes=(
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.ATTACKER_WIN,
            ),
            edges=((0, 0, Fraction(1, 2)), (0, 1, Fraction(1, 2))),
            components=(
                (StrongComponentKind.TERMINAL_REACHABLE_CYCLE, (0,)),
                (StrongComponentKind.ACYCLIC, (1,)),
            ),
        )
    )

    result = PurePythonBattleGraphSolver().solve(graph)

    assert result.win_probability == Fraction(1)
    assert result.loss_probability == Fraction(0)
    assert result.draw_probability == Fraction(0)
    assert result.closed_cycle_probability == Fraction(0)
    assert result.expected_turns == ExpectedTurns(
        ExpectedTurnsStatus.FINITE,
        Fraction(2),
    )


def test_mixed_terminal_cycle_preserves_observer_relative_probabilities() -> None:
    """循环出口混合三类终局时，双方观察方应只交换胜负字段。"""
    graph = _graph(
        _GraphSpec(
            outcomes=(
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.ATTACKER_WIN,
                GraphNodeOutcome.DEFENDER_WIN,
                GraphNodeOutcome.DRAW,
            ),
            edges=(
                (0, 0, Fraction(1, 2)),
                (0, 1, Fraction(1, 12)),
                (0, 2, Fraction(1, 6)),
                (0, 3, Fraction(1, 4)),
            ),
            components=(
                (StrongComponentKind.TERMINAL_REACHABLE_CYCLE, (0,)),
                (StrongComponentKind.ACYCLIC, (1,)),
                (StrongComponentKind.ACYCLIC, (2,)),
                (StrongComponentKind.ACYCLIC, (3,)),
            ),
        )
    )

    attacker_view = PurePythonBattleGraphSolver().solve(graph)
    defender_view = PurePythonBattleGraphSolver().solve(
        graph,
        BattleSide.DEFENDER,
    )

    assert attacker_view.win_probability == Fraction(1, 6)
    assert attacker_view.loss_probability == Fraction(1, 3)
    assert attacker_view.draw_probability == Fraction(1, 2)
    assert defender_view.win_probability == attacker_view.loss_probability
    assert defender_view.loss_probability == attacker_view.win_probability
    assert defender_view.draw_probability == attacker_view.draw_probability
    assert attacker_view.expected_turns.value == Fraction(2)


def test_truncated_graph_returns_explicit_incomplete_status() -> None:
    """截断图不得暴露部分概率或伪造期望回合。"""
    graph = _graph(
        _GraphSpec(
            outcomes=(GraphNodeOutcome.UNKNOWN,),
            edges=(),
            components=((StrongComponentKind.ACYCLIC, (0,)),),
            truncation_reasons=(GraphTruncationReason.MAX_TURNS,),
        )
    )

    result = PurePythonBattleGraphSolver().solve(graph)

    assert result.status is BattleGraphSolveStatus.INCOMPLETE_GRAPH
    assert result.win_probability is None
    assert result.loss_probability is None
    assert result.draw_probability is None
    assert result.expected_turns.status is ExpectedTurnsStatus.UNAVAILABLE
    assert result.diagnostics == ("graph truncated: max-turns",)


def test_equation_limit_and_singular_system_are_explicit() -> None:
    """方程规模保护和错误 SCC 元数据应返回不同失败状态。"""
    cyclic_graph = _graph(
        _GraphSpec(
            outcomes=(
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.NON_TERMINAL,
                GraphNodeOutcome.ATTACKER_WIN,
            ),
            edges=(
                (0, 1, Fraction(1)),
                (1, 0, Fraction(1, 2)),
                (1, 2, Fraction(1, 2)),
            ),
            components=(
                (StrongComponentKind.TERMINAL_REACHABLE_CYCLE, (0, 1)),
                (StrongComponentKind.ACYCLIC, (2,)),
            ),
        )
    )
    resource_result = PurePythonBattleGraphSolver(max_equation_nodes=1).solve(
        cyclic_graph
    )
    singular_graph = _graph(
        _GraphSpec(
            outcomes=(GraphNodeOutcome.NON_TERMINAL,),
            edges=((0, 0, Fraction(1)),),
            components=(
                (StrongComponentKind.TERMINAL_REACHABLE_CYCLE, (0,)),
            ),
        )
    )
    singular_result = PurePythonBattleGraphSolver().solve(singular_graph)

    assert resource_result.status is BattleGraphSolveStatus.RESOURCE_LIMIT_EXCEEDED
    assert singular_result.status is BattleGraphSolveStatus.SINGULAR_SYSTEM
    assert resource_result.expected_turns.status is ExpectedTurnsStatus.UNAVAILABLE
    assert singular_result.expected_turns.status is ExpectedTurnsStatus.UNAVAILABLE


def test_use_case_accepts_fake_solver_without_algorithm_dependency() -> None:
    """application 用例应只依赖 Protocol，并把图和观察方原样交给 fake。"""
    expected = BattleGraphSolveResult(
        status=BattleGraphSolveStatus.SOLVED,
        observer=BattleSide.DEFENDER,
        win_probability=Fraction(1),
        loss_probability=Fraction(0),
        draw_probability=Fraction(0),
        closed_cycle_probability=Fraction(0),
        expected_turns=ExpectedTurns(ExpectedTurnsStatus.FINITE, Fraction(3)),
    )

    @dataclass(slots=True)
    class _FakeSolver:
        """记录调用参数并返回测试预置结果。

        Args:
            result: 每次调用都返回的预置求解结果。
            calls: 已收到的图和观察方参数列表，会被原地追加。
        """

        result: BattleGraphSolveResult
        calls: list[tuple[StateGraphBuildResult, BattleSide]]

        @property
        def solver_id(self) -> str:
            """返回 fake 的稳定标识。"""
            return "fake"

        def solve(
            self,
            graph: StateGraphBuildResult,
            observer: BattleSide = BattleSide.ATTACKER,
        ) -> BattleGraphSolveResult:
            """记录调用并返回预置结果。

            Args:
                graph: 用例传入的状态图结果。
                observer: 用例传入的观察方。

            Returns:
                构造 fake 时预置的同一个结果对象。
            """
            self.calls.append((graph, observer))
            return self.result

    graph = _graph(
        _GraphSpec(
            outcomes=(GraphNodeOutcome.ATTACKER_WIN,),
            edges=(),
            components=((StrongComponentKind.ACYCLIC, (0,)),),
        )
    )
    fake = _FakeSolver(expected, [])

    actual = SolveBattleGraphUseCase(fake).execute(graph, BattleSide.DEFENDER)

    assert actual is expected
    assert fake.calls == [(graph, BattleSide.DEFENDER)]
