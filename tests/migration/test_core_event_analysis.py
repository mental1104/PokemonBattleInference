"""正式Core事件codec与原完整BattleEventAnalyzer产品图/精确求解链的独立差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.event_analysis import BattleEventAnalysisArtifact, BattleEventAnalyzer, BattleEventPredicate, BattleEventQuery, EventOccurrenceMode, EventSideRole, EventTurnRange
from pokeop.application.event_analysis.results import BattleEventAnalysisResult
from pokeop.application.solver.models import GraphEdgeId, GraphNodeId, GraphNodeOutcome, StateGraphBuildResult, StateGraphEdge, StateGraphNode, StateGraphStatistics, StateGraphTerminalCounts, StrongComponentKind
from pokeop.application.solver.strong_components import analyze_strong_components
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEvent, TransitionEventSummary, TransitionEventType
from tests.migration.test_core_battle_graph import WeightedPath, _BuildOracle
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_graph import GraphNode, GraphTruncationReason
from tests.migration.test_core_state import _StateOracle, _reference


class _Contract(BaseModel):
    """完整稳定事件边界，冻结并拒绝未知字段，不能漏证据后伪通过。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PredicateInput(_Contract):
    """原AND过滤的完整结构化字段，不检查trace或展示名称。"""

    battle_event_kinds: tuple[BattleEventKind, ...] = ()
    transition_event_types: tuple[TransitionEventType, ...] = ()
    side: BattleSide | None = None
    side_role: EventSideRole = EventSideRole.ANY
    move_id: int | None = None
    effect_identifier: str | None = None
    event_id: str | None = None
    outcome_id: str | None = None


class TurnRangeInput(_Contract):
    """任意精度回合边界按十进制保留，不截为机器整型。"""

    start_turn: str | None = None
    end_turn: str | None = None


class QueryInput(_Contract):
    """全历史查询及原有限分布上限，计数阈值保持任意精度。"""

    predicate: PredicateInput
    occurrence_mode: EventOccurrenceMode = EventOccurrenceMode.ANY
    turn_range: TurnRangeInput | None = None
    min_occurrences: str = "1"
    max_occurrences: str | None = None
    distribution_count_limit: int = 2
    distribution_turn_limit: int = 3
    max_key_event_summaries: int = 32


class EventEdge(_Contract):
    """原正式边绝对概率及各替代事件历史的条件权重，不能相互替代。"""

    source: int
    target: int
    probability: ExactFraction
    event_paths: tuple[WeightedPath, ...]


class EventGraphInput(_Contract):
    """完整图分析只需原结果/拓扑/事件/root实际回合，不传不消费的战斗快照。"""

    nodes: tuple[GraphNode, ...]
    edges: tuple[EventEdge, ...]
    root: int = 0
    root_turn_number: str = "1"
    truncations: tuple[GraphTruncationReason, ...] = ()


class EventInput(_Contract):
    """唯一正式事件分析请求，不接受预先计算的命中概率或产品图。"""

    kind: Literal["event_analysis"] = "event_analysis"
    calculation_revision: str
    inference_run_id: str
    graph: EventGraphInput
    query: QueryInput
    observer: BattleSide


class ConditionalReply(_Contract):
    """零条件质量明确不可定义，不能通过数值零伪造可计算结果。"""

    status: Literal["defined", "undefined-zero-condition"]
    value: ExactFraction | None
    condition_probability: ExactFraction


class Bucket(_Contract):
    """全部精确分布桶，包括原never和overflow。"""

    key: str
    probability: ExactFraction


class Coverage(_Contract):
    """图元数据数量覆盖，不是战斗随机概率或配置权重。"""

    total_edge_count: int
    matching_edge_count: int
    total_event_path_group_count: int
    matching_event_path_group_count: int


