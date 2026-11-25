"""真实 C++ 概率图进程与原 Python SCC/精确求解器差分；不替代回合器验收。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveStatus,
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
    StrongComponentKind,
)
from pokeop.application.solver.strong_components import analyze_strong_components
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import CycleResolution
from pokeop.domain.battle.transitions import TransitionEventSummary
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_state import _reference


class _Contract(BaseModel):
    """固定差分边界，冻结且拒绝未知字段，不能漏字段后仍伪通过。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GraphNode(_Contract):
    """数学拓扑需要的类别与循环策略，不含数据库引用。"""

    outcome: GraphNodeOutcome
    cycle_resolution: CycleResolution = CycleResolution.DECLARE_DRAW


class GraphEdge(_Contract):
    """完整回合有向边，分数以任意长度字符串保留。"""

    source: int
    target: int
    probability: ExactFraction


class GraphInput(_Contract):
    """独立向量工具的固定合同；这是测试进程协议，尚非正式 C ABI。"""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    root: int = 0
    observer: BattleSide = BattleSide.ATTACKER
    truncations: tuple[GraphTruncationReason, ...] = ()
    max_equation_nodes: int | None = None


class Component(_Contract):
    """完整 SCC 分量，逐项核对稳定编号、成员、分类、出边与终局可达性。"""

    id: int
    nodes: tuple[int, ...]
    kind: StrongComponentKind
    outgoing: tuple[int, ...]
    reaches_terminal: bool


class ExpectedTurns(_Contract):
    """有限、无限、不可用与分数值同时核对，不能把 None 当成零。"""

    status: ExpectedTurnsStatus
    value: ExactFraction | None


class GraphReply(_Contract):
    """精确求解的完整对外投影，不使用浮点容差。"""

    components: tuple[Component, ...]
    status: BattleGraphSolveStatus
    win: ExactFraction | None
    loss: ExactFraction | None
    draw: ExactFraction | None
    closed_cycle: ExactFraction | None
    expected_turns: ExpectedTurns


class _GraphOracle:
    """仅组装旧模型并调用旧算法；不复制 C++ 图遍历或消元逻辑。"""

    @staticmethod
    def fraction(value: Fraction | None) -> ExactFraction | None:
        """value 是原算法精确值或不可用；返回字符串边界，保留空值语义。"""
        if value is None:
            return None
        return ExactFraction(numerator=str(value.numerator), denominator=str(value.denominator))

    @classmethod
    def edge(cls, source: int, target: int, probability: Fraction) -> GraphEdge:
        """source/target 是图内连续索引；probability 为精确正概率，返回只读边合同。"""
        value = cls.fraction(probability)
        assert value is not None
        return GraphEdge(source=source, target=target, probability=value)

    @classmethod
    def expected(cls, specification: GraphInput) -> GraphReply:
        """specification 为完整数学拓扑；返回原 SCC 和 solver 的每个被比较字段。"""
        base = _reference()
        nodes: list[StateGraphNode] = []
        for index, node in enumerate(specification.nodes):
            state = replace(base, rules=replace(base.rules, cycle_resolution=node.cycle_resolution))
            nodes.append(StateGraphNode(GraphNodeId(index), state, state.state_key, node.outcome))
        edges = [StateGraphEdge(GraphEdgeId(index), GraphNodeId(edge.source), GraphNodeId(edge.target),
                 edge.probability.value(), TransitionEventSummary.empty()) for index, edge in enumerate(specification.edges)]
        components = analyze_strong_components(nodes, edges)
        counts = StateGraphTerminalCounts(
            attacker_wins=sum(node.outcome is GraphNodeOutcome.ATTACKER_WIN for node in nodes),
            defender_wins=sum(node.outcome is GraphNodeOutcome.DEFENDER_WIN for node in nodes),
            draws=sum(node.outcome is GraphNodeOutcome.DRAW for node in nodes),
            non_terminal=sum(node.outcome is GraphNodeOutcome.NON_TERMINAL for node in nodes),
            unknown=sum(node.outcome is GraphNodeOutcome.UNKNOWN for node in nodes),
        )
        graph = StateGraphBuildResult(GraphNodeId(specification.root), tuple(nodes), tuple(edges), components,
            StateGraphStatistics(len(nodes), len(edges), 1, counts,
                sum(component.kind is StrongComponentKind.CLOSED_CYCLE for component in components),
                sum(component.kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE for component in components)),
            specification.truncations)
        solution = PurePythonBattleGraphSolver(specification.max_equation_nodes).solve(graph, specification.observer)
        return GraphReply(
            components=tuple(Component(id=int(component.component_id), nodes=tuple(int(value) for value in component.node_ids),
                kind=component.kind, outgoing=tuple(int(value) for value in component.outgoing_component_ids),
                reaches_terminal=component.reaches_terminal) for component in components),
            status=solution.status, win=cls.fraction(solution.win_probability), loss=cls.fraction(solution.loss_probability),
            draw=cls.fraction(solution.draw_probability), closed_cycle=cls.fraction(solution.closed_cycle_probability),
            expected_turns=ExpectedTurns(status=solution.expected_turns.status, value=cls.fraction(solution.expected_turns.value)))

    @classmethod
    def compare(cls, runner: Path, specifications: tuple[GraphInput, ...]) -> None:
        """runner 为实际 Core 可执行文件；specifications 是完整输入，逐条精确比较全部字段。"""
        expected = tuple(cls.expected(specification) for specification in specifications)
        process = subprocess.run([str(runner)], input="\n".join(value.model_dump_json() for value in specifications) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        lines = process.stdout.splitlines()
        assert len(lines) == len(expected)
        for index, (line, reference) in enumerate(zip(lines, expected, strict=True)):
            actual = GraphReply.model_validate_json(line)
            assert actual == reference, f"graph differential case {index} did not match"

    @classmethod
    def random_graph(cls, randomizer: random.Random, *, cyclic: bool, closed: bool = False) -> GraphInput:
        """randomizer 是固定种子生成器；cyclic/closed 控制有出口与封闭循环，返回归一化图。"""
        count = randomizer.randint(4, 18)
        nodes = [GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL,
            cycle_resolution=randomizer.choice(tuple(CycleResolution))) for _ in range(count)]
        nodes[-3:] = [GraphNode(outcome=outcome) for outcome in (GraphNodeOutcome.ATTACKER_WIN, GraphNodeOutcome.DEFENDER_WIN, GraphNodeOutcome.DRAW)]
        edges: list[GraphEdge] = []
        for source in range(count - 3):
            choices = list(range(count)) if cyclic else list(range(source + 1, count))
            targets = [randomizer.choice(choices) for _ in range(randomizer.randint(1, 3))]
            if cyclic:
                # 明确给每个瞬态节点一个正概率出口，随机回边仍需真实解方程。
                targets.extend([source, count - 3 + randomizer.randrange(3)])
            weights = [randomizer.randint(1, 31) for _ in targets]
            total = sum(weights)
            edges.extend(cls.edge(source, target, Fraction(weight, total)) for target, weight in zip(targets, weights, strict=True))
        if closed:
            # 最后一个边界改为封闭双节点 SCC；其上游可同时到达真实终局。
            nodes[-1] = GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL, cycle_resolution=randomizer.choice(tuple(CycleResolution)))
            nodes.append(GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL, cycle_resolution=nodes[-1].cycle_resolution))
            edges.extend((cls.edge(count - 1, count, Fraction(1)), cls.edge(count, count - 1, Fraction(1))))
        return GraphInput(nodes=tuple(nodes), edges=tuple(edges), observer=randomizer.choice(tuple(BattleSide)))


