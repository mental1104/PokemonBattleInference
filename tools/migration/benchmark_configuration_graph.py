"""以原budget-stop-10x10的两个具体case比较同语义Python、typed Core与正式Go进程。"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import resource
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from pokeop.application.configuration_space import ConfiguredMove
from pokeop.application.solver.graph_solver import BattleGraphSolveResult, BattleGraphSolveStatus, PurePythonBattleGraphSolver
from pokeop.application.solver.models import GraphTruncationReason, StateGraphBuildResult
from pokeop.application.solver.state_graph import StateGraphBuilder, StateGraphBuildProgress
from pokeop.application.use_cases.stream_configuration_pairs.executor import ExactConfigurationPairGraphExecutor, _effects, _initial_state, _policy
from pokeop.application.use_cases.stream_configuration_pairs.models import ConfigurationPairRuntimeProgress
from pokeop.benchmarks.execution import _InstrumentedPolicyDrivenExpander
from pokeop.benchmarks.fixtures import _move_pools, iter_benchmark_cases, workload_by_id
from pokeop.benchmarks.models import FIXTURE_VERSION, BenchmarkCaseInput
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.structured_turn_resolver import BattleEventStandardMoveTurnResolver
from pokeop.domain.models.types import Type, TypeHelper
# 复用既有差分的唯一机械wire投影；这里没有从tests借用任何战斗计算算法。
from tests.migration.test_core_actions_abi import ActionStrategy
from tests.migration.test_core_battle_graph import BuildStatistics, TerminalCounts
from tests.migration.test_core_damage import ExactFraction, TypeEfficacySnapshot
from tests.migration.test_core_graph import ExpectedTurns
from tests.migration.test_core_graph_explanation import _Explanation
from tests.migration.test_core_state import BattleSnapshot, _StateOracle
from tests.migration.test_core_turn_abi import CoverageAspect

Mode = Literal["full", "configuration_summary"]
Backend = Literal["python", "cpp", "go"]


class _Contract(BaseModel):
    """固定bench边界，任何未知或缺失数学字段都不能默认为零。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Limits(_Contract):
    """原fixture每对独立预算，不能为缩短测量擅自改变。"""
    max_nodes: Literal[500] = 500
    max_edges: Literal[2000] = 2000
    max_turns: Literal[8] = 8


class _Operation(_Contract):
    """完全可重放的正式Core请求；配置权重另保留全局44100分母。"""
    kind: Literal["fixed_battle"] = "fixed_battle"
    state: BattleSnapshot
    type_chart: tuple[TypeEfficacySnapshot, ...]
    attacker_policy: ActionStrategy = ActionStrategy.uniform
    defender_policy: ActionStrategy = ActionStrategy.uniform
    observer: BattleSide = BattleSide.ATTACKER
    graph_limits: _Limits = _Limits()
    max_equation_nodes: None = None
    include_graph: Literal[False] = False
    include_root_action_explanation: Literal[True] = True
    graph_mode: Mode


class _PreparationTiming(_Contract):
    """分开原fixture、静态相克知识和机械请求投影；本夹具没有PG知识读取。"""
    fixture_preparation_seconds: float
    type_chart_preparation_seconds: float
    state_request_projection_seconds: float


class _Candidate(_Contract):
    """全20个原候选的可重放事实，不只保存所取两例的八个招式。"""
    move_id: int
    name: str
    type: int
    category: MoveCategory
    power: int
    max_pp: int
    effect_identifier: str | None


class _CaseManifest(_Contract):
    """原稳定case身份、全局权重与两种唯一显式图模式输入。"""
    pair_id: str
    configuration_weight: ExactFraction
    attacker_configuration_id: str
    defender_configuration_id: str
    full_operation: _Operation
    summary_operation: _Operation


class _Manifest(_Contract):
    """固定workload的完整输入证据，与后续测量报告共同绑定内容SHA。"""
    schema_version: Literal[1] = 1
    fixture_version: str
    workload: Literal["budget-stop-10x10"] = "budget-stop-10x10"
    candidate_pools: tuple[tuple[_Candidate, ...], tuple[_Candidate, ...]]
    total_pair_count: Literal[44100] = 44100
    max_pairs: Literal[2] = 2
    worker_counts: tuple[Literal[1], Literal[2]] = (1, 2)
    graph_limits: _Limits = _Limits()
    python_source_sha256: str
    preparation_measurement: _PreparationTiming
    cases: tuple[_CaseManifest, _CaseManifest]


