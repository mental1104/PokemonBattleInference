"""以同组有限拓扑实测原 Python 与真实 C++ 进程；不宣称完整战斗或纯函数性能。"""

from __future__ import annotations

import argparse
import hashlib
import platform
import random
import statistics
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from tests.migration.test_core_graph import GraphReply, _GraphOracle


class TimingSamples(BaseModel):
    """某一路径的全部 wall-clock 秒采样及中位数，保留原值便于独立审查。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    samples_seconds: tuple[float, ...]
    median_seconds: float


class GraphBenchmark(BaseModel):
    """完整可重放 benchmark 证据，明确范围/开销，不把吞吐数字扩展成全引擎结论。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int = 1
    graph_count: int
    node_count: int
    edge_count: int
    repeats: int
    seed: int
    input_sha256: str
    runner_sha256: str
    python_version: str
    platform: str
    python: TimingSamples
    cpp_process: TimingSamples
    all_results_equal: bool
    scope: str


def run_benchmark(runner: Path, count: int, repeats: int) -> GraphBenchmark:
    """实测相同拓扑并逐次核对完整精确结果。

    Args:
        runner: 已构建的真实 pbi_graph_vectors 程序，不调用 Python 代理。
        count: 正数拓扑数量，轮换 DAG、有出口循环和含封闭循环图。
        repeats: 正数 wall-clock 重复次数。

    Returns:
        包含每次原始耗时与校验信息的不可变报告；不一致立即断言失败。
    """
    if count <= 0 or repeats <= 0:
        raise ValueError("benchmark count and repeats must be greater than 0")
    seed = 94061
    randomizer = random.Random(seed)
    graphs = tuple(_GraphOracle.random_graph(randomizer, cyclic=index % 3 != 0, closed=index % 3 == 2) for index in range(count))
    encoded = "\n".join(graph.model_dump_json() for graph in graphs) + "\n"
    reference = tuple(_GraphOracle.expected(graph) for graph in graphs)
    python_samples: list[float] = []
    cpp_samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        original = tuple(_GraphOracle.expected(graph) for graph in graphs)
        python_samples.append(time.perf_counter() - started)
        assert original == reference
        started = time.perf_counter()
        process = subprocess.run([str(runner)], input=encoded, text=True, capture_output=True, check=True, timeout=120)
        cpp_samples.append(time.perf_counter() - started)
        actual = tuple(GraphReply.model_validate_json(line) for line in process.stdout.splitlines())
        assert actual == reference
    return GraphBenchmark(
        graph_count=count, node_count=sum(len(graph.nodes) for graph in graphs), edge_count=sum(len(graph.edges) for graph in graphs),
        repeats=repeats, seed=seed, input_sha256=hashlib.sha256(encoded.encode()).hexdigest(),
        runner_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(), python_version=platform.python_version(), platform=platform.platform(),
        python=TimingSamples(samples_seconds=tuple(python_samples), median_seconds=statistics.median(python_samples)),
        cpp_process=TimingSamples(samples_seconds=tuple(cpp_samples), median_seconds=statistics.median(cpp_samples)),
        all_results_equal=True,
        scope="Finite topology SCC and exact absorption only. Python includes domain input projection and output models; C++ includes process, JSON parse/output and IPC. Not a pure-function or complete battle benchmark.",
    )


def main() -> None:
    """读取显式 runner/output 参数，在指定报告路径保存证据；失败退出非零，不覆盖旧输入。"""
    parser = argparse.ArgumentParser(description="Benchmark verified finite probability graphs")
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--count", type=int, default=240)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = run_benchmark(arguments.runner, arguments.count, arguments.repeats)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(result.model_dump_json(indent=2) + "\n")
    print(f"Graph benchmark verified: {result.graph_count} graphs, {result.repeats} repeats")


if __name__ == "__main__":
    main()
