"""真实 C++ 不可变构图/事件历史与原 Python builder 差分，不使用假战斗推演结果。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.solver.models import GraphTruncationReason, StateGraphLimits
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.inference_rules import CycleResolution
from pokeop.domain.battle.state import BattlePhase, BattleState
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary, TransitionEventType, WeightedTransition
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_graph import Component, GraphNodeOutcome
from tests.migration.test_core_state import BattleSnapshot, _StateOracle, _reference


class _Contract(BaseModel):
    """仅边界承担 JSON，内部调用原声明式领域类型，不另写 schema engine。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ExpansionMode(str, Enum):
    """仅用于差分的四种明确扩展脚本，不作为完整回合机制对外提供。"""

    DECREMENT = "decrement"
    BINARY = "binary"
    CYCLE = "cycle"
    EMPTY = "empty"


class BuildInput(_Contract):
    """初始完整状态、实际脚本和构图保护的固定测试协议。"""

    initial: BattleSnapshot
    mode: ExpansionMode
    limits: StateGraphLimits


class RandomEvent(_Contract):
    """普通随机事件的完整投影，任意精度解释数值编码成字符串。"""

    kind: Literal["random"] = "random"
    event_type: TransitionEventType
    event_id: str
    outcome_id: str
    numeric_value: str | None


class BusinessEvent(_Contract):
    """业务事件类型及全部事实，不能只比较生成的来源字符串。"""

    kind: Literal["battle"] = "battle"
    event_type: Literal[TransitionEventType.CUSTOM]
    event_id: str
    outcome_id: str
    numeric_value: str | None
    battle_kind: BattleEventKind
    turn_number: int
    actor: BattleSide | None
    target: BattleSide | None
    move_id: int | None
    source_identifier: str | None
    value: str | None
    before: str | None
    after: str | None


Event = Annotated[RandomEvent | BusinessEvent, Field(discriminator="kind")]


class WeightedPath(_Contract):
    """同一后继的替代历史与条件权重，不把不同历史等概率化。"""

    events: tuple[Event, ...]
    probability: ExactFraction


class NodeReply(_Contract):
    """BFS 每个节点、完整状态、终局原因与首次发现代表路径。"""

    id: int
    state: BattleSnapshot
    outcome: GraphNodeOutcome
    reason: TerminationReason | GraphTruncationReason | None
    predecessor_node: int | None
    predecessor_edge: int | None
    path: tuple[int, ...]


class EdgeReply(_Contract):
    """每条边的完整后继概率和实际事件历史，不只校验边数。"""

    id: int
    source: int
    target: int
    probability: ExactFraction
    paths: tuple[WeightedPath, ...]
    source_key: str | None


class TerminalCounts(_Contract):
    """五个互斥节点类别的完整数量。"""

    attacker_wins: int
    defender_wins: int
    draws: int
    non_terminal: int
    unknown: int


class BuildStatistics(_Contract):
    """原始规模、回合与 SCC 数量，和每个具体图字段同时比较。"""

    nodes: int
    edges: int
    max_turn_number: int
    closed_cycles: int
    terminal_reachable_cycles: int
    terminal_counts: TerminalCounts


class BuildReply(_Contract):
    """真实 Core 完整输出；缺字段、未知字段或半套结果均不能通过。"""

    nodes: tuple[NodeReply, ...]
    edges: tuple[EdgeReply, ...]
    components: tuple[Component, ...]
    truncations: tuple[GraphTruncationReason, ...]
    statistics: BuildStatistics