class _Environment(_Contract):
    """真实平台/负载及容器已公开限制，不将机器总资源误称为容器配额。"""
    python: str
    platform: str
    cpu_count: int
    load_average: tuple[float, float, float]
    pid: int
    transport: str
    knowledge_io: str
    memory_limit: str
    cpu_quota: str
    cpu_period: str
    cpuset: str
    memory_v2_limit: str
    cpu_v2_limit: str


class _Parity(_Contract):
    """两种实现必须严格相等的完整摘要；diagnostic文字单独保留，不冒充数值误差。"""
    observer: BattleSide
    status: BattleGraphSolveStatus
    win: ExactFraction | None
    loss: ExactFraction | None
    draw: ExactFraction | None
    closed_cycle: ExactFraction | None
    expected_turns: ExpectedTurns
    statistics: BuildStatistics
    truncations: tuple[GraphTruncationReason, ...]
    root_action_explanation: _Explanation | None


class _FixedResult(_Parity):
    """正式codec完整摘要，先严格decode全部字段，再显式提取可比较部分。"""
    kind: Literal["fixed_battle"]
    diagnostics: tuple[str, ...]
    unsupported_aspects: tuple[CoverageAspect, ...]
    graph: None


class _Envelope(_Contract):
    """正式Go/CABI完整响应，不接受错误或半批results。"""
    schema_version: Literal[1]
    engine_version: str
    rules_version: str
    results: tuple[_FixedResult, ...]


class _Progress(_Contract):
    """正式Go worker原built帧，不从最终图大小推测已展开数量。"""
    operation_index: Literal[0]
    phase: Literal["building", "built"]
    nodes: int
    edges: int
    expanded: int
    frontier: int


class _ProgressFrame(_Contract):
    """正式worker原进度帧完整合同。"""
    kind: Literal["progress"]
    progress: _Progress


class _ResultFrame(_Contract):
    """正式worker唯一终帧完整合同。"""
    kind: Literal["result"]
    response: _Envelope


_Frame: TypeAdapter[_ProgressFrame | _ResultFrame] = TypeAdapter(Annotated[_ProgressFrame | _ResultFrame, Field(discriminator="kind")])


class _NativeTiming(_Contract):
    """native适配器按实际执行边界测量，evaluate仍包含小型结果模型投影。"""
    json_decode_seconds: float
    typed_preparation_seconds: float
    evaluate_including_result_projection_seconds: float
    result_json_encode_seconds: float
    process_cpu_seconds: float
    peak_rss_bytes: int
    expanded_nodes: int
    frontier: int


class _NativeResult(_Contract):
    """独立薄计时adapter复用正式codec的完整结果，未重写构图/求解。"""
    engine_version: str
    result: _FixedResult
    timing: _NativeTiming


class _PairSample(_Contract):
    """一个具体case的原权重、精确结果、分层计时与真实进程资源。"""
    pair_id: str
    configuration_weight: ExactFraction
    parity: _Parity
    diagnostics: tuple[str, ...]
    backend_version: str
    evaluate_including_result_projection_seconds: float | None
    preparation_seconds: float
    serialization_seconds: float
    process_wall_seconds: float
    cpu_seconds: float
    peak_rss_bytes: int
    input_bytes: int
    output_bytes: int
    expanded_nodes: int
    native_timing: _NativeTiming | None = None


class _RunReport(_Contract):
    """单模式/实现/worker的完整测量；只有所有同模式精确结果相等后才计算提速。"""
    schema_version: Literal[1] = 1
    workload: Literal["budget-stop-10x10"] = "budget-stop-10x10"
    fixture_version: str
    total_pair_count: Literal[44100] = 44100
    processed_pair_count: Literal[2] = 2
    coverage: ExactFraction
    backend: Backend
    graph_mode: Mode
    worker_count: Literal[1, 2]
    source_revision: str
    python_source_sha256: str
    manifest_sha256: str
    binary_sha256: str | None
    measured_run_wall_seconds: float
    coordinator_cpu_seconds: float
    environment: _Environment
    environment_before: _Environment
    preparation: _PreparationTiming
    benchmark_tool_sha256: str
    samples: tuple[_PairSample, ...]


