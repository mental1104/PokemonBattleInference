"""原根行动精确归因与Core同次固定图的完整差分，所有expected来自原求解/归因。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.solver.graph_explanation import build_root_action_pair_explanation
from pokeop.application.solver.models import GraphEdgeId, GraphNodeId, GraphNodeOutcome, StateGraphBuildResult, StateGraphEdge, StateGraphLimits, StateGraphNode
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.solver.summary_state_graph import SummaryStateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide, TerminationReason
from pokeop.domain.battle.state import BattleState, StateKey
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary
from tests.migration.test_core_actions_abi import ActionStrategy
from tests.migration.test_core_battle_graph import BuildReply, WeightedPath, _BuildOracle
from tests.migration.test_core_state import _StateOracle, _reference
from tests.migration.test_core_turn import Mode, _TurnCase, _TurnOracle
from tests.migration.test_core_turn_abi import FixedOperation, FixedResult, _ABIOracle
from tests.migration.test_core_winning_paths import _GraphFixtures


class _Contract(BaseModel):
    """稳定完整边界模型，未知/缺失字段不能通过省略检查隐藏。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Fraction(_Contract):
    """原归因仅分子/分母/decimal三个字段，没有projection的percent。"""
    numerator: str
    denominator: str
    decimal: float


class _Root(_Contract):
    """根价值按攻击方/防守方固定轴表达，不能随caller observer交换。"""
    node_id: int
    attacker_win: _Fraction
    defender_win: _Fraction
    draw: _Fraction


class _Bucket(_Contract):
    """原实际MOVE_USED行动簇的全部条件/贡献/代表节点和历史条数。"""
    attacker_move_id: int | None
    defender_move_id: int | None
    probability: _Fraction
    attacker_win_contribution: _Fraction
    defender_win_contribution: _Fraction
    draw_contribution: _Fraction
    conditional_attacker_win: _Fraction
    conditional_defender_win: _Fraction
    conditional_draw: _Fraction
    representative_target_node_id: int | None
    path_count: int


class _Counts(_Contract):
    """原实际完整图规模，不计摘要中的桶/替代事件数量。"""
    nodes: int
    edges: int


class _Explanation(_Contract):
    """原explanation.v1完整DTO，不允许拿engine元数据当业务解释。"""
    version: Literal["battle-inference.explanation.v1"]
    basis: Literal["root-action-pair-attribution"]
    coverage: _Fraction
    root: _Root
    buckets: tuple[_Bucket, ...]
    omitted_bucket_count: int
    graph: _Counts


class _RootSummary(_Contract):
    """原summary执行端在root单独保存的完整目标事件历史。"""
    target: int
    paths: tuple[WeightedPath, ...]


class _Diagnostic(_Contract):
    """只用于验证纯图算法，不是公开ABI kind或替代真实回合的生产入口。"""
    kind: Literal["root_action_explanation_fixture"] = "root_action_explanation_fixture"
    graph: BuildReply
    max_buckets: int = 12
    root_summaries: tuple[_RootSummary, ...] = ()


class _FixedOperation(FixedOperation):
    """真实fixed_battle的唯一新增opt-in，同次typed构图保留完整原结果。"""
    include_root_action_explanation: Literal[True] = True
    graph_mode: Literal["full", "configuration_summary"] = "full"


class _FixedResult(FixedResult):
    """完整原固定输出与可空解释，不把截断/无法归因变成全零解释。"""
    root_action_explanation: _Explanation | None


@dataclass(frozen=True)
class _DiagnosticCase:
    """原正式图、原根历史覆盖和TopK原参数，不保存Cpp生成的expected。"""
    graph: StateGraphBuildResult
    max_buckets: int = 12
    summaries: tuple[tuple[int, TransitionEventSummary], ...] = ()

    def original(self) -> _Explanation:
        """只调用原唯一归因函数；根覆盖表由原target.state_key映射，不重算概率。"""
        return _Explanation.model_validate(build_root_action_pair_explanation(graph=self.graph,
            root_event_summary_by_state_key={self.graph.nodes[target].state_key: summary for target, summary in self.summaries},
            max_buckets=self.max_buckets))

    def request(self) -> _Diagnostic:
        """返回完整原records/历史的机械投影，所有数据仍由Core唯一reader验证。"""
        return _Diagnostic(graph=_BuildOracle.graph(self.graph), max_buckets=self.max_buckets,
            root_summaries=tuple(_RootSummary(target=target, paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path),
                probability=_StateOracle.fraction(probability)) for probability, path in summary.weighted_paths)) for target, summary in self.summaries))


