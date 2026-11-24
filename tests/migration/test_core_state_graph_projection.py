"""原application节点投影与真实Core完整字段差分，原测试仅观察输入/输出，不替换规则。"""

from __future__ import annotations

import os
import random
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, TypeAdapter

from pokeop.application.solver.models import GraphEdgeId, GraphNodeId, GraphNodeOutcome, GraphTruncationReason, StateGraphLimits, StateGraphNode
from pokeop.application.solver.state_graph import StateGraphBuilder
from pokeop.application.use_cases.infer_one_on_one_battle._core import _PolicyDrivenBattleStateExpander
from pokeop.application.state_graph_projection import BattleNodeProjection, ProbabilityProjection, StateGraphProjectionUseCase
from pokeop.application import state_graph_projection as projection
from pokeop.application.use_cases import fixed_battle_snapshot as snapshot
from pokeop.application.solver.models import StateGraphEdge
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary, TransitionEventType
from pokeop.application.state_graph_exploration import ExplorationCursor
from pokeop.application.use_cases.battle_exploration import BuildBattleReportUseCase
from pokeop.application.use_cases.battle_exploration.models import BattleReport, BattleReportStep
from tests.application.use_cases import test_battle_exploration_report as reports
from tests.application import test_state_graph_projection as original
from tests.application import test_joint_action_projection as joint
from tests.migration.test_core_actions_abi import ActionStrategy
from tests.migration.test_core_turn import _TurnOracle, _TurnCase, Mode
from tests.migration.test_core_turn_abi import FixedOperation, FixedResult, _ABIOracle
from pokeop.application.use_cases.infer_one_on_one_battle import _core
from pokeop.domain.battle.inference_outcome import BattleSide
from tests.migration.test_core_battle_graph import WeightedPath, _BuildOracle
from pokeop.domain.battle.inference_outcome import TerminationReason
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_state import BattleSnapshot, _StateOracle, _reference


class ProjectionNodeRecord(BaseModel):
    """完整原图节点记录，任意精度身份统一十进制文本，其余复用正式状态模型。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    state: BattleSnapshot
    outcome: GraphNodeOutcome
    reason: TerminationReason | GraphTruncationReason | None
    predecessor_node: str | None
    predecessor_edge: str | None
    path: tuple[str, ...]


class ProjectionEdgeRecord(BaseModel):
    """正式边或即时快照边的全部事实，身份传输不受JSON安全整数约束。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    source: str
    target: str
    probability: ExactFraction
    paths: tuple[WeightedPath, ...]
    source_key: str | None


class ProjectionRequest(BaseModel):
    """完整单节点原图切片；直接复用原已有原始graph边界模型，不产生预计算组或概率。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["state_graph_projection"] = "state_graph_projection"
    mode: Literal["node"] = "node"
    node: ProjectionNodeRecord
    outgoing_edges: tuple[ProjectionEdgeRecord, ...]
    cumulative_probability: ExactFraction
    expanded_group_ids: tuple[str, ...]


class ProjectionReply(BaseModel):
    """完整原公开读取DTO；Pydantic仅把ABI任意精度文本转回原整数类型，无业务转换。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["state_graph_projection"]
    mode: Literal["node"]
    projection: BattleNodeProjection


class ProjectionStepRequest(BaseModel):
    """单边原始记录与已由原/Core计算的前缀概率，不需要传整图或自行分组。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["state_graph_projection"] = "state_graph_projection"
    mode: Literal["step"] = "step"
    node: ProjectionNodeRecord
    outgoing_edges: tuple[ProjectionEdgeRecord, ...]
    cumulative_probability: ExactFraction
    edge_id: str
    depth: int


class ProjectionStepReply(BaseModel):
    """原战报一步完整模型，任意精度文本仅做类型化无损解码。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["state_graph_projection"]
    mode: Literal["step"]
    step: BattleReportStep


class RepresentativeFixedRequest(FixedOperation):
    """在正式fixed_battle合同中仅选择可选代表路径，不改变默认图/方程/规则预算。"""

    include_representative_paths: Literal[True] = True


class RepresentativeFixedReply(FixedResult):
    """完整正式图/解加原轻量代表路径，原事实DTO仍按全部字段严格比较。"""

    representative_paths: tuple[_core.RepresentativeBattlePath, ...]


@dataclass(frozen=True)
class _ObservedProjection:
    """同一次原调用的完整输入与真实原结果，防止测试独立实现预期算法。"""

    request: ProjectionRequest
    expected: BattleNodeProjection