@dataclass(frozen=True)
class _PreparedCase:
    """原fixture实际输入加同一Core operation，池规模和全局权重未因取前两对改变。"""
    original: BenchmarkCaseInput
    operation: _Operation


class _Preparation:
    """只准备真实fixture和机械wire事实；不执行、缓存或预先推算战斗结果。"""

    @staticmethod
    def cases(mode: Mode) -> tuple[tuple[_PreparedCase, ...], _PreparationTiming]:
        """mode选择完整/任务摘要；返回同两case及明确准备阶段耗时。"""
        started = time.perf_counter()
        workload = workload_by_id("budget-stop-10x10")
        assert workload.attacker_move_count == workload.defender_move_count == 10 and workload.pair_count == 44100
        originals = tuple(islice(iter_benchmark_cases(workload), 2))
        fixture_seconds = time.perf_counter() - started
        chart_started = time.perf_counter()
        chart = tuple(TypeEfficacySnapshot(attacking=first, defending=second, percent=TypeHelper.get_type_efficacy(first, second)) for first in Type for second in Type)
        chart_seconds = time.perf_counter() - chart_started
        projection_started = time.perf_counter()
        cases = tuple(_PreparedCase(original, _Operation(state=_StateOracle.snapshot(_initial_state(original.work_item.configuration, original.rules)),
            type_chart=chart, graph_mode=mode)) for original in originals)
        for case in cases:
            assert case.original.work_item.configuration_weight.numerator == 1 and case.original.work_item.configuration_weight.denominator == 44100
        return cases, _PreparationTiming(fixture_preparation_seconds=fixture_seconds, type_chart_preparation_seconds=chart_seconds,
            state_request_projection_seconds=time.perf_counter() - projection_started)

    @staticmethod
    def source_digest(root: Path) -> str:
        """root为所属源码；哈希全部原Python源码字节与相对路径，不把Git HEAD当内容证明。"""
        digest = hashlib.sha256()
        for path in sorted((root / "pokeop").rglob("*.py")):
            digest.update(str(path.relative_to(root)).encode()); digest.update(b"\0"); digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def manifest(root: Path) -> _Manifest:
        """返回两种模式原完整输入、全20候选与固定限制，可独立复现所有后续测量。"""
        workload = workload_by_id("budget-stop-10x10")
        first, second = _move_pools(workload)
        def candidates(pool: tuple[ConfiguredMove, ...]) -> tuple[_Candidate, ...]:
            """pool为原真实候选；只编码完整事实，绝不改变招式组合或截取候选池。"""
            return tuple(_Candidate(move_id=move.move_spec.move_id, name=move.move_spec.move.name,
                type=move.move_spec.move.type.value, category=move.move_spec.move.category, power=move.move_spec.move.power,
                max_pp=move.move_spec.max_pp, effect_identifier=move.effect_identifier) for move in pool)
        cases, phases = _Preparation.cases("full")
        def case_manifest(case: _PreparedCase) -> _CaseManifest:
            """case为原前两具体配置之一；两个operation仅graph_mode不同。"""
            return _CaseManifest(pair_id=case.original.work_item.pair_id,
                configuration_weight=_StateOracle.fraction(case.original.work_item.configuration_weight),
                attacker_configuration_id=case.original.work_item.attacker_configuration_id,
                defender_configuration_id=case.original.work_item.defender_configuration_id,
                full_operation=case.operation, summary_operation=case.operation.model_copy(update={"graph_mode": "configuration_summary"}))
        return _Manifest(fixture_version=FIXTURE_VERSION, candidate_pools=(candidates(first), candidates(second)),
            python_source_sha256=_Preparation.source_digest(root), preparation_measurement=phases,
            cases=(case_manifest(cases[0]), case_manifest(cases[1])))


@dataclass
class _BuildObserver:
    """只记录真实graph_built帧；不误用原executor求解阶段的估计expanded数。"""
    expanded_nodes: int | None = None

    def write_graph_progress(self, progress: StateGraphBuildProgress) -> None:
        """progress为原builder帧；只保存实际完成帧，不改变图/调度。"""
        if progress.phase == "graph_built":
            self.expanded_nodes = progress.expanded_node_count

    def write_runtime_progress(self, progress: ConfigurationPairRuntimeProgress) -> None:
        """progress为原任务executor适配帧；过滤动作组和solving_probabilities估计。"""
        if progress.phase == "graph_built":
            self.expanded_nodes = progress.expanded_node_count


