"""流式执行配置对，持续输出轻量结果并聚合精确概率。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from hashlib import sha256

from pokeop.application.configuration_space import (
    BattleConfiguration,
    PokemonBattleConfiguration,
)
from pokeop.application.solver.graph_solver import (
    BattleGraphSolveStatus,
    ExpectedTurnsStatus,
)
from pokeop.application.use_cases.stream_configuration_pairs.aggregation import (
    AggregateState,
)
from pokeop.application.use_cases.stream_configuration_pairs.executor import (
    ExactConfigurationPairGraphExecutor,
)
from pokeop.application.use_cases.stream_configuration_pairs.models import (
    CancellationToken,
    ConfigurationPairAggregate,
    ConfigurationPairExecutionResult,
    ConfigurationPairExecutionStatus,
    ConfigurationPairGraphArtifact,
    ConfigurationPairGraphExecutor,
    ConfigurationPairResultSink,
    ConfigurationPairStopReason,
    ConfigurationPairStreamError,
    ConfigurationPairWorkItem,
    DiscardConfigurationPairResultSink,
    DiscardProgressSink,
    NeverCancelledToken,
    ProgressSink,
    StreamConfigurationPairsCommand,
)


@dataclass(slots=True)
class StreamConfigurationPairsUseCase:
    """逐项执行配置对、释放完整图并持续聚合精确概率。

    Args:
        graph_executor: 单配置图构建与求解端口。
        result_sink: 单配置与最终聚合输出端口。
        progress_sink: 配置数量和累计资源进度输出端口。
        cancellation_token: 每次领取新配置前检查的同步取消端口。
    """

    graph_executor: ConfigurationPairGraphExecutor = field(
        default_factory=ExactConfigurationPairGraphExecutor
    )
    result_sink: ConfigurationPairResultSink = field(
        default_factory=DiscardConfigurationPairResultSink
    )
    progress_sink: ProgressSink = field(default_factory=DiscardProgressSink)
    cancellation_token: CancellationToken = field(default_factory=NeverCancelledToken)

    def execute(
        self,
        command: StreamConfigurationPairsCommand,
    ) -> ConfigurationPairAggregate:
        """按稳定顺序流式执行，单配置异常不会终止后续配置。

        Args:
            command: 规范化配置集合、策略、单 pair 限制和累计预算。

        Returns:
            以完整配置空间为分母的部分或完整精确聚合结果。
        """
        state = AggregateState(top_k=command.top_k)
        stop_reason = ConfigurationPairStopReason.COMPLETED

        for work_item in iter_configuration_pairs(command):
            preflight_stop = _stop_before_next(
                command,
                state,
                self.cancellation_token,
            )
            if preflight_stop is not None:
                stop_reason = preflight_stop
                break

            result = self._execute_one(command, work_item)
            # sink 只看到轻量摘要；完整图已在 _execute_one 返回前离开调用栈。
            self.result_sink.write_result(result)
            state.add(result)
            self.progress_sink.write_progress(
                state.progress(total_pair_count=command.total_pair_count)
            )

        aggregate = state.finish(
            stop_reason=stop_reason,
            total_pair_count=command.total_pair_count,
        )
        self.result_sink.write_final(aggregate)
        return aggregate

    def _execute_one(
        self,
        command: StreamConfigurationPairsCommand,
        work_item: ConfigurationPairWorkItem,
    ) -> ConfigurationPairExecutionResult:
        """执行一个配置对，并确保完整图不会进入返回结果。

        Args:
            command: 当前批次共享规则、策略和单 pair 图限制。
            work_item: 当前配置对及其独立配置权重。

        Returns:
            不持有 graph、节点、边或原始路径的轻量结果。
        """
        try:
            artifact = self.graph_executor.execute(
                work_item,
                rules=command.rules,
                attacker_policy=command.attacker_policy,
                defender_policy=command.defender_policy,
                observer=command.observer,
                graph_limits=command.graph_limits,
            )
        except Exception as exc:  # noqa: BLE001 - 单配置失败必须类型化并继续。
            return _failed_result(work_item, exc)

        try:
            return _summarize_artifact(work_item, artifact)
        finally:
            # 显式切断局部引用，使 CPython 可立即回收大图。
            del artifact


def iter_configuration_pairs(
    command: StreamConfigurationPairsCommand,
) -> Iterator[ConfigurationPairWorkItem]:
    """惰性生成双方配置的稳定笛卡尔积。

    Args:
        command: 已按配置 ID 排序且两侧权重分别严格和为 1 的命令。

    Yields:
        不预构造完整 pair 列表的配置对工作项。
    """
    for attacker in command.attacker_configurations:
        for defender in command.defender_configurations:
            yield ConfigurationPairWorkItem(
                pair_id=_stable_pair_id(
                    attacker.configuration_id,
                    defender.configuration_id,
                ),
                attacker_configuration_id=attacker.configuration_id,
                defender_configuration_id=defender.configuration_id,
                configuration_weight=attacker.weight * defender.weight,
                configuration=BattleConfiguration(
                    attacker=attacker.configuration,
                    defender=defender.configuration,
                ),
            )


def _stable_pair_id(attacker_id: str, defender_id: str) -> str:
    """根据带阵营边界的双方配置 ID 生成稳定幂等 ID。

    Args:
        attacker_id: 攻击方稳定配置 ID。
        defender_id: 防守方稳定配置 ID。

    Returns:
        不受输入池顺序影响的 SHA-256 配置对标识。
    """
    payload = (
        f"attacker:{len(attacker_id)}:{attacker_id}\0"
        f"defender:{len(defender_id)}:{defender_id}"
    ).encode("utf-8")
    return f"pair-{sha256(payload).hexdigest()}"


def _stop_before_next(
    command: StreamConfigurationPairsCommand,
    state: AggregateState,
    cancellation_token: CancellationToken,
) -> ConfigurationPairStopReason | None:
    """在构建下一个大图前检查取消、数量和累计资源预算。

    Args:
        command: 包含全部运行保护的批次命令。
        state: 已完成配置的累计状态。
        cancellation_token: 外部同步取消端口。

    Returns:
        需要停止时的稳定原因；可继续领取时返回 None。
    """
    if cancellation_token.is_cancelled():
        return ConfigurationPairStopReason.CANCELLED
    if (
        command.max_configuration_pairs is not None
        and state.processed_pair_count >= command.max_configuration_pairs
    ):
        return ConfigurationPairStopReason.CONFIGURATION_PAIR_LIMIT
    if (
        command.cumulative_node_limit is not None
        and state.cumulative_node_count >= command.cumulative_node_limit
    ):
        return ConfigurationPairStopReason.CUMULATIVE_NODE_LIMIT
    if (
        command.cumulative_edge_limit is not None
        and state.cumulative_edge_count >= command.cumulative_edge_limit
    ):
        return ConfigurationPairStopReason.CUMULATIVE_EDGE_LIMIT
    if command.max_failures is not None and state.failed_count >= command.max_failures:
        return ConfigurationPairStopReason.MAX_FAILURES
    return None


def _summarize_artifact(
    work_item: ConfigurationPairWorkItem,
    artifact: ConfigurationPairGraphArtifact,
) -> ConfigurationPairExecutionResult:
    """从短生命周期图 artifact 提取 sink 可持久化的轻量结果。

    Args:
        work_item: 当前配置 ID、技能组和独立配置权重。
        artifact: 完整图和 solver 返回值。

    Returns:
        成功、截断或失败的类型化摘要。
    """
    graph = artifact.graph
    solved = artifact.solve_result
    shared = {
        "pair_id": work_item.pair_id,
        "attacker_configuration_id": work_item.attacker_configuration_id,
        "defender_configuration_id": work_item.defender_configuration_id,
        "attacker_move_ids": _move_ids(work_item.configuration.attacker),
        "defender_move_ids": _move_ids(work_item.configuration.defender),
        "configuration_weight": work_item.configuration_weight,
        "node_count": graph.statistics.unique_state_count,
        "edge_count": graph.statistics.edge_count,
        "scc_count": len(graph.components),
        "max_turn_number": graph.statistics.max_turn_number,
    }
    if not graph.is_complete or solved.status is BattleGraphSolveStatus.INCOMPLETE_GRAPH:
        return ConfigurationPairExecutionResult(
            **shared,
            status=ConfigurationPairExecutionStatus.TRUNCATED,
            win_probability=None,
            loss_probability=None,
            draw_probability=None,
            expected_turns=None,
            expected_turns_status=ExpectedTurnsStatus.UNAVAILABLE,
            diagnostics=tuple(reason.value for reason in graph.truncation_reasons)
            + solved.diagnostics,
        )
    if solved.status is not BattleGraphSolveStatus.SOLVED:
        return ConfigurationPairExecutionResult(
            **shared,
            status=ConfigurationPairExecutionStatus.FAILED,
            win_probability=None,
            loss_probability=None,
            draw_probability=None,
            expected_turns=None,
            expected_turns_status=ExpectedTurnsStatus.UNAVAILABLE,
            diagnostics=solved.diagnostics or (solved.status.value,),
        )
    if (
        solved.win_probability is None
        or solved.loss_probability is None
        or solved.draw_probability is None
    ):
        raise ConfigurationPairStreamError(
            "solved configuration pair is missing exact probabilities"
        )
    return ConfigurationPairExecutionResult(
        **shared,
        status=ConfigurationPairExecutionStatus.SUCCEEDED,
        win_probability=solved.win_probability,
        loss_probability=solved.loss_probability,
        draw_probability=solved.draw_probability,
        expected_turns=(
            solved.expected_turns.value
            if solved.expected_turns.status is ExpectedTurnsStatus.FINITE
            else None
        ),
        expected_turns_status=solved.expected_turns.status,
        diagnostics=solved.diagnostics,
    )


def _failed_result(
    work_item: ConfigurationPairWorkItem,
    exc: Exception,
) -> ConfigurationPairExecutionResult:
    """把单配置异常转换为不终止批次的类型化失败结果。

    Args:
        work_item: 异常对应的稳定配置对。
        exc: 单配置图构建或求解异常。

    Returns:
        概率为空、图规模为零且带异常类型诊断的失败结果。
    """
    message = str(exc).strip()
    diagnostic = type(exc).__name__ + (f": {message}" if message else "")
    return ConfigurationPairExecutionResult(
        pair_id=work_item.pair_id,
        attacker_configuration_id=work_item.attacker_configuration_id,
        defender_configuration_id=work_item.defender_configuration_id,
        attacker_move_ids=_move_ids(work_item.configuration.attacker),
        defender_move_ids=_move_ids(work_item.configuration.defender),
        configuration_weight=work_item.configuration_weight,
        status=ConfigurationPairExecutionStatus.FAILED,
        win_probability=None,
        loss_probability=None,
        draw_probability=None,
        expected_turns=None,
        expected_turns_status=ExpectedTurnsStatus.UNAVAILABLE,
        node_count=0,
        edge_count=0,
        scc_count=0,
        max_turn_number=0,
        diagnostics=(diagnostic,),
    )


def _move_ids(configuration: PokemonBattleConfiguration) -> tuple[int, ...]:
    """提取按 ID 稳定排序的无序技能组。

    Args:
        configuration: 已完成招式集合规范化的单边配置。

    Returns:
        与原始槽位顺序无关的招式 ID 元组。
    """
    return tuple(sorted(move.move_spec.move_id for move in configuration.moves))


__all__ = ["StreamConfigurationPairsUseCase", "iter_configuration_pairs"]
