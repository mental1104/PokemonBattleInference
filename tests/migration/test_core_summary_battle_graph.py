"""原轻量SummaryStateGraphBuilder完整状态/概率/预算/SCC/metadata差分。"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.solver.summary_state_graph import SummaryStateGraphBuilder
from tests.migration.test_core_battle_graph import BuildInput, BuildReply, ExpansionMode, _BuildCase, _BuildOracle, _ScriptedExpander
from tests.migration.test_core_state import _StateOracle, _reference


class _SummaryInput(BuildInput):
    """既有诊断runner唯一新增summary分支，原扩展脚本共用而不复制第二套伪回合。"""
    summary: Literal[True] = True


@pytest.fixture
def summary_runner() -> Path:
    """优先专属显式入口，否则使用正式构图runner；没有二进制时明确skip。"""
    configured = os.environ.get("PBI_SUMMARY_BATTLE_GRAPH_RUNNER")
    if configured is None:
        configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
        if configured is not None:
            configured = str(Path(configured).parent / "pbi_battle_graph_vectors")
    if configured is None:
        pytest.skip("native summary graph runner is required")
    path = Path(configured)
    assert path.is_file()
    return path


class TestCoreSummaryBattleGraph:
    """原完整summary与Core逐字段相等，不仅检查最后概率或节点数。"""

    def test_original_summary_all_limits_empty_cycle_and_metadata(self, summary_runner: Path) -> None:
        """summary_runner为实际Core；40种原输入覆盖节点/边/回合保护、空扩展、循环及元数据丢弃。"""
        root = _reference()
        root = replace(root, defender=root.defender.with_current_hp(5))
        cases = tuple(_BuildCase(root, mode, limits) for mode in ExpansionMode for limits in (
            StateGraphLimits(), StateGraphLimits(max_nodes=1), StateGraphLimits(max_nodes=3), StateGraphLimits(max_nodes=5),
            StateGraphLimits(max_edges=1), StateGraphLimits(max_edges=2), StateGraphLimits(max_edges=5),
            StateGraphLimits(max_nodes=4, max_edges=10), StateGraphLimits(max_turns=1), StateGraphLimits(max_turns=2)))
        expected = tuple(_BuildOracle.graph(SummaryStateGraphBuilder(_ScriptedExpander(case.mode), case.limits).build(case.state)) for case in cases)
        inputs = tuple(_SummaryInput(initial=_StateOracle.snapshot(case.state), mode=case.mode, limits=case.limits) for case in cases)
        process = subprocess.run((str(summary_runner),), input="".join(value.model_dump_json() + "\n" for value in inputs),
            text=True, capture_output=True, check=True, timeout=120)
        actual = tuple(BuildReply.model_validate_json(line) for line in process.stdout.splitlines())
        assert actual == expected, process.stderr