class _Original:
    """直接复用原P0 Full builder和原任务ExactExecutor；每次都新建图而不是查询缓存。"""

    @staticmethod
    def parity(graph: StateGraphBuildResult, solved: BattleGraphSolveResult, explanation: str | None) -> _Parity:
        """仅机械投影完整原统计和精确解，所有计算来自原builder/solver。"""
        def fraction(value: Fraction | None) -> ExactFraction | None:
            """只接受原明确Fraction/null；其它类型立即失败，不能经float转换。"""
            if value is None:
                return None
            return _StateOracle.fraction(value)
        counts, stats = graph.statistics.terminal_counts, graph.statistics
        return _Parity(observer=solved.observer, status=solved.status, win=fraction(solved.win_probability), loss=fraction(solved.loss_probability),
            draw=fraction(solved.draw_probability), closed_cycle=fraction(solved.closed_cycle_probability),
            expected_turns=ExpectedTurns(status=solved.expected_turns.status, value=fraction(solved.expected_turns.value)),
            statistics=BuildStatistics(nodes=stats.unique_state_count, edges=stats.edge_count, max_turn_number=stats.max_turn_number,
                closed_cycles=stats.closed_cycle_count, terminal_reachable_cycles=stats.terminal_reachable_cycle_count,
                terminal_counts=TerminalCounts(attacker_wins=counts.attacker_wins, defender_wins=counts.defender_wins,
                    draws=counts.draws, non_terminal=counts.non_terminal, unknown=counts.unknown)),
            truncations=graph.truncation_reasons,
            root_action_explanation=None if explanation is None else _Explanation.model_validate_json(explanation))

    @staticmethod
    def execute(prepared: _PreparedCase) -> _PairSample:
        """prepared为同一原具体case；返回新构图/求解/投影的实际计时、结果和进程资源。"""
        case = prepared.original
        observer = _BuildObserver()
        started, cpu_started = time.perf_counter(), time.process_time()
        if prepared.operation.graph_mode == "configuration_summary":
            artifact = ExactConfigurationPairGraphExecutor().execute(case.work_item, rules=case.rules,
                attacker_policy=case.attacker_policy, defender_policy=case.defender_policy, observer=BattleSide.ATTACKER, graph_limits=case.graph_limits, progress_observer=observer)
            graph, solved, explanation = artifact.graph, artifact.solve_result, artifact.explanation_json
        else:
            factory = PokemonChampionEffectFactory()
            expander = _InstrumentedPolicyDrivenExpander(BattleEventStandardMoveTurnResolver(effects=_effects(case.work_item.configuration, factory)),
                _policy(case.attacker_policy), _policy(case.defender_policy))
            graph = StateGraphBuilder(expander, case.graph_limits, progress_observer=observer).build(_initial_state(case.work_item.configuration, case.rules))
            solved = PurePythonBattleGraphSolver().solve(graph, BattleSide.ATTACKER)
            # 此冻结workload两例都截断，原解释为空；若未来fixture改变则必须显式重新审查。
            if graph.is_complete:
                raise RuntimeError("frozen full benchmark unexpectedly completed")
            explanation = None
        if observer.expanded_nodes is None:
            raise RuntimeError("original builder did not emit actual built progress")
        parity = _Original.parity(graph, solved, explanation)
        evaluate_seconds = time.perf_counter() - started
        cpu_seconds = time.process_time() - cpu_started
        encode_started = time.perf_counter()
        output = parity.model_dump_json()
        encode_seconds = time.perf_counter() - encode_started
        return _PairSample(pair_id=case.work_item.pair_id, configuration_weight=_StateOracle.fraction(case.work_item.configuration_weight),
            parity=parity, diagnostics=solved.diagnostics, backend_version=platform.python_version(),
            evaluate_including_result_projection_seconds=evaluate_seconds, preparation_seconds=0,
            serialization_seconds=encode_seconds, process_wall_seconds=time.perf_counter() - started, cpu_seconds=cpu_seconds,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024, input_bytes=0, output_bytes=len(output.encode()), expanded_nodes=observer.expanded_nodes)