class _ProjectionOracle:
    """调用原公开投影和原graph codec，既不模拟Core，也不重算分组/伤害/概率。"""

    @staticmethod
    def observe(owner: StateGraphProjectionUseCase, node: StateGraphNode, cumulative_probability: Fraction,
                expanded_group_ids: frozenset[str], expected: BattleNodeProjection) -> _ObservedProjection:
        """owner/node来自原真实调用；expected由未改动原函数计算，返回拥有的验收输入。"""
        record = ProjectionNodeRecord(id=str(node.node_id), state=_StateOracle.snapshot(node.state), outcome=node.outcome,
            reason=node.termination_reason, predecessor_node=None if node.predecessor_node_id is None else str(node.predecessor_node_id),
            predecessor_edge=None if node.predecessor_edge_id is None else str(node.predecessor_edge_id),
            path=tuple(str(value) for value in owner.graph.representative_path(node.node_id)))
        edges = tuple(ProjectionEdgeRecord(id=str(edge.edge_id), source=str(edge.source_node_id), target=str(edge.target_node_id),
            probability=_StateOracle.fraction(edge.probability), source_key=edge.source_key,
            paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path), probability=_StateOracle.fraction(probability))
                for probability, path in edge.event_summary.weighted_paths))
            for edge in owner.graph.edges if edge.source_node_id == node.node_id)
        return _ObservedProjection(ProjectionRequest(node=record, outgoing_edges=edges,
            cumulative_probability=_StateOracle.fraction(cumulative_probability), expanded_group_ids=tuple(expanded_group_ids)), expected)

    @staticmethod
    def compare(runner: Path, observed: tuple[_ObservedProjection, ...]) -> None:
        """runner必须真实可执行；每个原调用完整响应包含所有字段，精确值和浮点展示均直接比较。"""
        result = subprocess.run([str(runner)], input="".join(value.request.model_dump_json() + "\n" for value in observed),
            text=True, capture_output=True, check=True, timeout=30)
        lines = tuple(result.stdout.splitlines())
        assert len(lines) == len(observed)
        adapter = TypeAdapter(BattleNodeProjection)
        for line, value in zip(lines, observed, strict=True):
            actual = ProjectionReply.model_validate_json(line)
            assert adapter.dump_python(actual.projection, mode="json") == adapter.dump_python(value.expected, mode="json")


@pytest.fixture
def projection_runner() -> Path:
    """显式真实Core入口；缺环境单列SKIP，不能将原Python运行当作迁移验收通过。"""
    value = os.getenv("PBI_STATE_GRAPH_PROJECTION_RUNNER")
    if value is None:
        pytest.skip("PBI_STATE_GRAPH_PROJECTION_RUNNER is required")
    path = Path(value)
    assert path.is_file()
    return path


