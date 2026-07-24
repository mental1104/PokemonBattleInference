"""提供配置对流式执行测试使用的合成配置、fake executor 和 sinks。"""

from __future__ import annotations

import gc
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import cast
from weakref import ReferenceType, ref

from pokeop.application.configuration_space import (
    ConfiguredMove,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.graph_solver import (
    BattleGraphSolveResult,
    BattleGraphSolveStatus,
    ExpectedTurns,
    ExpectedTurnsStatus,
)
from pokeop.application.solver.models import (
    GraphTruncationReason,
    StateGraphBuildResult,
    StateGraphLimits,
)
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.application.use_cases.stream_configuration_pairs import (
    CancellationToken,
    ConfigurationPairAggregate,
    ConfigurationPairExecutionResult,
    ConfigurationPairGraphArtifact,
    ConfigurationPairProgress,
    ConfigurationPairResultSink,
    ConfigurationPairWorkItem,
    ProgressSink,
    StreamConfigurationPairsCommand,
    StreamConfigurationPairsUseCase,
    equally_weighted_configurations,
)
from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.specs import MoveSpec
from pokeop.domain.battle.stats import StatProfile, StatValues
from pokeop.domain.models.types import Type


_RULES = BattleInferenceRules(version_group_id=31, max_turns=20)


@dataclass(frozen=True, slots=True)
class _GraphStatistics:
    """提供流式摘要所需的最小图规模字段。"""

    unique_state_count: int
    edge_count: int
    max_turn_number: int


class _GraphArtifact:
    """模拟可被弱引用观察生命周期的完整状态图对象。"""

    def __init__(
        self,
        *,
        node_count: int,
        edge_count: int,
        scc_count: int,
        max_turn_number: int,
        truncation_reasons: tuple[GraphTruncationReason, ...] = (),
    ) -> None:
        """保存轻量测试字段，同时保留类似真实图的大对象生命周期边界。

        Args:
            node_count: 唯一节点数量。
            edge_count: 有向边数量。
            scc_count: 强连通分量数量。
            max_turn_number: 图内最大回合号。
            truncation_reasons: 非空时表示图被运行保护截断。
        """
        self.statistics = _GraphStatistics(
            unique_state_count=node_count,
            edge_count=edge_count,
            max_turn_number=max_turn_number,
        )
        self.components = tuple(object() for _ in range(scc_count))
        self.truncation_reasons = truncation_reasons

    @property
    def is_complete(self) -> bool:
        """返回测试图是否未触发截断。"""
        return not self.truncation_reasons


class _FakeExecutionKind(str, Enum):
    """声明 fake executor 对一个配置对采用的执行结果。"""

    SUCCEEDED = "succeeded"
    TRUNCATED = "truncated"
    RAISE_ERROR = "raise-error"
    SOLVER_FAILED = "solver-failed"
    MALFORMED_SOLVE_RESULT = "malformed-solve-result"


@dataclass(frozen=True, slots=True)
class _MalformedSolveResult:
    """模拟标记为 solved 但缺失精确概率的非法 solver 返回值。"""

    status: BattleGraphSolveStatus = BattleGraphSolveStatus.SOLVED
    win_probability: Fraction | None = None
    loss_probability: Fraction | None = None
    draw_probability: Fraction | None = None
    expected_turns: ExpectedTurns = ExpectedTurns(
        ExpectedTurnsStatus.UNAVAILABLE
    )
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FakeExecution:
    """保存 fake 图规模、概率、期望回合和失败类型。"""

    kind: _FakeExecutionKind = _FakeExecutionKind.SUCCEEDED
    win_probability: Fraction = Fraction(1, 2)
    loss_probability: Fraction = Fraction(1, 4)
    draw_probability: Fraction = Fraction(1, 4)
    expected_turns: Fraction = Fraction(3)
    node_count: int = 3
    edge_count: int = 2
    scc_count: int = 3
    max_turn_number: int = 2


@dataclass(slots=True)
class _FakeGraphExecutor:
    """按配置 ID 返回可控图结果，并记录同时存活的完整图数量。"""

    executions: dict[tuple[str, str], _FakeExecution] = field(default_factory=dict)
    graph_references: list[ReferenceType[_GraphArtifact]] = field(default_factory=list)
    max_live_graph_count: int = 0

    def execute(
        self,
        work_item: ConfigurationPairWorkItem,
        *,
        rules: BattleInferenceRules,
        attacker_policy: BattleActionPolicyKind,
        defender_policy: BattleActionPolicyKind,
        observer: BattleSide,
        graph_limits: StateGraphLimits,
    ) -> ConfigurationPairGraphArtifact:
        """为当前配置对创建一个短生命周期 fake 图和精确 solver 结果。

        Args:
            work_item: 当前配置对及其稳定双方 ID。
            rules: 批次共享规则；fake 只验证调用方确实传入相同对象。
            attacker_policy: 本测试不解释的攻击方策略枚举。
            defender_policy: 本测试不解释的防守方策略枚举。
            observer: solver 结果使用的观察方。
            graph_limits: 本测试不解释的单 pair 图限制。

        Returns:
            可由流式用例提取摘要的短生命周期 artifact。

        Raises:
            RuntimeError: 当前配置对被声明为单项异常时抛出。
        """
        del attacker_policy, defender_policy, graph_limits
        assert rules is _RULES
        key = (
            work_item.attacker_configuration_id,
            work_item.defender_configuration_id,
        )
        execution = self.executions.get(key, _FakeExecution())
        if execution.kind is _FakeExecutionKind.RAISE_ERROR:
            raise RuntimeError(f"fake failure for {work_item.pair_id}")

        # 进入下一配置时，前一配置完整图必须已经离开用例调用栈。
        gc.collect()
        live_before_create = sum(reference() is not None for reference in self.graph_references)
        graph = _GraphArtifact(
            node_count=execution.node_count,
            edge_count=execution.edge_count,
            scc_count=execution.scc_count,
            max_turn_number=execution.max_turn_number,
            truncation_reasons=(
                (GraphTruncationReason.MAX_NODES,)
                if execution.kind is _FakeExecutionKind.TRUNCATED
                else ()
            ),
        )
        self.graph_references.append(ref(graph))
        self.max_live_graph_count = max(self.max_live_graph_count, live_before_create + 1)

        if execution.kind is _FakeExecutionKind.TRUNCATED:
            solved = BattleGraphSolveResult.unavailable(
                status=BattleGraphSolveStatus.INCOMPLETE_GRAPH,
                observer=observer,
                diagnostics=("fake graph was truncated",),
            )
        elif execution.kind is _FakeExecutionKind.SOLVER_FAILED:
            solved = BattleGraphSolveResult.unavailable(
                status=BattleGraphSolveStatus.RESOURCE_LIMIT_EXCEEDED,
                observer=observer,
                diagnostics=("fake solver resource limit",),
            )
        elif execution.kind is _FakeExecutionKind.MALFORMED_SOLVE_RESULT:
            solved = cast(BattleGraphSolveResult, _MalformedSolveResult())
        else:
            solved = BattleGraphSolveResult(
                status=BattleGraphSolveStatus.SOLVED,
                observer=observer,
                win_probability=execution.win_probability,
                loss_probability=execution.loss_probability,
                draw_probability=execution.draw_probability,
                closed_cycle_probability=Fraction(0),
                expected_turns=ExpectedTurns(
                    ExpectedTurnsStatus.FINITE,
                    execution.expected_turns,
                ),
            )
        return ConfigurationPairGraphArtifact(
            graph=cast(StateGraphBuildResult, graph),
            solve_result=solved,
        )


@dataclass(slots=True)
class _CollectingResultSink(ConfigurationPairResultSink):
    """在测试内保存逐项轻量结果和最终聚合。"""

    results: list[ConfigurationPairExecutionResult] = field(default_factory=list)
    final: ConfigurationPairAggregate | None = None

    def write_result(self, result: ConfigurationPairExecutionResult) -> None:
        """追加一个不含完整图的配置对结果。"""
        self.results.append(result)

    def write_final(self, aggregate: ConfigurationPairAggregate) -> None:
        """保存本批次唯一最终聚合。"""
        self.final = aggregate


@dataclass(slots=True)
class _CollectingProgressSink(ProgressSink):
    """保存每完成一个配置对后的双轴进度。"""

    progress: list[ConfigurationPairProgress] = field(default_factory=list)

    def write_progress(self, progress: ConfigurationPairProgress) -> None:
        """追加最新配置数量和累计图资源快照。"""
        self.progress.append(progress)


@dataclass(slots=True)
class _CancelAfterChecks(CancellationToken):
    """在指定次数的领取检查通过后请求取消。"""

    allowed_checks: int
    check_count: int = 0

    def is_cancelled(self) -> bool:
        """前 allowed_checks 次返回 False，之后返回 True。"""
        self.check_count += 1
        return self.check_count > self.allowed_checks


def _pokemon_configuration(
    pokemon_id: int,
    move_ids: tuple[int, ...],
) -> PokemonBattleConfiguration:
    """创建仅用于 application 流式合同测试的合成单边配置。

    Args:
        pokemon_id: 配置中的稳定 Pokémon ID。
        move_ids: 一到四个互不重复的招式 ID；输入顺序故意可与规范顺序不同。

    Returns:
        规则轴与 ``_RULES`` 一致的不可变配置。
    """
    base_stats = StatValues(80, 90, 80, 70, 80, 90)
    return PokemonBattleConfiguration(
        ruleset_id=_RULES.ruleset_id,
        version_group_id=_RULES.version_group_id,
        pokemon_id=pokemon_id,
        name=f"pokemon-{pokemon_id}",
        level=_RULES.level,
        types=(Type.NORMAL,),
        stats=StatValues(155, 120, 110, 100, 110, 120),
        stat_profile=StatProfile(base_stats=base_stats),
        moves=tuple(
            ConfiguredMove(
                move_spec=MoveSpec(
                    move_id=move_id,
                    move=BattleMove(
                        f"move-{move_id}",
                        Type.NORMAL,
                        MoveCategory.PHYSICAL,
                        50,
                    ),
                    max_pp=10,
                ),
                effect_identifier=None,
            )
            for move_id in move_ids
        ),
        ability_identifier="none",
        item_identifier="none",
        can_evolve=False,
    )


def _command(
    *,
    attacker_ids: tuple[str, ...] = ("attacker-a", "attacker-b"),
    defender_ids: tuple[str, ...] = ("defender-a", "defender-b"),
    max_configuration_pairs: int | None = None,
    cumulative_node_limit: int | None = None,
    cumulative_edge_limit: int | None = None,
    max_failures: int | None = None,
    top_k: int = 10,
) -> StreamConfigurationPairsCommand:
    """创建双方等权、顺序可控的流式执行命令。

    Args:
        attacker_ids: 攻击方稳定配置 ID。
        defender_ids: 防守方稳定配置 ID。
        max_configuration_pairs: 可选配置对数量上限。
        cumulative_node_limit: 可选累计节点上限。
        cumulative_edge_limit: 可选累计边上限。
        max_failures: 可选最大失败数。
        top_k: 每类排行保留数量。

    Returns:
        使用合成配置但真实精确权重合同的命令。
    """
    attacker_configuration = _pokemon_configuration(149, (280, 245))
    defender_configuration = _pokemon_configuration(461, (8, 252))
    return StreamConfigurationPairsCommand(
        rules=_RULES,
        attacker_configurations=equally_weighted_configurations(
            tuple((identifier, attacker_configuration) for identifier in attacker_ids)
        ),
        defender_configurations=equally_weighted_configurations(
            tuple((identifier, defender_configuration) for identifier in defender_ids)
        ),
        max_configuration_pairs=max_configuration_pairs,
        cumulative_node_limit=cumulative_node_limit,
        cumulative_edge_limit=cumulative_edge_limit,
        max_failures=max_failures,
        top_k=top_k,
    )


def _execute(
    command: StreamConfigurationPairsCommand,
    executions: dict[tuple[str, str], _FakeExecution],
    *,
    cancellation_token: CancellationToken | None = None,
) -> tuple[
    ConfigurationPairAggregate,
    _FakeGraphExecutor,
    _CollectingResultSink,
    _CollectingProgressSink,
]:
    """使用 collecting sinks 执行命令并返回全部可验收对象。

    Args:
        command: 待执行流式命令。
        executions: 按双方配置 ID 指定的 fake 行为。
        cancellation_token: 可选同步取消端口。

    Returns:
        最终聚合、fake executor、结果 sink 和进度 sink。
    """
    executor = _FakeGraphExecutor(executions)
    result_sink = _CollectingResultSink()
    progress_sink = _CollectingProgressSink()
    use_case = StreamConfigurationPairsUseCase(
        graph_executor=executor,
        result_sink=result_sink,
        progress_sink=progress_sink,
        **(
            {"cancellation_token": cancellation_token}
            if cancellation_token is not None
            else {}
        ),
    )
    aggregate = use_case.execute(command)
    return aggregate, executor, result_sink, progress_sink


__all__ = [
    "_CancelAfterChecks",
    "_FakeExecution",
    "_FakeExecutionKind",
    "_FakeGraphExecutor",
    "_command",
    "_execute",
]