class _Process:
    """一次子进程唯一owner；wait4记录该进程真实CPU和RSS，不混用父进程累计峰值。"""

    @staticmethod
    def execute(executable: Path, request: bytes, arguments: tuple[str, ...] = ()) -> tuple[bytes, float, float, int]:
        """executable为固定绝对路径；request只读；返回stdout、实际wall/CPU/RSS，错误不形成性能样本。"""
        started = time.perf_counter()
        # stdin为真实pipe；结果写匿名临时文件避免wait4前管道塞满，边界在报告中明确。
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            process = subprocess.Popen((str(executable), *arguments), stdin=subprocess.PIPE, stdout=output, stderr=error)
            reaped = False
            try:
                assert process.stdin is not None
                process.stdin.write(request); process.stdin.close()
                while True:
                    child, status, usage = os.wait4(process.pid, os.WNOHANG)
                    if child:
                        reaped = True; process.returncode = os.waitstatus_to_exitcode(status); break
                    if time.perf_counter() - started > 1800:
                        raise TimeoutError("bounded benchmark process exceeded 1800 seconds")
                    time.sleep(0.005)
                wall_seconds = time.perf_counter() - started
                output.seek(0); body = output.read()
                if process.returncode:
                    error.seek(0)
                    raise RuntimeError(f"benchmark worker exit={process.returncode}: {error.read(4096).decode(errors='replace')}")
                return body, wall_seconds, usage.ru_utime + usage.ru_stime, usage.ru_maxrss * 1024
            finally:
                if not reaped:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                    _, status, _ = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)

    @classmethod
    def sample(cls, prepared: _PreparedCase, backend: Backend, executable: Path) -> _PairSample:
        """同一准备输入分别经过typed Core adapter或正式Go/CABI，完整结果先严格decode。"""
        encode_started = time.perf_counter()
        operation = prepared.operation.model_dump_json()
        request = (operation + "\n").encode() if backend == "cpp" else ("{\"schema_version\":1,\"operations\":[" + operation + "]}").encode()
        serialization_seconds = time.perf_counter() - encode_started
        body, wall_seconds, cpu_seconds, rss = cls.execute(executable, request, () if backend == "cpp" else ("--progress",))
        decode_started = time.perf_counter()
        native = _NativeResult.model_validate_json(body) if backend == "cpp" else None
        if native is None:
            envelope: _Envelope | None = None
            expanded: int | None = None
            frames = tuple(_Frame.validate_json(line) for line in body.splitlines())
            for frame in frames:
                if isinstance(frame, _ProgressFrame):
                    if envelope is not None:
                        raise RuntimeError("progress after final result")
                    if frame.progress.phase == "built":
                        expanded = frame.progress.expanded
                elif envelope is None:
                    envelope = frame.response
                else:
                    raise RuntimeError("duplicate final worker result")
            if envelope is None or expanded is None:
                raise RuntimeError("missing actual Go built/result frames")
            if len(envelope.results) != 1:
                raise RuntimeError("benchmark expected one exact Core result")
            result, version = envelope.results[0], envelope.engine_version
        else:
            result, version = native.result, native.engine_version
            expanded = native.timing.expanded_nodes
        parity = _Parity.model_validate(result.model_dump(exclude={"kind", "diagnostics", "unsupported_aspects", "graph"}))
        serialization_seconds += time.perf_counter() - decode_started
        if result.unsupported_aspects:
            raise RuntimeError("frozen neutral benchmark unexpectedly has unsupported behavior")
        return _PairSample(pair_id=prepared.original.work_item.pair_id, configuration_weight=_StateOracle.fraction(prepared.original.work_item.configuration_weight),
            parity=parity, diagnostics=result.diagnostics, backend_version=version,
            evaluate_including_result_projection_seconds=None if native is None else native.timing.evaluate_including_result_projection_seconds,
            preparation_seconds=0 if native is None else native.timing.typed_preparation_seconds, serialization_seconds=serialization_seconds,
            process_wall_seconds=wall_seconds, cpu_seconds=cpu_seconds, peak_rss_bytes=rss, input_bytes=len(request), output_bytes=len(body),
            expanded_nodes=expanded, native_timing=None if native is None else native.timing)


