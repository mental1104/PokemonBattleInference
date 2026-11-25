"""核验全部同输入benchmark报告后，才生成Full/Full及Summary/Summary有界提速表。"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tools.migration.benchmark_configuration_graph import Backend, Mode, _Parity, _RunReport


class _Contract(BaseModel):
    """完整比较输出；不接受不一致输入被默默丢弃。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Resources(_Contract):
    """CPU为两case各进程之和，RSS为最大单进程；不冒充并发进程总峰值。"""
    cpu_seconds: float
    max_individual_process_rss_bytes: int


class _Row(_Contract):
    """仅同模式/同worker的三后端比较，不用Full历史Python替代Summary参考。"""
    graph_mode: Mode
    workers: Literal[1, 2]
    pair_ids: tuple[str, ...]
    reference_results: tuple[_Parity, ...]
    expanded_nodes: tuple[int, ...]
    python_wall_seconds: float
    cpp_process_wall_seconds: float
    go_process_wall_seconds: float
    python_evaluate_including_projection_seconds: float
    cpp_evaluate_including_projection_seconds: float
    python_over_cpp_process_wall_ratio: float
    python_over_go_process_wall_ratio: float
    python_over_cpp_evaluation_ratio: float
    python: _Resources
    cpp: _Resources
    go: _Resources


class _Comparison(_Contract):
    """实际12组有界实验；PG、HTTP和完整44100吞吐均未测，不外推全空间。"""
    schema_version: Literal[1] = 1
    workload: Literal["budget-stop-10x10"] = "budget-stop-10x10"
    candidate_moves_per_side: Literal[10] = 10
    global_pair_denominator: Literal[44100] = 44100
    measured_pairs_per_run: Literal[2] = 2
    engine_version: str
    python_source_sha256: str
    benchmark_tool_sha256: str
    manifest_sha256: str
    all_same_mode_results_equal: Literal[True] = True
    all_same_mode_built_counts_equal: Literal[True] = True
    rows: tuple[_Row, ...]
    scope: str