class KeyEvent(_Contract):
    """全部唯一事件身份和路径组计数，保留空主体/目标的业务含义。"""

    event_type: TransitionEventType
    battle_event_kind: BattleEventKind | None
    actor: BattleSide | None
    target: BattleSide | None
    move_id: int | None
    effect_identifier: str | None
    event_id: str
    outcome_id: str
    path_group_count: int


class Cost(_Contract):
    """实际原图/产品图大小及每次精确求解次数，逐字段与原实现核对。"""

    original_node_count: int
    original_edge_count: int
    product_node_count: int
    product_edge_count: int
    exact_solver_run_count: int


class EventReply(_Contract):
    """原单图事件分析全部可观察结果，缺少任一证据即失败。"""

    kind: Literal["event_analysis"]
    calculation_revision: str
    inference_run_id: str
    observer: BattleSide
    query: QueryInput
    baseline_win_probability: ExactFraction
    baseline_loss_probability: ExactFraction
    baseline_draw_probability: ExactFraction
    event_probability: ExactFraction
    event_win_joint_probability: ExactFraction
    win_given_event: ConditionalReply
    win_given_not_event: ConditionalReply
    first_occurrence_distribution: tuple[Bucket, ...]
    occurrence_count_distribution: tuple[Bucket, ...]
    path_group_coverage: Coverage
    key_events: tuple[KeyEvent, ...]
    original_probability_preserved: bool
    computation_cost: Cost


@dataclass(frozen=True)
class _Case:
    """绑定同一原完整图和查询，C++只接收未执行分析的事实投影。"""

    graph: StateGraphBuildResult
    query: BattleEventQuery
    observer: BattleSide = BattleSide.ATTACKER