@dataclass(frozen=True)
class _ScriptedExpander:
    """只为检查通用构图/转移语义提供可重放输入，不复制 Python builder 的算法。"""

    mode: ExpansionMode

    def expand(self, state: BattleState) -> tuple[WeightedTransition[BattleState], ...]:
        """state 为父节点；返回明确不可变分支，Core 使用相同测试输入而非另一份 BFS。"""
        if self.mode is ExpansionMode.EMPTY:
            return ()
        if self.mode is ExpansionMode.CYCLE:
            return (WeightedTransition(Fraction(1), state.next_turn(), source_key="cycle"),)
        count = 2 if self.mode is ExpansionMode.BINARY else 1
        result: list[WeightedTransition[BattleState]] = []
        before = state.defender.current_hp
        for amount in range(1, count + 1):
            after = max(0, before - amount)
            probability = Fraction(amount, 3) if count == 2 else Fraction(1)
            random_event = TransitionEvent(TransitionEventType.DAMAGE_ROLL, "scripted-damage", str(amount), amount)
            business = BattleEvent(kind=BattleEventKind.DAMAGE, turn_number=state.turn_number,
                actor=BattleSide.ATTACKER, target=BattleSide.DEFENDER, move_id=1, source_identifier="move", value=before - after)
            target = state.with_battler(BattleSide.DEFENDER, state.defender.with_current_hp(after)).next_turn()
            result.append(WeightedTransition(probability, target, TransitionEventSummary(((random_event, business),)), f"hit-{amount}"))
        return tuple(result)


@dataclass(frozen=True)
class _BuildCase:
    """实际领域初始状态与脚本/限额，共同供旧算法和 C++ 进程使用。"""

    state: BattleState
    mode: ExpansionMode
    limits: StateGraphLimits = StateGraphLimits()


