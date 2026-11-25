"""原配置事件聚合与独立revision反事实端口的真实Core差分，重算集成另有原生验收。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Literal

import pytest

from pokeop.application.event_analysis import BattleEventAnalysisArtifact, BattleEventAnalyzer, BattleEventPredicate, BattleEventQuery, BattleRuleOverride, ConfigurationEventAnalysisGroup, CounterfactualBattleEventAnalyzer, CounterfactualBattleEventRequest, CounterfactualInferenceRequest, aggregate_configuration_event_analyses
from pokeop.application.solver.models import GraphNodeOutcome
from pokeop.domain.battle.battle_events import BattleEvent, BattleEventKind
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.transitions import TransitionEventSummary
from tests.migration.test_core_damage import ExactFraction
from tests.migration.test_core_event_analysis import EventInput, EventReply, _Case, _Contract, _EventOracle
from tests.migration.test_core_state import _StateOracle


class GroupInput(_Contract):
    """每组持有完整未分析图与原完整配置分母权重。"""

    configuration_id: str
    configuration_weight: ExactFraction
    analysis: EventInput


class BatchInput(_Contract):
    """正式配置事件操作，不从输入接收任何已求解事件概率。"""

    kind: Literal["configuration_event_analysis"] = "configuration_event_analysis"
    groups: tuple[GroupInput, ...]
    total_configuration_count: str
    unresolved_configuration_weight: ExactFraction


class GroupReply(_Contract):
    """每组原始配置身份/权重和真正事件产品图的完整结果。"""

    configuration_id: str
    configuration_weight: ExactFraction
    analysis: EventReply


class ConfigurationCoverage(_Contract):
    """完整配置分母上的实际数量和权重覆盖，不因未分析配置重新归一化。"""

    total_configuration_count: str
    analyzed_configuration_count: int
    event_possible_configuration_count: int
    analyzed_configuration_weight: ExactFraction
    event_possible_configuration_weight: ExactFraction
    unresolved_configuration_weight: ExactFraction


class WeightedMetrics(_Contract):
    """完整分母上的混合战斗事件/联合概率。"""

    event_probability: ExactFraction
    event_win_joint_probability: ExactFraction


class BatchReply(_Contract):
    """原aggregate_configuration_event_analyses全部输出，包含逐组完整证据。"""

    kind: Literal["configuration_event_analysis"]
    groups: tuple[GroupReply, ...]
    coverage: ConfigurationCoverage
    weighted_metrics: WeightedMetrics


class Override(_Contract):
    """原端口识别的显式规则键和值，不复制或发明规则键到机制的映射。"""

    identifier: str
    value: str


class CounterfactualFixture(_Contract):
    """独立端口差分夹具，不是公开ABI；真正两次重算在原生InferFixedBattle集成验证。"""

    kind: Literal["counterfactual_fixture"] = "counterfactual_fixture"
    baseline: EventInput
    counterfactual: EventInput
    rule_overrides: tuple[Override, ...]


class CounterfactualCost(_Contract):
    """两次独立端口调用与各自事件分析的原完整成本。"""

    inference_run_count: int
    graph_build_count: int
    exact_solver_run_count: int


class CounterfactualReply(_Contract):
    """完整双结果、三个精确差值、独立身份验证和真实端口调用次数。"""

    baseline: EventReply
    counterfactual: EventReply
    win_probability_delta: ExactFraction
    event_probability_delta: ExactFraction
    event_win_joint_probability_delta: ExactFraction
    independent_revisions_verified: bool
    actual_runner_calls: int
    computation_cost: CounterfactualCost


@dataclass(frozen=True)
class _IndependentRunner:
    """原CounterfactualInferenceRunner的独立图端口夹具，保留全部调用以核对两次请求。"""

    baseline: BattleEventAnalysisArtifact
    counterfactual: BattleEventAnalysisArtifact
    calls: list[CounterfactualInferenceRequest] = field(default_factory=list)

    def run(self, request: CounterfactualInferenceRequest) -> BattleEventAnalysisArtifact:
        """记录完整revision/覆盖请求并返回对应独立artifact，分析算法仍调用原实现。"""
        self.calls.append(request)
        return self.baseline if request.calculation_revision == self.baseline.calculation_revision else self.counterfactual


class _BatchOracle:
    """只生成两端共享事实/组和完整结果投影，所有混合/条件概率都调用原业务。"""

    @staticmethod
    def case(weight: Fraction, event_probability: Fraction, observer: BattleSide = BattleSide.ATTACKER) -> _Case:
        """用实际元数据构造完整图，参数是原边概率，不是产品图或分析结果。"""
        event = BattleEvent(kind=BattleEventKind.ACTION_BLOCKED, turn_number=1, actor=BattleSide.ATTACKER, source_identifier="paralysis")
        graph = _EventOracle.graph((GraphNodeOutcome.NON_TERMINAL, GraphNodeOutcome.ATTACKER_WIN, GraphNodeOutcome.DEFENDER_WIN),
            ((0, 1, weight, TransitionEventSummary(((event,), ()), (event_probability, 1 - event_probability))),
             (0, 2, 1 - weight, TransitionEventSummary.single(event))))
        return _Case(graph, BattleEventQuery(predicate=BattleEventPredicate(battle_event_kinds=(BattleEventKind.ACTION_BLOCKED,),
            side=BattleSide.ATTACKER, effect_identifier="paralysis"), distribution_count_limit=2, distribution_turn_limit=2), observer)

    @staticmethod
    def expected(request: BatchInput, cases: tuple[_Case, ...]) -> BatchReply:
        """调用原完整逐图analyze和公开aggregate，逐组保留原身份/权重/全部分析。"""
        groups = tuple(ConfigurationEventAnalysisGroup(group.configuration_id, group.configuration_weight.value(),
            BattleEventAnalyzer().analyze(BattleEventAnalysisArtifact(group.analysis.calculation_revision, group.analysis.inference_run_id, case.graph), case.query, case.observer))
            for group, case in zip(request.groups, cases, strict=True))
        result = aggregate_configuration_event_analyses(groups, total_configuration_count=int(request.total_configuration_count),
            unresolved_configuration_weight=request.unresolved_configuration_weight.value())
        coverage = result.coverage
        return BatchReply(kind="configuration_event_analysis", groups=tuple(GroupReply(configuration_id=group.configuration_id,
            configuration_weight=_StateOracle.fraction(group.configuration_weight), analysis=_EventOracle.response(group.analysis)) for group in result.groups),
            coverage=ConfigurationCoverage(total_configuration_count=str(coverage.total_configuration_count), analyzed_configuration_count=coverage.analyzed_configuration_count,
                event_possible_configuration_count=coverage.event_possible_configuration_count, analyzed_configuration_weight=_StateOracle.fraction(coverage.analyzed_configuration_weight),
                event_possible_configuration_weight=_StateOracle.fraction(coverage.event_possible_configuration_weight), unresolved_configuration_weight=_StateOracle.fraction(coverage.unresolved_configuration_weight)),
            weighted_metrics=WeightedMetrics(event_probability=_StateOracle.fraction(result.weighted_metrics.event_probability),
                event_win_joint_probability=_StateOracle.fraction(result.weighted_metrics.event_win_joint_probability)))


@pytest.fixture
def event_batch_runner() -> Path:
    """获取真实已编译Core入口；缺少时明确skip而不以内存Python替代。"""
    value = os.getenv("PBI_EVENT_ANALYSIS_RUNNER")
    if value is None:
        pytest.skip("PBI_EVENT_ANALYSIS_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreEventAnalysisBatch:
    """原独立revision与完整配置分母的事件汇总边界。"""

    def test_original_configuration_event_aggregate(self, event_batch_runner: Path) -> None:
        """32组完整/部分/空分析空间，保留原失败权重、逐组结果、配置可能性及全部精确混合指标。"""
        rng = random.Random(60302)
        requests: list[BatchInput] = []
        originals: list[tuple[_Case, ...]] = []
        for index in range(32):
            count = index % 5
            cases = tuple(_BatchOracle.case(Fraction(rng.randint(1, 9), 10), Fraction(rng.randint(1, 9), 10),
                BattleSide.ATTACKER if index % 2 == 0 else BattleSide.DEFENDER) for _ in range(count))
            group_weight = Fraction(1, count + 1)
            groups = tuple(GroupInput(configuration_id=f"config-{index}-{position}", configuration_weight=_StateOracle.fraction(group_weight),
                analysis=_EventOracle.request(case).model_copy(update={"inference_run_id": f"run-{index}-{position}"})) for position, case in enumerate(cases))
            requests.append(BatchInput(groups=groups, total_configuration_count=str((10**40 if index % 3 == 0 else count + 1)),
                unresolved_configuration_weight=_StateOracle.fraction(1 - count * group_weight)))
            originals.append(cases)
        result = subprocess.run([str(event_batch_runner)], input="".join(value.model_dump_json() + "\n" for value in requests), text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(requests)
        for line, request, cases in zip(lines, requests, originals, strict=True):
            assert BatchReply.model_validate_json(line) == _BatchOracle.expected(request, cases)

    def test_original_counterfactual_port_and_complete_delta(self, event_batch_runner: Path) -> None:
        """16组原独立artifact端口，比较完整双结果/差值/成本，并核对真实两次revision和覆盖请求。"""
        fixtures: list[CounterfactualFixture] = []
        references: list[CounterfactualReply] = []
        for index in range(16):
            baseline = _BatchOracle.case(Fraction(index + 1, 20), Fraction(1, 3))
            counterfactual = _BatchOracle.case(Fraction(19 - index, 20), Fraction(2, 3))
            first = _EventOracle.request(baseline).model_copy(update={"calculation_revision": "baseline", "inference_run_id": "baseline-run"})
            second = _EventOracle.request(counterfactual).model_copy(update={"calculation_revision": "override", "inference_run_id": "override-run"})
            overrides = (Override(identifier="fixture:independent-revision", value=str(index)),)
            fixture = CounterfactualFixture(baseline=first, counterfactual=second, rule_overrides=overrides)
            runner = _IndependentRunner(BattleEventAnalysisArtifact("baseline", "baseline-run", baseline.graph), BattleEventAnalysisArtifact("override", "override-run", counterfactual.graph))
            request = CounterfactualBattleEventRequest("baseline", "override", (BattleRuleOverride(overrides[0].identifier, overrides[0].value),), baseline.query)
            result = CounterfactualBattleEventAnalyzer(runner).execute(request)
            assert runner.calls == [CounterfactualInferenceRequest("baseline", ()), CounterfactualInferenceRequest("override", request.rule_overrides)]
            references.append(CounterfactualReply(baseline=_EventOracle.response(result.baseline), counterfactual=_EventOracle.response(result.counterfactual),
                win_probability_delta=_StateOracle.fraction(result.win_probability_delta), event_probability_delta=_StateOracle.fraction(result.event_probability_delta),
                event_win_joint_probability_delta=_StateOracle.fraction(result.event_win_joint_probability_delta), independent_revisions_verified=result.independent_revisions_verified,
                actual_runner_calls=len(runner.calls), computation_cost=CounterfactualCost(inference_run_count=result.computation_cost.inference_run_count,
                    graph_build_count=result.computation_cost.graph_build_count, exact_solver_run_count=result.computation_cost.exact_solver_run_count)))
            fixtures.append(fixture)
        result = subprocess.run([str(event_batch_runner)], input="".join(value.model_dump_json() + "\n" for value in fixtures), text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(fixtures)
        for line, expected in zip(lines, references, strict=True):
            assert CounterfactualReply.model_validate_json(line) == expected
