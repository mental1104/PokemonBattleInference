"""序列化版本化 benchmark 报告，并支持从部分结果恢复。"""

from __future__ import annotations

import json
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from pokeop.benchmarks.models import BenchmarkProgressPoint, BenchmarkReport


def write_report(report: BenchmarkReport, output_dir: Path) -> tuple[Path, Path]:
    """原子写出机器可读 JSON 和人类可读 Markdown 报告。

    Args:
        report: 已完成或明确部分覆盖的 benchmark 报告。
        output_dir: 输出目录；不存在时自动创建。

    Returns:
        JSON 和 Markdown 文件的最终路径。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report.fixture_version}-{int(report.generated_at_unix_seconds)}"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    _atomic_write(json_path, json.dumps(_json_value(report), indent=2, ensure_ascii=False))
    _atomic_write(markdown_path, _markdown_report(report))
    return json_path, markdown_path


def load_resume_pair_ids(path: Path) -> frozenset[str]:
    """从先前 JSON 报告恢复全部已完成 pair ID。

    Args:
        path: 由本模块生成的版本化 JSON 报告路径。

    Returns:
        跨全部 run 去重后的稳定 pair ID 集合，供恢复执行跳过。

    Raises:
        OSError: 报告无法读取时由文件系统操作抛出。
        json.JSONDecodeError: 文件不是合法 JSON 时抛出。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    identifiers: set[str] = set()
    for run in payload.get("runs", ()):
        identifiers.update(run.get("completed_pair_ids", ()))
    return frozenset(identifiers)


def _json_value(value: Any) -> Any:
    """递归转换内部报告模型为 JSON 兼容对象。

    Args:
        value: dataclass、Enum、Path、集合或基础类型。

    Returns:
        只包含 JSON 原生标量、列表和字典的等价对象。
    """
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _markdown_report(report: BenchmarkReport) -> str:
    """把机器可读报告渲染为便于 review 的 Markdown 摘要。

    Args:
        report: 包含环境、运行、一致性和语言路线结论的完整报告。

    Returns:
        可直接写入 .md 结果文件的 UTF-8 文本。
    """
    lines = [
        f"# Configuration Space Benchmark ({report.fixture_version})",
        "",
        "## Environment",
        "",
        f"- Commit: `{report.environment.commit}`",
        f"- Python: `{report.environment.python}`",
        f"- Platform: `{report.environment.platform}`",
        f"- CPU count: `{report.environment.cpu_count}`",
        f"- Memory bytes: `{report.environment.total_memory_bytes}`",
        "",
        "## Runs",
        "",
        "| Workload | Workers | Coverage | Wall(s) | Pair/s | Speedup | "
        "P95(s) | RSS | Nodes | Edges | Merge | Status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for run in report.runs:
        lines.append(
            "| "
            + " | ".join(
                (
                    run.workload_id,
                    str(run.worker_count),
                    f"{run.processed_pair_count}/{run.total_pair_count}",
                    f"{run.wall_seconds:.3f}",
                    f"{run.throughput_pairs_per_second:.2f}",
                    f"{run.speedup_vs_single_process:.2f}x",
                    f"{run.p95_pair_seconds:.6f}",
                    str(run.peak_rss_bytes),
                    str(run.cumulative_node_count),
                    str(run.cumulative_edge_count),
                    f"{run.transition_merge_rate:.2%}",
                    f"{run.succeeded_count}/{run.truncated_count}/{run.failed_count}",
                )
            )
            + " |"
        )
    lines.extend(("", "## Consistency", ""))
    if report.consistency_checks:
        for check in report.consistency_checks:
            lines.append(
                f"- `{check.workload_id}` {check.left_worker_count} vs "
                f"{check.right_worker_count}: `{'PASS' if check.consistent else 'FAIL'}`"
            )
    else:
        lines.append("- 仅运行一个 worker 配置，未生成跨进程一致性检查。")
    lines.extend(("", "## Language Decision", ""))
    lines.append(f"- Decision: `{report.language_decision}`")
    lines.append(f"- Evidence: {report.language_decision_reason}")
    lines.extend(("", "## Notes", ""))
    lines.append(
        "- `postgres_write_seconds` 在本 direct-solver benchmark 中为 null；"
        "需要通过现有持久化 worker 另跑数据库路径，报告不会伪造写库占比。"
    )
    lines.append(
        "- `completed_pair_ids` 支持中断后通过 `--resume-from` 跳过已完成配置；"
        "报告只保存轻量摘要，不保存 graph artifact。"
    )
    return "\n".join(lines) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    """先写临时文件再替换目标，避免取消时留下半份报告。

    Args:
        path: 最终输出路径。
        content: 需要以 UTF-8 写入的完整文本。

    Side Effects:
        在同目录创建临时文件，并通过原子替换发布最终报告。
    """
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


__all__ = ["load_resume_pair_ids", "write_report"]