def _environment() -> _Environment:
    """采集真实机器及容器限制；缺失cgroup字段明确unavailable，不推测配额。"""
    def limit(path: str) -> str:
        """path为固定公开cgroup字段；返回实际文本或明确不可用，不读取私有环境变量。"""
        file = Path(path)
        return file.read_text().strip() if file.is_file() else "unavailable"
    return _Environment(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count() or 0, load_average=os.getloadavg(), pid=os.getpid(),
        transport="stdin pipe; stdout anonymous temporary file; exact child wait4 resource accounting",
        knowledge_io="synthetic frozen original fixture; no SQL/HTTP/cache lookup",
        memory_limit=limit("/sys/fs/cgroup/memory/memory.limit_in_bytes"), cpu_quota=limit("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"),
        cpu_period=limit("/sys/fs/cgroup/cpu/cpu.cfs_period_us"), cpuset=limit("/sys/fs/cgroup/cpuset/cpuset.cpus"),
        memory_v2_limit=limit("/sys/fs/cgroup/memory.max"), cpu_v2_limit=limit("/sys/fs/cgroup/cpu.max"))


def _run(backend: Backend, mode: Mode, workers: Literal[1, 2], executable: Path | None, output: Path, revision: str, manifest_path: Path) -> None:
    """执行一个明确模式/并发度的全两case，保存逐例结果和资源，不在此计算提速。"""
    tool_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    environment_before = _environment()
    cases, phases = _Preparation.cases(mode)
    manifest_bytes = manifest_path.read_bytes()
    manifest = _Manifest.model_validate_json(manifest_bytes)
    root = Path(__file__).resolve().parents[2]
    source_digest = _Preparation.source_digest(root)
    if source_digest != manifest.python_source_sha256:
        raise RuntimeError("original Python source drifted after workload preparation")
    for prepared, frozen in zip(cases, manifest.cases, strict=True):
        frozen_operation = frozen.full_operation if mode == "full" else frozen.summary_operation
        if prepared.original.work_item.pair_id != frozen.pair_id or prepared.operation != frozen_operation:
            raise RuntimeError("fixed benchmark input drifted")
    started, cpu_started = time.perf_counter(), time.process_time()
    if backend == "python":
        if workers == 1:
            samples = tuple(_Original.execute(case) for case in cases)
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                samples = tuple(pool.map(_Original.execute, cases))
    else:
        if executable is None or not executable.is_absolute() or not executable.is_file():
            raise ValueError("cpp/go backend requires an existing absolute --executable")
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = tuple(pool.submit(_Process.sample, case, backend, executable) for case in cases)
            samples = tuple(future.result() for future in futures)
    wall_seconds = time.perf_counter() - started
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != tool_digest or manifest_path.read_bytes() != manifest_bytes:
        raise RuntimeError("benchmark tool or frozen manifest changed during measurement")
    report = _RunReport(fixture_version=FIXTURE_VERSION, coverage=ExactFraction(numerator="2", denominator="44100"), backend=backend,
        graph_mode=mode, worker_count=workers, source_revision=revision, python_source_sha256=source_digest,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), binary_sha256=None if executable is None else hashlib.sha256(executable.read_bytes()).hexdigest(),
        measured_run_wall_seconds=wall_seconds, coordinator_cpu_seconds=time.process_time() - cpu_started, environment=_environment(), environment_before=environment_before, preparation=phases,
        benchmark_tool_sha256=tool_digest, samples=samples)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n")
    print(f"{backend}/{mode}/workers={workers}: {wall_seconds:.6f}s; {len(samples)}/44100; saved {output}", flush=True)


def main() -> None:
    """准备原完整workload或执行一个有界实现；报告中不自动把不一致结果换算提速。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--backend", choices=("python", "cpp", "go"), default="python")
    parser.add_argument("--mode", choices=("full", "configuration_summary"), default="configuration_summary")
    parser.add_argument("--workers", choices=(1, 2), type=int, default=1)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()
    if args.prepare:
        manifest = _Preparation.manifest(Path(__file__).resolve().parents[2])
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(manifest.model_dump_json(indent=2) + "\n")
        print(args.manifest)
        return
    if args.output is None:
        parser.error("--output is required for a measured run")
    _run(args.backend, args.mode, args.workers, args.executable, args.output, args.source_revision, args.manifest)


if __name__ == "__main__":
    main()