class _BuildOracle:
    """只组装输入与投影原始结果，不重写归并、SCC、BFS、限额或路径算法。"""

    @staticmethod
    def event(event: TransitionEvent) -> RandomEvent | BusinessEvent:
        """event 为原始类型化事实；返回完整边界值，业务事件先于普通基类判断。"""
        if isinstance(event, BattleEvent):
            return BusinessEvent(event_type=TransitionEventType.CUSTOM, event_id=event.event_id, outcome_id=event.outcome_id,
                numeric_value=None if event.numeric_value is None else str(event.numeric_value), battle_kind=event.kind,
                turn_number=event.turn_number, actor=event.actor, target=event.target, move_id=event.move_id, source_identifier=event.source_identifier,
                value=None if event.value is None else str(event.value), before=None if event.before_value is None else str(event.before_value),
                after=None if event.after_value is None else str(event.after_value))
        return RandomEvent(event_type=event.event_type, event_id=event.event_id, outcome_id=event.outcome_id,
            numeric_value=None if event.numeric_value is None else str(event.numeric_value))

    @classmethod
    def expected(cls, case: _BuildCase) -> BuildReply:
        """case 为相同初始状态和扩展输入；返回原正式 StateGraphBuilder 的完整图投影。"""
        graph = StateGraphBuilder(_ScriptedExpander(case.mode), case.limits).build(case.state)
        nodes = tuple(NodeReply(id=int(node.node_id), state=_StateOracle.snapshot(node.state), outcome=node.outcome,
            reason=node.termination_reason, predecessor_node=node.predecessor_node_id, predecessor_edge=node.predecessor_edge_id,
            path=tuple(int(value) for value in graph.representative_path(node.node_id))) for node in graph.nodes)
        edges = tuple(EdgeReply(id=int(edge.edge_id), source=int(edge.source_node_id), target=int(edge.target_node_id),
            probability=_StateOracle.fraction(edge.probability), source_key=edge.source_key,
            paths=tuple(WeightedPath(events=tuple(cls.event(event) for event in path), probability=_StateOracle.fraction(probability))
                for probability, path in edge.event_summary.weighted_paths)) for edge in graph.edges)
        components = tuple(Component(id=int(component.component_id), nodes=tuple(int(value) for value in component.node_ids),
            kind=component.kind, outgoing=tuple(int(value) for value in component.outgoing_component_ids), reaches_terminal=component.reaches_terminal)
            for component in graph.components)
        counts = graph.statistics.terminal_counts
        return BuildReply(nodes=nodes, edges=edges, components=components, truncations=graph.truncation_reasons,
            statistics=BuildStatistics(nodes=graph.statistics.unique_state_count, edges=graph.statistics.edge_count,
                max_turn_number=graph.statistics.max_turn_number, closed_cycles=graph.statistics.closed_cycle_count,
                terminal_reachable_cycles=graph.statistics.terminal_reachable_cycle_count,
                terminal_counts=TerminalCounts(attacker_wins=counts.attacker_wins, defender_wins=counts.defender_wins,
                    draws=counts.draws, non_terminal=counts.non_terminal, unknown=counts.unknown)))

    @classmethod
    def compare(cls, runner: Path, cases: tuple[_BuildCase, ...]) -> None:
        """runner 为真实 C++ 进程；cases 同时交给旧正式 builder，比较全部具体字段。"""
        inputs = tuple(BuildInput(initial=_StateOracle.snapshot(case.state), mode=case.mode, limits=case.limits) for case in cases)
        expected = tuple(cls.expected(case) for case in cases)
        process = subprocess.run([str(runner)], input="\n".join(value.model_dump_json() for value in inputs) + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        lines = process.stdout.splitlines()
        assert len(lines) == len(expected)
        for index, (line, reference) in enumerate(zip(lines, expected, strict=True)):
            assert BuildReply.model_validate_json(line) == reference, f"battle graph case {index} did not match"


@pytest.fixture(scope="module")
def battle_graph_runner() -> Path:
    """返回真实构图适配器；显式配置缺少二进制必须失败，未构建才解释性跳过。"""
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    directory = Path(configured).parent if configured else Path(__file__).resolve().parents[2] / "build/core"
    runner = directory / "pbi_battle_graph_vectors"
    if not runner.is_file() or not os.access(runner, os.X_OK):
        if configured:
            pytest.fail("configured core build must contain pbi_battle_graph_vectors")
        pytest.skip("run make test-core to enable battle graph differential tests")
    return runner


class TestCoreBattleGraph:
    """检查原子构图、条件历史、全部状态和真实保护语义，完整回合另行迁移。"""

    def test_generated_graphs_and_weighted_event_paths(self, battle_graph_runner: Path) -> None:
        """battle_graph_runner 为真实 Core；96 组图覆盖双方终局、分支、闭环和各预算组合。"""
        randomizer = random.Random(63049)
        reference = _reference()
        cases: list[_BuildCase] = []
        for _ in range(96):
            state = replace(reference, rules=replace(reference.rules,
                cycle_resolution=randomizer.choice(tuple(CycleResolution)), max_turns=randomizer.choice((None, 2, 100))))
            state = state.with_battler(BattleSide.DEFENDER, state.defender.with_current_hp(randomizer.randint(0, 24)))
            if randomizer.randrange(10) == 0:
                state = state.with_battler(BattleSide.ATTACKER, state.attacker.with_current_hp(0))
            if randomizer.randrange(10) == 0:
                state = replace(state, phase=BattlePhase.TERMINAL)
            limits = StateGraphLimits(max_nodes=randomizer.choice((None, 1, 4, 30)),
                max_edges=randomizer.choice((None, 1, 5, 50)), max_turns=randomizer.choice((None, 1, 3, 50)))
            cases.append(_BuildCase(state, randomizer.choice(tuple(ExpansionMode)), limits))
        _BuildOracle.compare(battle_graph_runner, tuple(cases))

    def test_atomic_node_edge_and_turn_budgets(self, battle_graph_runner: Path) -> None:
        """battle_graph_runner 为真实 Core；同状态不等概率历史和三类限额逐项对照原实现。"""
        state = _reference()
        state = state.with_battler(BattleSide.DEFENDER, state.defender.with_current_hp(7))
        cases = [_BuildCase(state, ExpansionMode.BINARY)]
        cases.extend(_BuildCase(state, ExpansionMode.BINARY, limits) for limits in (
            StateGraphLimits(max_nodes=1), StateGraphLimits(max_edges=1), StateGraphLimits(max_turns=1),
            StateGraphLimits(max_nodes=2), StateGraphLimits(max_edges=3), StateGraphLimits(max_turns=2)))
        cases.extend(_BuildCase(replace(state, rules=replace(state.rules, cycle_resolution=policy)), ExpansionMode.CYCLE)
            for policy in CycleResolution)
        cases.append(_BuildCase(state, ExpansionMode.EMPTY))
        _BuildOracle.compare(battle_graph_runner, tuple(cases))