class _Fixtures:
    """按原模型构造归因独有边界，借用原builder/SCC而不模拟待测算法。"""

    @staticmethod
    def history(attacker: int, defender: int, *, blocked: bool = False) -> tuple[TransitionEvent, ...]:
        """attacker/defender为真正used ID，blocked使已selected守方没有used；返回原完整业务事实。"""
        events: list[TransitionEvent] = [BattleEvent(kind=BattleEventKind.MOVE_SELECTED, turn_number=1, actor=BattleSide.ATTACKER, move_id=999)]
        events.extend((BattleEvent(kind=BattleEventKind.MOVE_USED, turn_number=1, actor=BattleSide.ATTACKER),
            BattleEvent(kind=BattleEventKind.MOVE_USED, turn_number=1, actor=BattleSide.ATTACKER, move_id=attacker)))
        if not blocked:
            events.append(BattleEvent(kind=BattleEventKind.MOVE_USED, turn_number=1, actor=BattleSide.DEFENDER, move_id=defender))
        return tuple(events)

    @classmethod
    def graph(cls, *, reverse_weights: bool = False) -> StateGraphBuildResult:
        """reverse_weights选择不相等权重；返回16个真实终局BFS节点，覆盖Top12与稳定同贡献排序。"""
        root = _reference()
        nodes = [StateGraphNode(GraphNodeId(0), root, root.state_key, GraphNodeOutcome.NON_TERMINAL)]
        edges: list[StateGraphEdge] = []
        weights = tuple(range(1, 17)) if reverse_weights else (1,) * 16
        for index, weight in enumerate(weights):
            state = replace(root, attacker=root.attacker.with_current_hp(50 + index), defender=root.defender.with_current_hp(0), turn_number=2)
            nodes.append(StateGraphNode(GraphNodeId(index + 1), state, state.state_key, GraphNodeOutcome.ATTACKER_WIN, TerminationReason.KNOCKOUT))
            history = cls.history(1 + index // 4, 101 + index % 4)
            alternative = history + (BattleEvent(kind=BattleEventKind.DAMAGE, turn_number=1, actor=BattleSide.ATTACKER, value=index),)
            edges.append(StateGraphEdge(GraphEdgeId(index), GraphNodeId(0), GraphNodeId(index + 1), Fraction(weight, sum(weights)),
                TransitionEventSummary((history, alternative), (Fraction(1, 3), Fraction(2, 3)))))
        return _GraphFixtures.graph(tuple(nodes), tuple(edges))

    @staticmethod
    def actual_graph(case: _TurnCase, summary: bool = False) -> StateGraphBuildResult:
        """case为实际状态/双方policy/预算；返回原完整回合→BFS图，不以fixture替代正式调用链。"""
        resolver = _TurnOracle.resolver(case.state)
        expander = _PolicyDrivenBattleStateExpander(resolver, _TurnOracle.policy(case.attacker_policy), _TurnOracle.policy(case.defender_policy))
        builder = SummaryStateGraphBuilder if summary else StateGraphBuilder
        return builder(expander, case.graph_limits).build(case.state)

    @staticmethod
    def actual_explanation(case: _TurnCase, graph: StateGraphBuildResult, summary: bool) -> _Explanation | None:
        """case/graph为原完整链，summary选择独立root捕获；返回原可空增强，不从Cpp恢复预期。"""
        if not graph.is_complete:
            return None
        root_events: dict[StateKey, TransitionEventSummary] = {}
        if summary and not graph.nodes[0].is_terminal:
            expander = _PolicyDrivenBattleStateExpander(_TurnOracle.resolver(case.state), _TurnOracle.policy(case.attacker_policy), _TurnOracle.policy(case.defender_policy))
            root_events = {transition.state.state_key: transition.event_summary for transition in expander.expand(case.state)}
        return _Explanation.model_validate(build_root_action_pair_explanation(graph=graph, root_event_summary_by_state_key=root_events))


@pytest.fixture
def explanation_runner() -> Path:
    """返回正式编译runner；缺少显式原生入口时报告skip，不借Python伪造Core输出。"""
    configured = os.environ.get("PBI_GRAPH_EXPLANATION_RUNNER")
    if configured is None:
        pytest.skip("PBI_GRAPH_EXPLANATION_RUNNER is required")
    result = Path(configured)
    assert result.is_file()
    return result


class TestCoreRootActionExplanation:
    """完整原归因、实际同次固定构图、观察轴、截断及原增强可空语义。"""

    def test_full_original_root_attribution_topk_and_summary_overrides(self, explanation_runner: Path) -> None:
        """explanation_runner为真实codec；比较原16桶、非等权、全部TopK边界、根覆盖及blocked事实。"""
        cases: list[_DiagnosticCase] = []
        for unequal in (False, True):
            graph = _Fixtures.graph(reverse_weights=unequal)
            cases.extend(_DiagnosticCase(graph, count) for count in (1, 2, 12, 16, 100))
            override = TransitionEventSummary((_Fixtures.history(3, 103, blocked=True),))
            cases.append(_DiagnosticCase(graph, summaries=((1, override),)))
        expected = tuple(case.original() for case in cases)
        process = subprocess.run((str(explanation_runner),), input="".join(case.request().model_dump_json() + "\n" for case in cases),
            text=True, capture_output=True, check=True, timeout=120)
        actual = tuple(_Explanation.model_validate_json(line) for line in process.stdout.splitlines())
        assert actual == expected, process.stderr

    def test_actual_fixed_battle_same_graph_and_optional_explanation(self, explanation_runner: Path) -> None:
        """explanation_runner为真实fixed codec；双方速序/16档/终局/预算和observer都调用原完整链核验。"""
        base = _reference()
        low_defender = replace(base, defender=base.defender.with_current_hp(1))
        low_attacker = replace(base, attacker=base.attacker.with_current_hp(1))
        tied_defender = replace(low_defender.defender, spec=replace(low_defender.defender.spec,
            stats=replace(low_defender.defender.spec.stats, speed=base.attacker.spec.stats.speed)))
        tie = replace(low_defender, attacker=base.attacker.with_current_hp(1), defender=tied_defender)
        terminal = replace(base, defender=base.defender.with_current_hp(0))
        cases = tuple(_TurnCase(state, Mode.FIXED, attacker_policy=ActionStrategy.first, defender_policy=ActionStrategy.first, observer=observer,
            graph_limits=limits) for state in (low_defender, low_attacker, tie, terminal) for observer in BattleSide
            for limits in (StateGraphLimits(max_nodes=200, max_edges=800), StateGraphLimits(max_nodes=1, max_edges=800)))
        modes = (False,) * len(cases) + (True,) * len(cases)
        cases = cases + cases
        graphs = tuple(_Fixtures.actual_graph(case, summary) for case, summary in zip(cases, modes, strict=True))
        expected = tuple(_Fixtures.actual_explanation(case, graph, summary) for case, graph, summary in zip(cases, graphs, modes, strict=True))
        operations: list[_FixedOperation] = []
        for case, summary in zip(cases, modes, strict=True):
            original = _ABIOracle.request(case).operations[0]
            assert isinstance(original, FixedOperation)
            operation = _FixedOperation.model_validate(original.model_dump())
            if summary:
                operation = _FixedOperation(**operation.model_dump(exclude={"graph_mode"}), graph_mode="configuration_summary")
            operations.append(operation)
        process = subprocess.run((str(explanation_runner),), input="".join(operation.model_dump_json() + "\n" for operation in operations),
            text=True, capture_output=True, check=True, timeout=180)
        actual = tuple(_FixedResult.model_validate_json(line) for line in process.stdout.splitlines())
        assert len(actual) == len(cases), process.stderr
        for result, explanation, graph in zip(actual, expected, graphs, strict=True):
            assert result.root_action_explanation == explanation
            assert result.graph == _BuildOracle.graph(graph)
