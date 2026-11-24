"""正式 C ABI 的概率图差分；复用原 Python oracle，覆盖序列化、SCC 和精确求解。"""
from __future__ import annotations

import random
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.solver.models import GraphNodeOutcome
from tests.migration.test_core_damage import damage_runner
from tests.migration.test_core_graph import GraphInput, GraphNode, GraphReply, _GraphOracle


class GraphOperation(GraphInput):
    """正式图操作使用同一完整拓扑，消元预算显式受 ABI 上限约束。"""
    kind: Literal["graph"] = "graph"
    max_equation_nodes: int = Field(default=128, ge=1, le=128)


class GraphBatch(BaseModel):
    """完整 C ABI 请求；所有结果按输入顺序逐项核对。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    operations: tuple[GraphOperation, ...]


class GraphResult(GraphReply):
    """完整正式结果保留不可用诊断，不将未知或无限值转换成零。"""
    kind: Literal["graph"]
    diagnostics: tuple[str, ...] = ()


class GraphEnvelope(BaseModel):
    """完整版本信封，错误或缺项不能被解码成空成功。"""
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1]
    engine_version: Literal["0.7.0"]
    rules_version: Literal["calculation-rules.v7"]
    results: tuple[GraphResult, ...]


class TestGraphABI:
    """实际 pbi_v1_compute 与原 SCC/solver 比较，不通过独立测试 runner 冒充 ABI 接入。"""
    def test_complete_graph_results_match_python(self, damage_runner: Path) -> None:
        """damage_runner 为已构建 Core 目录；比较 48 随机拓扑、200 位分母和截断未知图的全部字段。"""
        randomizer = random.Random(8932)
        specifications = [_GraphOracle.random_graph(randomizer, cyclic=kind != 0, closed=kind == 2)
                          for kind in range(3) for _ in range(16)]
        epsilon = Fraction(1, 10 ** 200)
        specifications.append(GraphInput(nodes=(GraphNode(outcome=GraphNodeOutcome.NON_TERMINAL),
            GraphNode(outcome=GraphNodeOutcome.ATTACKER_WIN)), edges=(_GraphOracle.edge(0, 0, 1 - epsilon),
            _GraphOracle.edge(0, 1, epsilon))))
        specifications.append(GraphInput(nodes=(GraphNode(outcome=GraphNodeOutcome.UNKNOWN),), edges=()))
        operations = tuple(GraphOperation.model_validate(value.model_dump(exclude_none=True)) for value in specifications)
        request = GraphBatch(operations=operations)
        process = subprocess.run([str(damage_runner.parent / "pbi_abi_vectors")], input=request.model_dump_json() + "\n",
            text=True, capture_output=True, check=True, timeout=90)
        reply = GraphEnvelope.model_validate_json(process.stdout)
        assert len(reply.results) == len(operations)
        for operation, actual in zip(operations, reply.results, strict=True):
            expected = _GraphOracle.expected(operation)
            assert actual.model_dump(exclude={"kind", "diagnostics"}) == expected.model_dump()
            if actual.status != "solved":
                assert actual.win is None and actual.loss is None and actual.draw is None