class TestCoreStateGraphProjection:
    """完整原合成图场景与真实联合回合图，覆盖渐进展开的所有事件和离散伤害结果。"""

    @pytest.mark.parametrize("scenario", (
        original.test_node_detail_projects_complete_json_friendly_battle_state,
        original.test_sixteen_distinct_damage_rolls_form_one_collapsed_damage_group,
        original.test_rounded_duplicate_rolls_keep_four_raw_paths_but_two_outcomes,
        original.test_all_knockout_rolls_merge_to_one_outcome_and_preserve_actual_hp_loss,
        original.test_hit_and_miss_share_one_hit_check_group_with_structured_events,
        original.test_strategy_selection_variants_take_precedence_over_internal_randomness,
        original.test_mixed_first_random_mechanisms_form_composite_group_and_keep_paths,
        joint.test_same_formal_edge_is_split_into_exact_joint_action_groups,
        joint.test_joint_action_outcomes_keep_conditional_probability_and_discrete_rolls,
    ), ids=lambda scenario: scenario.__name__.removeprefix("test_"))
    def test_original_projection_scenarios(self, projection_runner: Path, monkeypatch: pytest.MonkeyPatch,
                                            scenario: Callable[[], None]) -> None:
        """只观察原_project调用并原样返回真实结果；原测试全部断言仍实际执行，不注入预制结果。"""
        implementation = StateGraphProjectionUseCase._project
        observed: list[_ObservedProjection] = []

        def observe(owner: StateGraphProjectionUseCase, *, node: StateGraphNode, cumulative_probability: Fraction,
                    expanded_group_ids: frozenset[str]) -> BattleNodeProjection:
            """记录当前原输入/原完整结果；执行顺序和返回值保持不变，无规则/solver替换。"""
            expected = implementation(owner, node=node, cumulative_probability=cumulative_probability, expanded_group_ids=expanded_group_ids)
            observed.append(_ProjectionOracle.observe(owner, node, cumulative_probability, expanded_group_ids, expected))
            return expected

        monkeypatch.setattr(StateGraphProjectionUseCase, "_project", observe)
        scenario()
        assert observed
        _ProjectionOracle.compare(projection_runner, tuple(observed))

    def test_exact_fraction_display_and_subnormal_ties(self, projection_runner: Path) -> None:
        """完整1024位以内分数、binary64半值和subnormal展示必须与原Fraction完全一致。"""
        node = original._node(0, _reference())
        graph = original._graph((node,), ())
        owner = StateGraphProjectionUseCase("fraction-display", graph)
        values = (Fraction(0), Fraction(1), Fraction((2**80) + 7, (2**96) + 33),
            Fraction(1, 2**1075), Fraction(3, 2**1075), Fraction(5, 2**1075), Fraction(1, 2**1074),
            Fraction((2**53) + 1, 2**54), Fraction((2**53) + 3, 2**54))
        observed = tuple(_ProjectionOracle.observe(owner, node, value, frozenset(),
            owner.project_node(node.node_id, cumulative_probability=value)) for value in values)
        _ProjectionOracle.compare(projection_runner, observed)

    def test_real_structured_turn_graphs(self, projection_runner: Path) -> None:
        """真实原resolver→策略→BFS的8个图，对所有节点折叠/展开完整事实，不构造假伤害结果。"""
        randomizer = random.Random(618871)
        observed: list[_ObservedProjection] = []
        for index in range(8):
            state = _TurnOracle.random_state(randomizer)
            expander = _PolicyDrivenBattleStateExpander(_TurnOracle.resolver(state),
                _TurnOracle.policy(ActionStrategy.uniform), _TurnOracle.policy(ActionStrategy.uniform))
            graph = StateGraphBuilder(expander, StateGraphLimits(max_nodes=512, max_edges=2048, max_turns=state.turn_number + 1)).build(state)
            owner = StateGraphProjectionUseCase(f"real-turn-{index}", graph)
            for node in graph.nodes:
                cumulative = Fraction(3, 7)
                collapsed = owner.project_node(node.node_id, cumulative_probability=cumulative)
                observed.append(_ProjectionOracle.observe(owner, node, cumulative, frozenset(), collapsed))
                expanded = frozenset(group.group_id for group in collapsed.transition_groups)
                if expanded:
                    observed.append(_ProjectionOracle.observe(owner, node, cumulative, expanded,
                        owner.project_node(node.node_id, cumulative_probability=cumulative, expanded_group_ids=expanded)))
        _ProjectionOracle.compare(projection_runner, tuple(observed))

    @pytest.mark.parametrize("scenario", (
        reports.test_reports_preserve_distinct_merge_paths_and_edge_alternatives,
        reports.test_report_keeps_cycle_back_edge_and_repeated_root_node,
        reports.test_report_step_probabilities_are_exact_prefix_products,
    ), ids=lambda scenario: scenario.__name__.removeprefix("test_"))
    def test_original_report_steps(self, projection_runner: Path, monkeypatch: pytest.MonkeyPatch,
                                   scenario: Callable[[], None]) -> None:
        """原store/explorer/report全部实际运行，Core逐步结果含全部替代历史，最终不得只保留代表路径。"""
        implementation = BuildBattleReportUseCase.execute
        requests: list[ProjectionStepRequest] = []
        expected: list[BattleReportStep] = []

        def observe(owner: BuildBattleReportUseCase, graph_id: str, calculation_revision: str,
                    cursor: ExplorationCursor) -> BattleReport:
            """只记录原实际report步骤，返回原结果且保留原用例所有异常/断言行为。"""
            report = implementation(owner, graph_id, calculation_revision, cursor)
            graph = owner.graph_store.get(graph_id).graph
            projection_owner = StateGraphProjectionUseCase(graph_id, graph)
            previous = Fraction(1)
            for step in report.steps:
                node = graph.node(step.source_node_id)
                raw = _ProjectionOracle.observe(projection_owner, node, previous, frozenset(),
                    projection_owner.project_node(node.node_id, cumulative_probability=previous)).request
                requests.append(ProjectionStepRequest(node=raw.node, outgoing_edges=tuple(edge for edge in raw.outgoing_edges if edge.id == str(step.edge_id)),
                    cumulative_probability=raw.cumulative_probability, edge_id=str(step.edge_id), depth=step.depth))
                expected.append(step)
                previous = Fraction(int(step.cumulative_probability.numerator), int(step.cumulative_probability.denominator))
            return report

        monkeypatch.setattr(BuildBattleReportUseCase, "execute", observe)
        scenario()
        assert requests
        result = subprocess.run([str(projection_runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=30)
        lines = tuple(result.stdout.splitlines())
        assert len(lines) == len(expected)
        adapter = TypeAdapter(BattleReportStep)
        for line, step in zip(lines, expected, strict=True):
            actual = ProjectionStepReply.model_validate_json(line)
            assert adapter.dump_python(actual.step, mode="json") == adapter.dump_python(step, mode="json")

    @pytest.mark.parametrize("depth", (1, 5, 16, 200))
    def test_original_snapshot_arbitrary_precision_node_identity(self, projection_runner: Path, depth: int) -> None:
        """按原snapshot真实ID函数走到第5/200层，完整组ID/目标ID/条件概率不能溢出或变成浮点。"""
        state = _reference()
        node_id = GraphNodeId(0)
        for _ in range(depth):
            node_id = snapshot._target_node_id(node_id, 0)
        if depth >= 5:
            assert node_id > 2**64
        source = snapshot._node(node_id=node_id, state=state)
        expander = _PolicyDrivenBattleStateExpander(_TurnOracle.resolver(state),
            _TurnOracle.policy(ActionStrategy.uniform), _TurnOracle.policy(ActionStrategy.uniform))
        transitions = expander.expand(state)
        edges = tuple(StateGraphEdge(edge_id=GraphEdgeId(index), source_node_id=node_id,
            target_node_id=snapshot._target_node_id(node_id, index), probability=value.probability,
            event_summary=value.event_summary, source_key=value.source_key) for index, value in enumerate(transitions))
        cumulative = Fraction(3, 7)
        collapsed = projection._transition_groups(node=source, outgoing_edges=edges, cumulative_probability=cumulative, expanded_group_ids=frozenset())
        expanded = frozenset(group.group_id for group in collapsed)
        expected = BattleNodeProjection(node=projection._node_detail(source, has_outgoing_edges=bool(edges)),
            cumulative_probability=ProbabilityProjection.from_fraction(cumulative),
            transition_groups=projection._transition_groups(node=source, outgoing_edges=edges,
                cumulative_probability=cumulative, expanded_group_ids=expanded))
        request = ProjectionRequest(node=ProjectionNodeRecord(id=str(node_id), state=_StateOracle.snapshot(state), outcome=source.outcome,
            reason=source.termination_reason, predecessor_node=None, predecessor_edge=None, path=(str(node_id),)),
            outgoing_edges=tuple(ProjectionEdgeRecord(id=str(edge.edge_id), source=str(edge.source_node_id), target=str(edge.target_node_id),
                probability=_StateOracle.fraction(edge.probability), source_key=edge.source_key,
                paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path), probability=_StateOracle.fraction(probability))
                    for probability, path in edge.event_summary.weighted_paths)) for edge in edges),
            cumulative_probability=_StateOracle.fraction(cumulative), expanded_group_ids=tuple(expanded))
        _ProjectionOracle.compare(projection_runner, (_ObservedProjection(request, expected),))

    def test_real_fixed_battle_representative_paths(self, projection_runner: Path) -> None:
        """Core真实构图后首终局/前驱路径/首历史Identity标签与原函数完整一致，含根终局与真实伤害。"""
        base = _reference()
        states = [base.with_battler(BattleSide.ATTACKER, base.attacker.with_current_hp(0)),
            base.with_battler(BattleSide.DEFENDER, base.defender.with_current_hp(0)),
            base.with_battler(BattleSide.ATTACKER, base.attacker.with_current_hp(0)).with_battler(BattleSide.DEFENDER, base.defender.with_current_hp(0))]
        for side in BattleSide:
            base = base.with_battler(side, base.battler(side).with_current_hp(20))
        states.extend((base, replace(base, rules=replace(base.rules,
            damage_policy=replace(base.rules.damage_policy, random_damage_multipliers=(0.85, 1.0))))))
        requests: list[RepresentativeFixedRequest] = []
        expected: list[tuple[_core.RepresentativeBattlePath, ...]] = []
        for state in states:
            limits = StateGraphLimits(max_nodes=256, max_edges=1024, max_turns=state.turn_number + 2)
            case = _TurnCase(state, Mode.FIXED, graph_limits=limits)
            operation = _ABIOracle.request(case).operations[0]
            assert isinstance(operation, FixedOperation)
            requests.append(RepresentativeFixedRequest.model_validate(operation.model_dump()))
            expander = _PolicyDrivenBattleStateExpander(_TurnOracle.resolver(state),
                _TurnOracle.policy(case.attacker_policy), _TurnOracle.policy(case.defender_policy))
            graph = StateGraphBuilder(expander, limits).build(state)
            expected.append(_core._representative_paths(graph))
        result = subprocess.run([str(projection_runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=60)
        lines = tuple(result.stdout.splitlines())
        assert len(lines) == len(expected)
        for line, paths in zip(lines, expected, strict=True):
            actual = RepresentativeFixedReply.model_validate_json(line)
            assert actual.representative_paths == paths

    @pytest.mark.parametrize("scenario", ("node-1000", "cumulative-1501", "edge-1501", "event-path-1501"))
    def test_original_long_projection_wire(self, projection_runner: Path, scenario: str) -> None:
        """原Python默认4300位范围内的合法长身份/精确分数不得被旧通用1024位保护静默缩小。"""
        state = _reference()
        identity = GraphNodeId(0)
        if scenario == "node-1000":
            for _ in range(1000):
                identity = snapshot._target_node_id(identity, 0)
            assert 1024 < len(str(identity)) < 4300
        source = snapshot._node(node_id=identity, state=state)
        probability = Fraction((10**1500) + 1, (3 * 10**1500) + 7)
        assert len(str(probability.numerator)) > 1024
        assert len(str(probability.denominator)) > 1024
        cumulative = probability if scenario == "cumulative-1501" else Fraction(1)
        edges: tuple[StateGraphEdge, ...] = ()
        if scenario == "edge-1501":
            edges = (StateGraphEdge(edge_id=GraphEdgeId(0), source_node_id=identity, target_node_id=GraphNodeId(1), probability=probability,
                event_summary=TransitionEventSummary.empty()),
                StateGraphEdge(edge_id=GraphEdgeId(1), source_node_id=identity, target_node_id=GraphNodeId(2), probability=1-probability,
                    event_summary=TransitionEventSummary.empty()))
        elif scenario == "event-path-1501":
            paths = ((TransitionEvent(TransitionEventType.CUSTOM, "long-path", "first"),),
                (TransitionEvent(TransitionEventType.CUSTOM, "long-path", "second"),))
            edges = (StateGraphEdge(edge_id=GraphEdgeId(0), source_node_id=identity, target_node_id=GraphNodeId(1), probability=Fraction(1),
                event_summary=TransitionEventSummary(paths, (probability, 1-probability))),)
        collapsed = projection._transition_groups(node=source, outgoing_edges=edges, cumulative_probability=cumulative, expanded_group_ids=frozenset())
        expanded = frozenset(group.group_id for group in collapsed)
        expected = BattleNodeProjection(node=projection._node_detail(source, has_outgoing_edges=bool(edges)),
            cumulative_probability=ProbabilityProjection.from_fraction(cumulative),
            transition_groups=projection._transition_groups(node=source, outgoing_edges=edges, cumulative_probability=cumulative, expanded_group_ids=expanded))
        request = ProjectionRequest(node=ProjectionNodeRecord(id=str(identity), state=_StateOracle.snapshot(state), outcome=source.outcome,
            reason=source.termination_reason, predecessor_node=None, predecessor_edge=None, path=(str(identity),)),
            outgoing_edges=tuple(ProjectionEdgeRecord(id=str(edge.edge_id), source=str(edge.source_node_id), target=str(edge.target_node_id),
                probability=_StateOracle.fraction(edge.probability), source_key=edge.source_key,
                paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path), probability=_StateOracle.fraction(weight))
                    for weight, path in edge.event_summary.weighted_paths)) for edge in edges),
            cumulative_probability=_StateOracle.fraction(cumulative), expanded_group_ids=tuple(expanded))
        _ProjectionOracle.compare(projection_runner, (_ObservedProjection(request, expected),))