@pytest.fixture(scope="module")
def graph_runner() -> Path:
    """返回真实已构建图适配器；显式构建配置错误必须 FAIL，不通过缺文件跳过。"""
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    directory = Path(configured).parent if configured else Path(__file__).resolve().parents[2] / "build/core"
    runner = directory / "pbi_graph_vectors"
    if not runner.is_file() or not os.access(runner, os.X_OK):
        if configured:
            pytest.fail("configured core build must contain pbi_graph_vectors")
        pytest.skip("run make test-core to enable graph differential tests")
    return runner


class TestCoreGraph:
    """真实拓扑进程覆盖 DAG、循环、无限期望、截断和大整数，不宣称完整战斗迁移。"""

    def test_generated_dags_and_cyclic_absorption(self, graph_runner: Path) -> None:
        """graph_runner 为真实 Core；128 DAG/96 有出口循环/64 封闭循环逐项比较 SCC 与精确解。"""
        randomizer = random.Random(41298)
        graphs = tuple(_GraphOracle.random_graph(randomizer, cyclic=False) for _ in range(128))
        graphs += tuple(_GraphOracle.random_graph(randomizer, cyclic=True) for _ in range(96))
        graphs += tuple(_GraphOracle.random_graph(randomizer, cyclic=True, closed=True) for _ in range(64))
        _GraphOracle.compare(graph_runner, graphs)

    def test_truncation_equation_limits_and_arbitrary_precision(self, graph_runner: Path) -> None:
        """graph_runner 为真实 Core；截断不冒充平局，DAG 不受方程预算，200 位分母保持精确。"""
        randomizer = random.Random(905)
        cyclic = _GraphOracle.random_graph(randomizer, cyclic=True)
        dag = _GraphOracle.random_graph(randomizer, cyclic=False)
        graphs = [cyclic.model_copy(update={"max_equation_nodes": 1}), dag.model_copy(update={"max_equation_nodes": 1})]
        graphs.extend(cyclic.model_copy(update={"truncations": (reason,)}) for reason in GraphTruncationReason)
        graphs.append(GraphInput(nodes=(GraphNode(outcome=GraphNodeOutcome.UNKNOWN),), edges=()))
        escape = Fraction(1, 10**200 - 1)
        graphs.append(GraphInput(nodes=(GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL), GraphNode(outcome=GraphNodeOutcome.ATTACKER_WIN)),
            edges=(_GraphOracle.edge(0, 0, 1 - escape), _GraphOracle.edge(0, 1, escape))))
        _GraphOracle.compare(graph_runner, tuple(graphs))

    def test_deep_chain_without_recursive_stack(self, graph_runner: Path) -> None:
        """graph_runner 为真实 Core；2,500 深链同时对照两个迭代 SCC 和原期望回合算法。"""
        count = 2500
        nodes = (GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL),) * (count - 1) + (GraphNode(outcome=GraphNodeOutcome.ATTACKER_WIN),)
        graph = GraphInput(nodes=nodes, edges=tuple(_GraphOracle.edge(index, index + 1, Fraction(1)) for index in range(count - 1)), max_equation_nodes=1)
        _GraphOracle.compare(graph_runner, (graph,))
