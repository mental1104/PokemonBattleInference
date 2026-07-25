"""定义配置空间性能基准的版本化输入、结果和预算模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import comb

from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.application.use_cases.stream_configuration_pairs.models import (
    ConfigurationPairWorkItem,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules

FIXTURE_VERSION = "configuration-space-v1"
DEFAULT_PROGRESS_EVERY = 100
DEFAULT_SMOKE_PAIR_LIMIT = 100


def _move_set_count(candidate_count: int) -> int:
    """按产品规范计算一侧招式组数量。

    Args:
        candidate_count: 完成机制准入后的候选招式数量。

    Returns:
        候选不足四招时取全量的一种组合，否则返回 C(n, 4)。
    """
    return comb(candidate_count, min(4, candidate_count))


class BenchmarkWorkloadKind(str, Enum):
    """区分纯攻击、混合机制和高循环风险三类固定招式池。"""

    ATTACK_ONLY = "attack-only"
    MIXED = "mixed"
    CYCLIC = "cyclic"


@dataclass(frozen=True, slots=True)
class BenchmarkWorkloadSpec:
    """声明一个可重复配置空间 workload 的候选分配与图限制。

    Args:
        workload_id: JSON、Markdown 和 CLI 使用的稳定标识。
        description: 对该 workload 的人类可读目的说明。
        attacker_move_count: 攻击方候选招式数量，双方合计固定为 20。
        defender_move_count: 防守方候选招式数量，双方合计固定为 20。
        kind: 招式池的机制风险类型。
        graph_limits: 每个配置对独立使用的节点、边和回合预算。
    """

    workload_id: str
    description: str
    attacker_move_count: int
    defender_move_count: int
    kind: BenchmarkWorkloadKind
    graph_limits: StateGraphLimits

    def __post_init__(self) -> None:
        """校验 workload 标识、20 招式总量和图限制类型。

        Raises:
            ValueError: 标识未规范化、候选总量不是二十或任一侧候选为空。
            TypeError: 机制类型或状态图限制未使用显式模型。
        """
        if not self.workload_id or self.workload_id != self.workload_id.strip():
            raise ValueError("workload_id must be non-empty and normalized")
        if self.attacker_move_count + self.defender_move_count != 20:
            raise ValueError("benchmark workload must contain exactly 20 candidate moves")
        if min(self.attacker_move_count, self.defender_move_count) <= 0:
            raise ValueError("both sides must contain at least one candidate move")
        if not isinstance(self.kind, BenchmarkWorkloadKind):
            raise TypeError("kind must be BenchmarkWorkloadKind")
        if not isinstance(self.graph_limits, StateGraphLimits):
            raise TypeError("graph_limits must be StateGraphLimits")

    @property
    def attacker_configuration_count(self) -> int:
        """返回产品规范模式下攻击方无序招式组数量。

        Returns:
            候选不足四招时为一个全量组合，否则为无序四招组合数。
        """
        return _move_set_count(self.attacker_move_count)

    @property
    def defender_configuration_count(self) -> int:
        """返回产品规范模式下防守方无序招式组数量。

        Returns:
            候选不足四招时为一个全量组合，否则为无序四招组合数。
        """
        return _move_set_count(self.defender_move_count)

    @property
    def pair_count(self) -> int:
        """返回双方配置笛卡尔积的精确 case 数量。

        Returns:
            攻击方与防守方无序招式组数量的乘积。
        """
        return self.attacker_configuration_count * self.defender_configuration_count


@dataclass(frozen=True, slots=True)
class BenchmarkLimits:
    """声明 benchmark 协调器自身的累计预算与输出频率。

    Args:
        max_pairs: 最多领取的配置对数量；None 表示执行 workload 全部 case。
        cumulative_node_limit: 达到该累计节点数后停止领取新 case。
        cumulative_edge_limit: 达到该累计边数后停止领取新 case。
        max_failures: 达到该失败数后停止领取新 case。
        progress_every: 每完成多少个 case 采集一次 RSS 与累计预算曲线。
    """

    max_pairs: int | None = None
    cumulative_node_limit: int | None = None
    cumulative_edge_limit: int | None = None
    max_failures: int | None = None
    progress_every: int = DEFAULT_PROGRESS_EVERY

    def __post_init__(self) -> None:
        """拒绝零值、负值和布尔值预算。

        Raises:
            ValueError: 任一可选预算不是正整数，或进度频率不是正整数。
        """
        for name, value in (
            ("max_pairs", self.max_pairs),
            ("cumulative_node_limit", self.cumulative_node_limit),
            ("cumulative_edge_limit", self.cumulative_edge_limit),
            ("max_failures", self.max_failures),
        ):
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise ValueError(f"{name} must be greater than 0")
        if isinstance(self.progress_every, bool) or self.progress_every <= 0:
            raise ValueError("progress_every must be greater than 0")


@dataclass(frozen=True, slots=True)
class BenchmarkCaseInput:
    """保存可安全序列化到子进程的单配置 benchmark 输入。

    Args:
        work_item: 稳定配置对 ID、精确权重和双方不可变配置。
        rules: 与双方配置规则轴一致的推演规则。
        attacker_policy: 攻击方固定行动策略枚举。
        defender_policy: 防守方固定行动策略枚举。
        graph_limits: 当前 case 独立使用的状态图运行保护。
    """

    work_item: ConfigurationPairWorkItem
    rules: BattleInferenceRules
    attacker_policy: BattleActionPolicyKind
    defender_policy: BattleActionPolicyKind
    graph_limits: StateGraphLimits


@dataclass(frozen=True, slots=True)
class BenchmarkPairSample:
    """保存一个配置对的轻量性能、概率和状态图摘要。

    Args:
        pair_id: 可恢复和去重的稳定配置对 ID。
        status: succeeded、truncated 或 failed。
        diagnostic: 截断原因或异常诊断；正常成功可为 None。
        win_probability: 攻击方胜率的精确分子分母。
        loss_probability: 攻击方负率的精确分子分母。
        draw_probability: 平局率的精确分子分母。
        expected_turns: 有限期望回合的精确分子分母。
        wall_seconds: 单 case 构图和求解墙钟耗时。
        cpu_seconds: 执行该 case 的进程 CPU 耗时。
        graph_build_seconds: StateGraphBuilder 构图耗时。
        solve_seconds: PurePythonBattleGraphSolver 求解耗时。
        input_serialization_seconds: 输入对象 pickle 探针耗时。
        output_serialization_seconds: 轻量输出 pickle 探针耗时。
        input_bytes: 输入对象 pickle 字节数。
        output_bytes: 轻量输出 pickle 字节数。
        peak_rss_bytes: 执行进程已观测峰值 RSS。
        process_id: 实际执行该 case 的进程 ID。
        node_count: 唯一状态节点数量。
        edge_count: 归并后的图边数量。
        raw_transition_count: 状态扩展归并前随机转移数量。
        merged_transition_count: 按后继状态归并后的转移数量。
        scc_count: 强连通分量数量。
        max_scc_size: 最大强连通分量包含的节点数。
        max_turn_number: 图内最大回合号。
        numerator_bits: 当前概率和期望回合最大分子位数。
        denominator_bits: 当前概率和期望回合最大分母位数。

    完整 graph 在子进程函数返回前释放，本模型不得新增 graph、node 或 edge 对象字段。
    """

    pair_id: str
    status: str
    diagnostic: str | None
    win_probability: tuple[int, int] | None
    loss_probability: tuple[int, int] | None
    draw_probability: tuple[int, int] | None
    expected_turns: tuple[int, int] | None
    wall_seconds: float
    cpu_seconds: float
    graph_build_seconds: float
    solve_seconds: float
    input_serialization_seconds: float
    output_serialization_seconds: float
    input_bytes: int
    output_bytes: int
    peak_rss_bytes: int
    process_id: int
    node_count: int
    edge_count: int
    raw_transition_count: int
    merged_transition_count: int
    scc_count: int
    max_scc_size: int
    max_turn_number: int
    numerator_bits: int
    denominator_bits: int


@dataclass(frozen=True, slots=True)
class BenchmarkProgressPoint:
    """记录批量执行期间累计节点、边和 RSS 的离散曲线点。

    Args:
        processed_pairs: 采样时已经完成的配置对数量。
        elapsed_seconds: 从当前 run 启动到采样点的墙钟时间。
        parent_rss_bytes: 父协调进程已观测峰值 RSS。
        cumulative_nodes: 已完成配置累计唯一节点数。
        cumulative_edges: 已完成配置累计归并边数。
    """

    processed_pairs: int
    elapsed_seconds: float
    parent_rss_bytes: int
    cumulative_nodes: int
    cumulative_edges: int


@dataclass(frozen=True, slots=True)
class BenchmarkBudgetRecommendation:
    """保存依据本次样本自动校准出的默认值和硬上限建议。

    Args:
        default_configuration_pair_limit: 当前 workload 建议默认配置对数量。
        hard_configuration_pair_limit: 首版允许的配置对绝对硬上限。
        default_pair_node_limit: 基于样本 P95 放大的单 pair 节点默认值。
        hard_pair_node_limit: 基于样本最大值放大的单 pair 节点硬上限。
        default_pair_edge_limit: 基于样本 P95 放大的单 pair 边默认值。
        hard_pair_edge_limit: 基于样本最大值放大的单 pair 边硬上限。
        default_pair_turn_limit: 基于已观察最大回合的默认值。
        hard_pair_turn_limit: 不低于当前规则保护的回合硬上限。
        default_cumulative_node_limit: 完整空间节点累计默认预算。
        hard_cumulative_node_limit: 节点累计绝对硬上限。
        default_cumulative_edge_limit: 完整空间边累计默认预算。
        hard_cumulative_edge_limit: 边累计绝对硬上限。
        default_max_failures: 默认允许的失败配置数量。
        hard_max_failures: 失败配置绝对硬上限。
        default_worker_count: 同 workload 实测吞吐最高的建议进程数。
        hard_worker_count: 受 CPU 和首版并发上限共同限制的最大进程数。
        default_progress_every: 建议每多少个配置对写一次进度。
        hard_progress_every: 首版允许的最稀疏进度更新间隔。
    """

    default_configuration_pair_limit: int
    hard_configuration_pair_limit: int
    default_pair_node_limit: int
    hard_pair_node_limit: int
    default_pair_edge_limit: int
    hard_pair_edge_limit: int
    default_pair_turn_limit: int
    hard_pair_turn_limit: int
    default_cumulative_node_limit: int
    hard_cumulative_node_limit: int
    default_cumulative_edge_limit: int
    hard_cumulative_edge_limit: int
    default_max_failures: int
    hard_max_failures: int
    default_worker_count: int
    hard_worker_count: int
    default_progress_every: int
    hard_progress_every: int


@dataclass(frozen=True, slots=True)
class BenchmarkRunSummary:
    """保存一次 workload/worker 组合的完整机器可读基准摘要。

    Args:
        workload_id: 固定 workload 标识。
        fixture_version: 输入夹具版本。
        worker_count: 请求的配置对级进程数。
        total_pair_count: workload 完整配置空间大小。
        requested_pair_count: 考虑 smoke、恢复和 max-pairs 后计划执行数量。
        processed_pair_count: 实际完成并进入聚合的配置对数量。
        coverage_ratio: 实际完成数量占完整配置空间的比例。
        succeeded_count: 完成精确求解的配置数。
        truncated_count: 触发图运行保护的配置数。
        failed_count: 构图、求解或子进程异常配置数。
        cancelled: 当前 run 是否由 KeyboardInterrupt 取消。
        stop_reason: 完成、取消或累计预算停止原因。
        wall_seconds: 整个 run 墙钟耗时。
        cpu_seconds: 协调器与已完成 worker case 的 CPU 时间总和。
        throughput_pairs_per_second: 实际完成配置对吞吐。
        p50_pair_seconds: 单配置墙钟 P50。
        p95_pair_seconds: 单配置墙钟 P95。
        peak_rss_bytes: 父进程与 worker 样本中的最大峰值 RSS。
        rss_slope_bytes_per_pair: 父进程 RSS 首尾曲线估算斜率。
        process_count: 实际返回样本的不同进程数量。
        cumulative_node_count: 已处理配置累计节点数。
        cumulative_edge_count: 已处理配置累计边数。
        raw_transition_count: 已处理配置累计原始转移数。
        merged_transition_count: 已处理配置累计归并转移数。
        transition_merge_rate: 原始转移被归并消除的比例。
        scc_count: 已处理配置累计 SCC 数。
        max_scc_size: 全部配置最大 SCC 节点数。
        max_turn_number: 全部配置最大图回合号。
        max_numerator_bits: Fraction 最大分子位数。
        max_denominator_bits: Fraction 最大分母位数。
        fraction_aggregation_seconds: 父进程精确概率聚合耗时。
        fraction_aggregation_share: Fraction 聚合占 run 墙钟比例。
        input_serialization_seconds: 输入 pickle 探针累计耗时。
        output_serialization_seconds: 输出 pickle 探针累计耗时。
        serialized_input_bytes: 输入 pickle 累计字节数。
        serialized_output_bytes: 输出 pickle 累计字节数。
        coordinator_overhead_seconds: 扣除平均 case 执行后的协调估算开销。
        progress_update_seconds: 父进程生成进度快照累计耗时。
        postgres_write_seconds: direct-solver 模式固定为 None，避免伪造写库指标。
        probability_digest: 配置 ID、状态和精确概率形成的稳定摘要。
        speedup_vs_single_process: 相对同 workload 单进程吞吐加速比。
        profiler_top_self_time_share: 单函数最高自耗时占比。
        completed_pair_ids: 可供恢复执行使用的已完成配置 ID。
        progress_curve: 累计节点、边和 RSS 曲线。
        profiler_top_ten: 串行 cProfile 前十热点文本。
        recommendation: 根据当前样本生成的预算建议。
    """

    workload_id: str
    fixture_version: str
    worker_count: int
    total_pair_count: int
    requested_pair_count: int
    processed_pair_count: int
    coverage_ratio: float
    succeeded_count: int
    truncated_count: int
    failed_count: int
    cancelled: bool
    stop_reason: str
    wall_seconds: float
    cpu_seconds: float
    throughput_pairs_per_second: float
    p50_pair_seconds: float
    p95_pair_seconds: float
    peak_rss_bytes: int
    rss_slope_bytes_per_pair: float
    process_count: int
    cumulative_node_count: int
    cumulative_edge_count: int
    raw_transition_count: int
    merged_transition_count: int
    transition_merge_rate: float
    scc_count: int
    max_scc_size: int
    max_turn_number: int
    max_numerator_bits: int
    max_denominator_bits: int
    fraction_aggregation_seconds: float
    fraction_aggregation_share: float
    input_serialization_seconds: float
    output_serialization_seconds: float
    serialized_input_bytes: int
    serialized_output_bytes: int
    coordinator_overhead_seconds: float
    progress_update_seconds: float
    postgres_write_seconds: float | None
    probability_digest: str
    speedup_vs_single_process: float
    profiler_top_self_time_share: float
    completed_pair_ids: tuple[str, ...]
    progress_curve: tuple[BenchmarkProgressPoint, ...]
    profiler_top_ten: tuple[str, ...]
    recommendation: BenchmarkBudgetRecommendation


@dataclass(frozen=True, slots=True)
class BenchmarkConsistencyCheck:
    """记录同一 workload 两种进程数的精确结果一致性。

    Args:
        workload_id: 被比较的固定 workload。
        left_worker_count: 左侧 run 请求进程数。
        right_worker_count: 右侧 run 请求进程数。
        same_pair_set: 已完成稳定配置 ID 集合是否一致。
        same_status_counts: 成功、截断和失败计数是否一致。
        same_probability_digest: 精确概率摘要是否一致。
    """

    workload_id: str
    left_worker_count: int
    right_worker_count: int
    same_pair_set: bool
    same_status_counts: bool
    same_probability_digest: bool

    @property
    def consistent(self) -> bool:
        """返回配置集合、状态计数和精确概率摘要是否全部一致。

        Returns:
            三项一致性条件均满足时返回 True，否则返回 False。
        """
        return (
            self.same_pair_set
            and self.same_status_counts
            and self.same_probability_digest
        )


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    """记录可追溯基准所需的代码、Python、CPU 和内存环境。

    Args:
        commit: 当前 checkout commit SHA 或 unknown。
        python: 完整 Python 版本文本。
        platform: 操作系统与内核平台文本。
        machine: 硬件架构标识。
        processor: 平台可提供的处理器说明。
        cpu_count: 当前进程可见逻辑 CPU 数量。
        total_memory_bytes: 可读取时的物理内存字节数。
    """

    commit: str
    python: str
    platform: str
    machine: str
    processor: str
    cpu_count: int
    total_memory_bytes: int | None


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """组合环境、运行结果、正确性检查和语言路线结论。

    Args:
        schema_version: JSON 报告结构版本。
        fixture_version: 固定输入夹具版本。
        generated_at_unix_seconds: 报告生成时间戳。
        environment: 不包含凭据的机器与代码环境。
        runs: 已完成或部分覆盖的运行摘要。
        consistency_checks: 同 workload 跨 worker 精确一致性结果。
        language_decision: 继续 Python、先 profile 或评估局部原生加速的稳定结论。
        language_decision_reason: 支撑语言结论的完整覆盖与热点占比证据。
    """

    schema_version: int
    fixture_version: str
    generated_at_unix_seconds: float
    environment: BenchmarkEnvironment
    runs: tuple[BenchmarkRunSummary, ...]
    consistency_checks: tuple[BenchmarkConsistencyCheck, ...]
    language_decision: str
    language_decision_reason: str


__all__ = [
    "DEFAULT_PROGRESS_EVERY",
    "DEFAULT_SMOKE_PAIR_LIMIT",
    "FIXTURE_VERSION",
    "BenchmarkBudgetRecommendation",
    "BenchmarkCaseInput",
    "BenchmarkConsistencyCheck",
    "BenchmarkEnvironment",
    "BenchmarkLimits",
    "BenchmarkPairSample",
    "BenchmarkProgressPoint",
    "BenchmarkReport",
    "BenchmarkRunSummary",
    "BenchmarkWorkloadKind",
    "BenchmarkWorkloadSpec",
]