class _ComparisonBuilder:
    """只核验原始测量和数值结果，不访问缓存图或再算战斗规则。"""

    @staticmethod
    def resources(run: _RunReport) -> _Resources:
        """run为完整两case；返回明确聚合方式的实际OS测量，避免混淆RSS单位。"""
        return _Resources(cpu_seconds=sum(sample.cpu_seconds for sample in run.samples),
            max_individual_process_rss_bytes=max(sample.peak_rss_bytes for sample in run.samples))

    @staticmethod
    def same(reference: _RunReport, actual: _RunReport) -> None:
        """先完整比较权重、状态/概率/null、统计、截断、解释及真实展开计数，再允许除法。"""
        if len(reference.samples) != 2 or len(actual.samples) != 2:
            raise ValueError("benchmark requires the original two concrete cases")
        for expected, result in zip(reference.samples, actual.samples, strict=True):
            if (result.pair_id, result.configuration_weight, result.parity, result.expanded_nodes) != (
                expected.pair_id, expected.configuration_weight, expected.parity, expected.expanded_nodes):
                raise ValueError(f"exact benchmark parity mismatch: {reference.graph_mode}/{actual.backend}/{actual.worker_count}/{result.pair_id}")

    @classmethod
    def compare(cls, reports: Sequence[_RunReport], engine_version: str) -> _Comparison:
        """reports须含两模式×三后端×workers1/2；任何版本、来源、重复或结果差异整体拒绝。"""
        indexed: dict[tuple[Mode, Backend, int], _RunReport] = {}
        for run in reports:
            key = (run.graph_mode, run.backend, run.worker_count)
            if key in indexed:
                raise ValueError(f"duplicate benchmark run: {key}")
            indexed[key] = run
        if len(indexed) != 12:
            raise ValueError("exactly twelve full/summary python/cpp/go workers1/2 runs are required")
        if len({run.python_source_sha256 for run in reports}) != 1 or len({run.manifest_sha256 for run in reports}) != 1 or len({run.benchmark_tool_sha256 for run in reports}) != 1:
            raise ValueError("benchmark original source, workload or measuring tool differs")
        if any(sample.backend_version != engine_version for run in reports if run.backend != "python" for sample in run.samples):
            raise ValueError("native benchmark engine versions differ from the validated snapshot")
        rows: list[_Row] = []
        for mode in ("full", "configuration_summary"):
            serial = indexed[(mode, "python", 1)]
            cls.same(serial, indexed[(mode, "python", 2)])
            for workers in (1, 2):
                python, cpp, go = (indexed[(mode, backend, workers)] for backend in ("python", "cpp", "go"))
                cls.same(python, cpp); cls.same(python, go)
                python_compute = tuple(sample.evaluate_including_result_projection_seconds for sample in python.samples)
                cpp_compute = tuple(sample.evaluate_including_result_projection_seconds for sample in cpp.samples)
                if any(value is None for value in (*python_compute, *cpp_compute)):
                    raise ValueError("missing measured evaluation phase")
                py_seconds = sum(value for value in python_compute if value is not None)
                cpp_seconds = sum(value for value in cpp_compute if value is not None)
                if min(py_seconds, cpp_seconds, python.measured_run_wall_seconds, cpp.measured_run_wall_seconds, go.measured_run_wall_seconds) <= 0:
                    raise ValueError("zero or negative benchmark measurement")
                rows.append(_Row(graph_mode=mode, workers=workers, pair_ids=tuple(sample.pair_id for sample in python.samples),
                    reference_results=tuple(sample.parity for sample in python.samples), expanded_nodes=tuple(sample.expanded_nodes for sample in python.samples),
                    python_wall_seconds=python.measured_run_wall_seconds, cpp_process_wall_seconds=cpp.measured_run_wall_seconds,
                    go_process_wall_seconds=go.measured_run_wall_seconds, python_evaluate_including_projection_seconds=py_seconds,
                    cpp_evaluate_including_projection_seconds=cpp_seconds, python_over_cpp_process_wall_ratio=python.measured_run_wall_seconds / cpp.measured_run_wall_seconds,
                    python_over_go_process_wall_ratio=python.measured_run_wall_seconds / go.measured_run_wall_seconds,
                    python_over_cpp_evaluation_ratio=py_seconds / cpp_seconds,
                    python=cls.resources(python), cpp=cls.resources(cpp), go=cls.resources(go)))
        first = reports[0]
        return _Comparison(engine_version=engine_version, python_source_sha256=first.python_source_sha256,
            benchmark_tool_sha256=first.benchmark_tool_sha256, manifest_sha256=first.manifest_sha256, rows=tuple(rows),
            scope="Original 10+10 candidate fixture, first two concrete pairs with global 44100 denominator and unchanged 500 nodes/2000 edges/8 turns. Each run rebuilds fresh; no cached graph queries. Full and configuration_summary compared separately. Evaluation includes result-model projection; process wall includes startup/CGO/JSON/stdio. Synthetic fact preparation measured separately; no PostgreSQL, HTTP or full-space throughput measurement. One bounded sample per implementation/workers/mode, not a statistical median or an extrapolated 44100-case result.")


def main() -> None:
    """只在完整同输入核验通过后写JSON与Markdown；失败不发布任何提速结论。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", nargs=12, required=True, type=Path)
    parser.add_argument("--engine-version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    reports = tuple(_RunReport.model_validate_json(path.read_text()) for path in args.reports)
    comparison = _ComparisonBuilder.compare(reports, args.engine_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(comparison.model_dump_json(indent=2) + "\n")
    lines = ["# 同语义配置图有界基准", "", comparison.scope, "", "所有同模式精确结果、原权重和真实展开计数一致后生成下表。", "",
        "| 模式 | Workers | Python wall(s) | C++ process(s) | Go process(s) | Python/C++ wall | Python/Go wall |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in comparison.rows:
        lines.append(f"| {row.graph_mode} | {row.workers} | {row.python_wall_seconds:.6f} | {row.cpp_process_wall_seconds:.6f} | {row.go_process_wall_seconds:.6f} | {row.python_over_cpp_process_wall_ratio:.2f}x | {row.python_over_go_process_wall_ratio:.2f}x |")
    lines.extend(("", "旧 270.777/140.881 秒保留在 legacy-graph-20261124 中，属于 Full 历史记录，未用作 Summary 的语言收益分母。", ""))
    args.output.with_suffix(".md").write_text("\n".join(lines))
    print(args.output)


if __name__ == "__main__":
    main()
