"""测量真实 Python/C++ 非 HP 能力计算批次；C++ 时间包含进程、协议解析和 IO。"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pokeop.domain.battle.stats import calculate_non_hp_stat


@dataclass(frozen=True)
class StatCase:
    """固定批次中的只读非 HP 能力输入；使用标准十分制性格编码。"""

    base: int
    iv: int
    ev: int
    level: int
    nature_tenths: Literal[9, 10, 11]


@dataclass(frozen=True)
class BatchTiming:
    """一种实现的逐次 wall time 与中位数，保留原始采样供后续比较。"""

    seconds: tuple[float, ...]
    median_seconds: float


@dataclass(frozen=True)
class BenchmarkReport:
    """当前非 HP 切片的真实批次测量；不能代表完整战斗图或 CGO 性能。"""

    schema_version: Literal[1]
    operation: Literal["modern-non-hp-stat-batch"]
    case_count: int
    repeats: int
    platform: str
    python_version: str
    compiler: str
    binary_sha256: str
    result_sha256: str
    python: BatchTiming
    cpp_process: BatchTiming


def _python_batch(cases: Sequence[StatCase]) -> str:
    """计算并序列化 Python 参考结果。

    Args:
        cases: 只读能力配置序列，不修改。

    Returns:
        与 C++ 逐行协议一致的完整结果文本。
    """
    return "".join(
        f"{calculate_non_hp_stat(base=case.base, iv=case.iv, ev=case.ev, level=case.level, nature_modifier=case.nature_tenths / 10)}\n"
        for case in cases
    )


def benchmark(runner: Path, *, count: int, repeats: int) -> BenchmarkReport:
    """对相同批次执行真实 Python 和 C++ 计算，逐字比较所有结果后计入采样。

    Args:
        runner: CMake 构建的 C++ 向量入口。
        count: 每批非 HP 输入数量，必须大于零。
        repeats: 两种实现各自采样次数，必须大于零。

    Returns:
        含原始计时、环境与二进制/结果校验值的报告。

    Raises:
        ValueError: 数量参数不合法。
        RuntimeError: C++ 与 Python 任一结果不一致。
        subprocess.SubprocessError: C++ 失败或单批超过 60 秒。
    """
    if count <= 0 or repeats <= 0:
        raise ValueError("count and repeats must be positive")
    nature_choices: tuple[Literal[9, 10, 11], ...] = (9, 10, 11)
    cases = tuple(
        StatCase(1 + index % 255, index % 32, index % 253,
                 1 + index % 100, nature_choices[index % 3])
        for index in range(count)
    )
    requests = "".join(
        f"stat {case.base} {case.iv} {case.ev} {case.level} {case.nature_tenths}\n"
        for case in cases
    )
    # 预热只创建参考结果；每次计时仍执行完整计算，不读取缓存。
    expected = _python_batch(cases)
    python_times: list[float] = []
    cpp_times: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        actual_python = _python_batch(cases)
        python_times.append(time.perf_counter() - started)
        started = time.perf_counter()
        actual_cpp = subprocess.run(
            [str(runner)], input=requests, text=True, capture_output=True,
            check=True, timeout=60,
        ).stdout
        cpp_times.append(time.perf_counter() - started)
        if actual_cpp != expected or actual_python != expected:
            raise RuntimeError("C++ and Python benchmark results differ")
    compiler = subprocess.run(["c++", "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    return BenchmarkReport(
        schema_version=1, operation="modern-non-hp-stat-batch", case_count=count,
        repeats=repeats, platform=platform.platform(), python_version=platform.python_version(),
        compiler=compiler, binary_sha256=hashlib.sha256(runner.read_bytes()).hexdigest(),
        result_sha256=hashlib.sha256(expected.encode()).hexdigest(),
        python=BatchTiming(tuple(python_times), statistics.median(python_times)),
        cpp_process=BatchTiming(tuple(cpp_times), statistics.median(cpp_times)),
    )


def main() -> None:
    """解析 runner、批次数量和输出参数；写入实际测量 JSON，不生成性能推断。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", required=True, type=Path)
    parser.add_argument("--count", type=int, default=20000)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = benchmark(args.runner, count=args.count, repeats=args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
