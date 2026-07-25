"""验证随机战斗事件条件概率、循环求解、配置汇总与反事实合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from pokeop.application.event_analysis import (
    BattleEventAnalysisArtifact,
    BattleEventAnalyzer,
    BattleEventPredicate,
    BattleEventQuery,
    BattleRuleOverride,
    ConditionalProbabilityStatus,
    ConfigurationEventAnalysisGroup,
    CounterfactualBattleEventAnalyzer,
    CounterfactualBattleEventRequest,
    CounterfactualInferenceRequest,
    EventOccurrenceMode,
    EventSideRole,
    EventTurnRange,
    aggregate_configuration_event_analyses,
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
    StrongComponentKind,
)
from pokeop.application.solver.strong_components import analyze_strong_components
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import (
    TransitionEvent,
    TransitionEventSummary,
    TransitionEventType,
)


@dataclass(frozen=True, slots=True)
class _FakeState:
    """提供事件产品图统计所需的最小回合和稳定状态键。"""

    node_key: str
    turn_number: int = 1

    @property
    def state_key(self) -> tuple[str, str]:
        """返回测试图中唯一节点使用的稳定键。"""
        return ("fake", self.node_key)


def _blocked_event(
    *,
    side: BattleSide = BattleSide.ATTACKER,
    source_identifier: str = "paralysis",
    turn_number: int = 1,
) -> BattleEvent:
    """构造一次结构化行动阻断事件。

    Args:
        side: 被阻断行动的主体侧。
        source_identifier: 导致阻断的稳定状态或机制标识。
        turn_number: 图首次展开时记录的事件回合号。

    Returns:
        不依赖展示文本的 ``ACTION_BLOCKED`` 事件。
    """
    return BattleEvent(
        kind=BattleEventKind.ACTION_BLOCKED,
        turn_number=turn_number,
        actor=side,
        source_identifier=source_identifier,
    )


def _event_summary(
    event: TransitionEvent | None,
) -> TransitionEventSummary:
    """为测试边构造确定性空路径或单事件路径摘要。

    Args:
        event: 需要附加到边上的类型化事件；None 表示无事件路径。

    Returns:
        条件概率为 1 的事件摘要。
    """
    if event is None:
        return TransitionEventSummary.empty()
    return TransitionEventSummary.single(event)


def _build_graph(
    outcomes: tuple[GraphNodeOutcome, ...],
    edge_specs: tuple[
        tuple[int, int, Fraction, TransitionEventSummary],
        ...,
    ],
) -> StateGraphBuildResult:
    """从小型节点和边规格构造可被正式精确求解器消费的测试图。

    Args:
        outcomes: 按连续节点 ID 排列的终局或非终局类别。
        edge_specs: 每项依次为源节点、目标节点、概率和结构化事件摘要。

    Returns:
        已完成 SCC 分类和规模统计的完整有限状态图。
    """
    nodes = [
        StateGraphNode(
            node_id=GraphNodeId(index),
            state=_FakeState(str(index)),  # type: ignore[arg-type]
            state_key=("test-node", index),  # type: ignore[arg-type]
            outcome=outcome,
            termination_reason=None,
        )
        for index, outcome in enumerate(outcomes)
    ]
    edges = [
        StateGraphEdge(
            edge_id=GraphEdgeId(index),
            source_node_id=GraphNodeId(source),
            target_node_id=GraphNodeId(target),
            probability=probability,
            event_summary=summary,
        )
        for index, (source, target, probability, summary) in enumerate(edge_specs)
    ]
    components = analyze_strong_components(nodes, edges)
    counts = StateGraphTerminalCounts(
        attacker_wins=sum(
            outcome is GraphNodeOutcome.ATTACKER_WIN for outcome in outcomes
        ),
        defender_wins=sum(
            outcome is GraphNodeOutcome.DEFENDER_WIN for outcome in outcomes
        ),
        draws=sum(outcome is GraphNodeOutcome.DRAW for outcome in outcomes),
        non_terminal=sum(
            outcome is GraphNodeOutcome.NON_TERMINAL for outcome in outcomes
        ),
        unknown=sum(outcome is GraphNodeOutcome.UNKNOWN for outcome in outcomes),
    )
    return StateGraphBuildResult(
        root_node_id=GraphNodeId(0),
        nodes=tuple(nodes),
        edges=tuple(edges),
        components=components,
        statistics=StateGraphStatistics(
            unique_state_count=len(nodes),
            edge_count=len(edges),
            max_turn_number=1,
            terminal_counts=counts,
            closed_cycle_count=sum(
                component.kind is StrongComponentKind.CLOSED_CYCLE
                for component in components
            ),
            terminal_reachable_cycle_count=sum(
                component.kind is StrongComponentKind.TERMINAL_REACHABLE_CYCLE
                for component in components
            ),
        ),
    )


def _query() -> BattleEventQuery:
    """返回测试统一使用的攻击方麻痹行动阻断查询。"""
    return BattleEventQuery(
        predicate=BattleEventPredicate(
            battle_event_kinds=(BattleEventKind.ACTION_BLOCKED,),
            side=BattleSide.ATTACKER,
            side_role=EventSideRole.ACTOR,
            effect_identifier="paralysis",
        ),
        distribution_count_limit=2,
        distribution_turn_limit=2,
    )


def _analyze(
    graph: StateGraphBuildResult,
    *,
    revision: str = "revision:test",
    run_id: str = "run:test",
    query: BattleEventQuery | None = None,
):
    """执行一次测试事件分析并返回正式结果。

    Args:
        graph: 待分析的完整小型状态图。
        revision: 绑定结果的计算 revision。
        run_id: 证明独立推演身份的运行 ID。
        query: 可选事件查询；省略时使用统一麻痹停动查询。

    Returns:
        攻击方视角下的精确事件分析结果。
    """
    return BattleEventAnalyzer().analyze(
        BattleEventAnalysisArtifact(
            calculation_revision=revision,
            inference_run_id=run_id,
            graph=graph,
        ),
        query or _query(),
        BattleSide.ATTACKER,
    )


def test_no_event_returns_explicit_undefined_condition_and_preserves_baseline() -> None:
    """验证 ``P(E)=0`` 时不除零，并保持原图胜负概率。"""
    graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(1, 2), _event_summary(None)),
            (0, 2, Fraction(1, 2), _event_summary(None)),
        ),
    )

    result = _analyze(graph)

    assert result.event_probability == Fraction(0)
    assert result.event_win_joint_probability == Fraction(0)
    assert (
        result.win_given_event.status
        is ConditionalProbabilityStatus.UNDEFINED_ZERO_CONDITION
    )
    assert result.win_given_event.value is None
    assert result.win_given_not_event.value == Fraction(1, 2)
    assert result.original_probability_preserved is True


def test_certain_event_returns_undefined_complement_condition() -> None:
    """验证必然事件路径得到 ``P(E)=1``，且 ``P(W|¬E)`` 明确不可定义。"""
    event = _blocked_event()
    graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(3, 4), _event_summary(event)),
            (0, 2, Fraction(1, 4), _event_summary(event)),
        ),
    )

    result = _analyze(graph)

    assert result.event_probability == Fraction(1)
    assert result.event_win_joint_probability == Fraction(3, 4)
    assert result.win_given_event.value == Fraction(3, 4)
    assert (
        result.win_given_not_event.status
        is ConditionalProbabilityStatus.UNDEFINED_ZERO_CONDITION
    )


def test_merged_event_paths_use_their_exact_conditional_weights() -> None:
    """验证同一图边内的替代事件历史按条件权重计算 ``P(E)``。"""
    event = _blocked_event()
    summary = TransitionEventSummary(
        paths=((), (event,)),
        path_probabilities=(Fraction(1, 4), Fraction(3, 4)),
    )
    graph = _build_graph(
        (GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN),
        ((0, 1, Fraction(1), summary),),
    )

    result = _analyze(graph)

    assert result.event_probability == Fraction(3, 4)
    assert result.event_win_joint_probability == Fraction(3, 4)
    assert result.win_given_event.value == Fraction(1)
    assert result.win_given_not_event.value == Fraction(1)


def test_terminal_reachable_event_loop_is_solved_without_path_enumeration() -> None:
    """验证连续麻痹停动形成无限 walk 时仍由有限产品图精确求解。"""
    graph = _build_graph(
        (GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN),
        (
            (0, 0, Fraction(1, 2), _event_summary(_blocked_event())),
            (0, 1, Fraction(1, 2), _event_summary(None)),
        ),
    )

    result = _analyze(graph)
    count_distribution = {
        bucket.key: bucket.probability
        for bucket in result.occurrence_count_distribution
    }

    assert result.event_probability == Fraction(1, 2)
    assert result.event_win_joint_probability == Fraction(1, 2)
    assert result.win_given_event.value == Fraction(1)
    assert result.win_given_not_event.value == Fraction(1)
    assert count_distribution == {
        "count:0": Fraction(1, 2),
        "count:1": Fraction(1, 4),
        "count:2": Fraction(1, 8),
        "count:3+": Fraction(1, 8),
    }
    assert result.computation_cost.product_node_count < 10


def test_turn_range_first_mode_and_occurrence_count_filter_are_exact() -> None:
    """验证任意/首次回合过滤和发生次数边界使用同一产品历史。"""
    event = _blocked_event()
    graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
        ),
        (
            (0, 1, Fraction(1), _event_summary(event)),
            (1, 2, Fraction(1), _event_summary(event)),
        ),
    )
    any_second_turn = BattleEventQuery(
        predicate=_query().predicate,
        occurrence_mode=EventOccurrenceMode.ANY,
        turn_range=EventTurnRange(start_turn=2, end_turn=2),
        min_occurrences=2,
        max_occurrences=2,
        distribution_count_limit=2,
        distribution_turn_limit=2,
    )
    first_second_turn = BattleEventQuery(
        predicate=_query().predicate,
        occurrence_mode=EventOccurrenceMode.FIRST,
        turn_range=EventTurnRange(start_turn=2, end_turn=2),
        min_occurrences=2,
        max_occurrences=2,
        distribution_count_limit=2,
        distribution_turn_limit=2,
    )

    any_result = _analyze(graph, query=any_second_turn, run_id="run:any")
    first_result = _analyze(graph, query=first_second_turn, run_id="run:first")
    first_distribution = {
        bucket.key: bucket.probability
        for bucket in any_result.first_occurrence_distribution
    }

    assert any_result.event_probability == Fraction(1)
    assert first_result.event_probability == Fraction(0)
    assert first_distribution["first:turn:1"] == Fraction(1)
    assert any_result.path_group_coverage.matching_edge_count == 2
    assert any_result.path_group_coverage.matching_event_path_group_count == 2


def test_predicate_uses_structured_fields_instead_of_event_text() -> None:
    """验证带有相似文本的普通随机事件不会冒充结构化麻痹停动。"""
    predicate = _query().predicate
    misleading_event = TransitionEvent(
        event_type=TransitionEventType.CUSTOM,
        event_id="trace:paralysis-action-blocked",
        outcome_id="attacker-cannot-move",
    )

    assert predicate.matches(misleading_event) is False
    assert predicate.matches(_blocked_event()) is True
    assert predicate.matches(
        _blocked_event(source_identifier="flinch")
    ) is False
    assert predicate.matches(
        _blocked_event(side=BattleSide.DEFENDER)
    ) is False
    move_predicate = BattleEventPredicate(
        battle_event_kinds=(BattleEventKind.ACTION_BLOCKED,),
        move_id=85,
    )
    assert move_predicate.matches(
        BattleEvent(
            kind=BattleEventKind.ACTION_BLOCKED,
            turn_number=1,
            actor=BattleSide.ATTACKER,
            move_id=85,
            source_identifier="paralysis",
        )
    ) is True


def test_configuration_aggregation_separates_coverage_from_battle_probability() -> None:
    """验证配置权重覆盖与配置内部事件概率使用不同字段表达。"""
    no_event_graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(1, 2), _event_summary(None)),
            (0, 2, Fraction(1, 2), _event_summary(None)),
        ),
    )
    event_graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(1, 2), _event_summary(_blocked_event())),
            (0, 2, Fraction(1, 2), _event_summary(_blocked_event())),
        ),
    )
    groups = (
        ConfigurationEventAnalysisGroup(
            configuration_id="config:no-event",
            configuration_weight=Fraction(1, 4),
            analysis=_analyze(no_event_graph, run_id="run:no-event"),
        ),
        ConfigurationEventAnalysisGroup(
            configuration_id="config:event",
            configuration_weight=Fraction(1, 2),
            analysis=_analyze(event_graph, run_id="run:event"),
        ),
    )

    summary = aggregate_configuration_event_analyses(
        groups,
        total_configuration_count=3,
        unresolved_configuration_weight=Fraction(1, 4),
    )

    assert summary.coverage.analyzed_configuration_count == 2
    assert summary.coverage.event_possible_configuration_count == 1
    assert summary.coverage.analyzed_configuration_weight == Fraction(3, 4)
    assert summary.coverage.event_possible_configuration_weight == Fraction(1, 2)
    assert summary.coverage.unresolved_configuration_weight == Fraction(1, 4)
    assert summary.weighted_metrics.event_probability == Fraction(1, 2)
    assert summary.weighted_metrics.event_win_joint_probability == Fraction(1, 4)


@dataclass(slots=True)
class _CounterfactualRunner:
    """按 revision 返回预置图，并记录两次独立推演请求。"""

    graphs: dict[str, StateGraphBuildResult]
    requests: list[CounterfactualInferenceRequest] = field(default_factory=list)

    def run(
        self,
        request: CounterfactualInferenceRequest,
    ) -> BattleEventAnalysisArtifact:
        """记录请求并返回使用唯一运行 ID 的图 artifact。

        Args:
            request: 当前 revision 及其显式规则覆盖。

        Returns:
            与请求 revision 对应、运行 ID 唯一的完整图。
        """
        self.requests.append(request)
        return BattleEventAnalysisArtifact(
            calculation_revision=request.calculation_revision,
            inference_run_id=f"run:{request.calculation_revision}",
            graph=self.graphs[request.calculation_revision],
        )


def test_counterfactual_analysis_runs_two_independent_revisions() -> None:
    """验证反事实差值来自两次独立推演，而非同一观察图内推断。"""
    baseline_graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(1, 2), _event_summary(None)),
            (0, 2, Fraction(1, 2), _event_summary(None)),
        ),
    )
    counterfactual_graph = _build_graph(
        (
            GraphNodeOutcome.NON_TERMINAL,
            GraphNodeOutcome.ATTACKER_WIN,
            GraphNodeOutcome.DEFENDER_WIN,
        ),
        (
            (0, 1, Fraction(3, 4), _event_summary(_blocked_event())),
            (0, 2, Fraction(1, 4), _event_summary(_blocked_event())),
        ),
    )
    runner = _CounterfactualRunner(
        graphs={
            "revision:baseline": baseline_graph,
            "revision:no-paralysis-stop": counterfactual_graph,
        }
    )
    request = CounterfactualBattleEventRequest(
        baseline_revision="revision:baseline",
        counterfactual_revision="revision:no-paralysis-stop",
        rule_overrides=(
            BattleRuleOverride(
                identifier="status.paralysis.action_block_probability",
                value="0",
            ),
        ),
        query=_query(),
    )

    result = CounterfactualBattleEventAnalyzer(runner).execute(request)

    assert len(runner.requests) == 2
    assert runner.requests[0].rule_overrides == ()
    assert runner.requests[1].rule_overrides == request.rule_overrides
    assert result.independent_revisions_verified is True
    assert result.win_probability_delta == Fraction(1, 4)
    assert result.event_probability_delta == Fraction(1)
    assert result.event_win_joint_probability_delta == Fraction(3, 4)
    assert result.computation_cost.inference_run_count == 2
    assert result.computation_cost.graph_build_count == 2