class _EventOracle:
    """复用原真实图/产品分析器；只有DTO投影和独立输入生成，没有分析算法副本。"""

    @staticmethod
    def query(query: BattleEventQuery) -> QueryInput:
        """只投影原查询完整字段，任意精度阈值不经过浮点。"""
        predicate = query.predicate
        return QueryInput(predicate=PredicateInput(battle_event_kinds=predicate.battle_event_kinds,
            transition_event_types=predicate.transition_event_types, side=predicate.side, side_role=predicate.side_role,
            move_id=predicate.move_id, effect_identifier=predicate.effect_identifier, event_id=predicate.event_id, outcome_id=predicate.outcome_id),
            occurrence_mode=query.occurrence_mode, turn_range=None if query.turn_range is None else TurnRangeInput(
                start_turn=None if query.turn_range.start_turn is None else str(query.turn_range.start_turn),
                end_turn=None if query.turn_range.end_turn is None else str(query.turn_range.end_turn)),
            min_occurrences=str(query.min_occurrences), max_occurrences=None if query.max_occurrences is None else str(query.max_occurrences),
            distribution_count_limit=query.distribution_count_limit, distribution_turn_limit=query.distribution_turn_limit,
            max_key_event_summaries=query.max_key_event_summaries)

    @staticmethod
    def graph(outcomes: tuple[GraphNodeOutcome, ...], edges: tuple[tuple[int, int, Fraction, TransitionEventSummary], ...], turn: int = 1) -> StateGraphBuildResult:
        """将完整知识规格组装为原图模型，SCC仍由原分析器计算，节点使用真实BattleState。"""
        base = _reference()
        nodes: list[StateGraphNode] = []
        for index, outcome in enumerate(outcomes):
            state = replace(base, attacker=replace(base.attacker, current_hp=index + 1), turn_number=turn + index)
            nodes.append(StateGraphNode(GraphNodeId(index), state, state.state_key, outcome))
        original_edges = tuple(StateGraphEdge(GraphEdgeId(index), GraphNodeId(source), GraphNodeId(target), probability, summary)
            for index, (source, target, probability, summary) in enumerate(edges))
        components = analyze_strong_components(nodes, original_edges)
        counts = StateGraphTerminalCounts(attacker_wins=outcomes.count(GraphNodeOutcome.ATTACKER_WIN),
            defender_wins=outcomes.count(GraphNodeOutcome.DEFENDER_WIN), draws=outcomes.count(GraphNodeOutcome.DRAW),
            non_terminal=outcomes.count(GraphNodeOutcome.NON_TERMINAL), unknown=outcomes.count(GraphNodeOutcome.UNKNOWN))
        statistics = StateGraphStatistics(len(nodes), len(edges), turn + len(nodes) - 1, counts,
            sum(component.kind is StrongComponentKind.CLOSED_CYCLE for component in components),
            sum(component.kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE for component in components))
        return StateGraphBuildResult(GraphNodeId(0), tuple(nodes), original_edges, components, statistics)

    @classmethod
    def request(cls, case: _Case) -> EventInput:
        """只投影原图完整事件条件路径，不调用事件分析或提供其结果。"""
        graph = case.graph
        return EventInput(calculation_revision="analysis-v1", inference_run_id="run-unique", observer=case.observer, query=cls.query(case.query),
            graph=EventGraphInput(nodes=tuple(GraphNode(outcome=node.outcome, cycle_resolution=node.state.rules.cycle_resolution) for node in graph.nodes),
                edges=tuple(EventEdge(source=int(edge.source_node_id), target=int(edge.target_node_id), probability=_StateOracle.fraction(edge.probability),
                    event_paths=tuple(WeightedPath(events=tuple(_BuildOracle.event(event) for event in path), probability=_StateOracle.fraction(probability))
                        for probability, path in edge.event_summary.weighted_paths)) for edge in graph.edges),
                root=int(graph.root_node_id), root_turn_number=str(graph.node(graph.root_node_id).state.turn_number), truncations=graph.truncation_reasons))

    @classmethod
    def response(cls, result: BattleEventAnalysisResult) -> EventReply:
        """只把原公开结果完整投影到严格schema，共享给独立重算和配置事件差分。"""
        return EventReply(kind="event_analysis", calculation_revision=result.calculation_revision, inference_run_id=result.inference_run_id,
            observer=result.observer, query=cls.query(result.query), baseline_win_probability=_StateOracle.fraction(result.baseline_win_probability),
            baseline_loss_probability=_StateOracle.fraction(result.baseline_loss_probability), baseline_draw_probability=_StateOracle.fraction(result.baseline_draw_probability),
            event_probability=_StateOracle.fraction(result.event_probability), event_win_joint_probability=_StateOracle.fraction(result.event_win_joint_probability),
            win_given_event=ConditionalReply(status=result.win_given_event.status.value,
                value=None if result.win_given_event.value is None else _StateOracle.fraction(result.win_given_event.value),
                condition_probability=_StateOracle.fraction(result.win_given_event.condition_probability)),
            win_given_not_event=ConditionalReply(status=result.win_given_not_event.status.value,
                value=None if result.win_given_not_event.value is None else _StateOracle.fraction(result.win_given_not_event.value),
                condition_probability=_StateOracle.fraction(result.win_given_not_event.condition_probability)),
            first_occurrence_distribution=tuple(Bucket(key=bucket.key, probability=_StateOracle.fraction(bucket.probability)) for bucket in result.first_occurrence_distribution),
            occurrence_count_distribution=tuple(Bucket(key=bucket.key, probability=_StateOracle.fraction(bucket.probability)) for bucket in result.occurrence_count_distribution),
            path_group_coverage=Coverage(total_edge_count=result.path_group_coverage.total_edge_count, matching_edge_count=result.path_group_coverage.matching_edge_count,
                total_event_path_group_count=result.path_group_coverage.total_event_path_group_count, matching_event_path_group_count=result.path_group_coverage.matching_event_path_group_count),
            key_events=tuple(KeyEvent(event_type=event.event_type, battle_event_kind=event.battle_event_kind, actor=event.actor, target=event.target,
                move_id=event.move_id, effect_identifier=event.effect_identifier, event_id=event.event_id, outcome_id=event.outcome_id, path_group_count=event.path_group_count)
                for event in result.key_events), original_probability_preserved=result.original_probability_preserved,
            computation_cost=Cost(original_node_count=result.computation_cost.original_node_count, original_edge_count=result.computation_cost.original_edge_count,
                product_node_count=result.computation_cost.product_node_count, product_edge_count=result.computation_cost.product_edge_count,
                exact_solver_run_count=result.computation_cost.exact_solver_run_count))

    @classmethod
    def expected(cls, case: _Case) -> EventReply:
        """调用原公开完整analyze产生所有联合/条件概率、分布、覆盖、成本后仅做DTO转换。"""
        return cls.response(BattleEventAnalyzer().analyze(
            BattleEventAnalysisArtifact("analysis-v1", "run-unique", case.graph), case.query, case.observer))

    @classmethod
    def compare(cls, runner: Path, cases: tuple[_Case, ...]) -> None:
        """真实C++进程逐例与原完整分析器输出相等，不能用浮点容差或只比单一事件概率。"""
        requests = tuple(cls.request(case) for case in cases)
        result = subprocess.run([str(runner)], input="".join(request.model_dump_json() + "\n" for request in requests), text=True,
            capture_output=True, check=True, timeout=90)
        lines = result.stdout.splitlines()
        assert len(lines) == len(cases)
        for index, (line, case) in enumerate(zip(lines, cases, strict=True)):
            assert EventReply.model_validate_json(line) == cls.expected(case), f"event analysis case {index} differs"

    @staticmethod
    def random_summary(rng: random.Random) -> TransitionEventSummary:
        """生成随机完整元数据和精确条件权重，不生成任何分析概率或产品图。"""
        pool: tuple[TransitionEvent, ...] = tuple(BattleEvent(kind=kind, turn_number=rng.randint(1, 20),
            actor=rng.choice((None, *BattleSide)), target=rng.choice((None, *BattleSide)), move_id=rng.choice((None, 42, 105)),
            source_identifier=rng.choice((None, "paralysis", "life_orb")), value=rng.randint(0, 20)) for kind in BattleEventKind) + tuple(
                TransitionEvent(event_type=kind, event_id=f"rng-{kind.value}", outcome_id=rng.choice(("hit", "miss")), numeric_value=rng.randint(0, 100)) for kind in TransitionEventType)
        paths = tuple(tuple(rng.choice(pool) for _ in range(rng.randint(0, 4))) for _ in range(rng.randint(1, 3)))
        weights = tuple(rng.randint(1, 10) for _ in paths)
        total = sum(weights)
        return TransitionEventSummary(paths, tuple(Fraction(value, total) for value in weights))


@pytest.fixture
def event_analysis_runner() -> Path:
    """明确外部真实Core编译入口；未配置时skip，不用原Python冒充Core运行。"""
    value = os.getenv("PBI_EVENT_ANALYSIS_RUNNER")
    if value is None:
        pytest.skip("PBI_EVENT_ANALYSIS_RUNNER is required")
    path = Path(value)
    assert path.is_file()
    return path


class TestCoreEventAnalysis:
    """真实产品历史、原SCC求解、完整联合/条件指标及元数据排序差分。"""

    def test_original_analyzer_complete_metrics(self, event_analysis_runner: Path) -> None:
        """48个DAG/开放循环/封闭循环，覆盖原全部过滤字段与ANY/FIRST回合语义。"""
        rng = random.Random(60301)
        cases: list[_Case] = []
        for case in range(48):
            cyclic = case >= 32
            closed = case >= 44
            if cyclic:
                outcomes = (GraphNodeOutcome.NON_TERMINAL,) if closed else (GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN, GraphNodeOutcome.DEFENDER_WIN)
                specs = ((0, 0, Fraction(1), _EventOracle.random_summary(rng)),) if closed else (
                    (0, 0, Fraction(1, 3), _EventOracle.random_summary(rng)), (0, 1, Fraction(1, 3), _EventOracle.random_summary(rng)),
                    (0, 2, Fraction(1, 3), _EventOracle.random_summary(rng)))
            else:
                outcomes = (GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN, GraphNodeOutcome.DEFENDER_WIN, GraphNodeOutcome.DRAW)
                specs = ((0, 1, Fraction(1, 2), _EventOracle.random_summary(rng)), (0, 2, Fraction(1, 2), _EventOracle.random_summary(rng)),
                    (1, 2, Fraction(1, 3), _EventOracle.random_summary(rng)), (1, 3, Fraction(1, 3), _EventOracle.random_summary(rng)),
                    (1, 4, Fraction(1, 3), _EventOracle.random_summary(rng)))
            predicate = (BattleEventPredicate(), BattleEventPredicate(battle_event_kinds=(BattleEventKind.DAMAGE, BattleEventKind.HIT)),
                BattleEventPredicate(transition_event_types=(TransitionEventType.HIT_CHECK,)), BattleEventPredicate(side=BattleSide.ATTACKER, side_role=EventSideRole.ACTOR),
                BattleEventPredicate(side=BattleSide.DEFENDER, side_role=EventSideRole.TARGET, move_id=42), BattleEventPredicate(effect_identifier="paralysis"),
                BattleEventPredicate(outcome_id="hit"), BattleEventPredicate(event_id="rng-custom"))[case % 8]
            minimum = rng.randint(0, 2)
            query = BattleEventQuery(predicate=predicate, occurrence_mode=rng.choice(tuple(EventOccurrenceMode)),
                turn_range=rng.choice((None, EventTurnRange(1, 2), EventTurnRange(2, None), EventTurnRange(None, 1))),
                min_occurrences=minimum, max_occurrences=rng.choice((None, minimum, minimum + 2)), distribution_count_limit=2,
                distribution_turn_limit=3, max_key_event_summaries=rng.choice((1, 4, 32)))
            cases.append(_Case(_EventOracle.graph(outcomes, specs, turn=rng.choice((1, 2, 5))), query, rng.choice(tuple(BattleSide))))
        _EventOracle.compare(event_analysis_runner, tuple(cases))

    def test_original_distinct_value_metadata_identity(self, event_analysis_runner: Path) -> None:
        """同摘要身份的不同numeric值先保留完整事件去重，计数历史与元数据覆盖各沿原语义。"""
        first = TransitionEvent(event_type=TransitionEventType.HIT_CHECK, event_id="accuracy", outcome_id="hit", numeric_value=1)
        second = replace(first, numeric_value=2)
        graph = _EventOracle.graph((GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN),
            ((0, 1, Fraction(1), TransitionEventSummary(((first, second, first),), (Fraction(1),))),))
        query = BattleEventQuery(predicate=BattleEventPredicate(outcome_id="hit"), min_occurrences=3, max_occurrences=3,
            distribution_count_limit=2, distribution_turn_limit=2)
        _EventOracle.compare(event_analysis_runner, (_Case(graph, query),))

    def test_exact_large_count_and_turn_boundaries(self, event_analysis_runner: Path) -> None:
        """百位计数阈值/回合与有限DAG真实对照，不能在桶加一或解析时溢出机器整型。"""
        event = TransitionEvent(event_type=TransitionEventType.CUSTOM, event_id="exact", outcome_id="once")
        huge = 10**100
        graph = _EventOracle.graph((GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN),
            ((0, 1, Fraction(1), TransitionEventSummary.single(event)),), turn=huge)
        predicate = BattleEventPredicate(event_id="exact")
        query = BattleEventQuery(predicate=predicate, min_occurrences=huge, max_occurrences=huge + 1,
            distribution_count_limit=2, distribution_turn_limit=2)
        timing = BattleEventQuery(predicate=predicate, occurrence_mode=EventOccurrenceMode.FIRST, turn_range=EventTurnRange(huge, huge),
            distribution_count_limit=2, distribution_turn_limit=2)
        _EventOracle.compare(event_analysis_runner, (_Case(graph, query), _Case(graph, timing)))
