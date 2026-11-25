from __future__ import annotations

from dataclasses import dataclass, field

from pokeop.application.solver.graph_solver import (
    BattleGraphSolveError,
    BattleGraphSolveResult,
    BattleGraphSolver,
    PurePythonBattleGraphSolver,
)
from pokeop.application.solver.models import StateGraphBuildResult
from pokeop.domain.battle.inference_outcome import BattleSide


@dataclass(frozen=True, slots=True)
class SolveBattleGraphUseCase:
    """通过可替换的 ``BattleGraphSolver`` 求解一个已构建状态图。

    application 调用方只依赖该用例和 solver Protocol，不需要知道纯 Python、
    原生扩展或未来策略求解器采用的具体算法。

    Args:
        solver: 状态图求解实现；默认使用精确 ``Fraction`` 的纯 Python 版本。
    """

    solver: BattleGraphSolver = field(default_factory=PurePythonBattleGraphSolver)

    def __post_init__(self) -> None:
        """校验注入对象满足稳定求解器协议。"""
        if not isinstance(self.solver, BattleGraphSolver):
            raise BattleGraphSolveError("solver must implement BattleGraphSolver")

    def execute(
        self,
        graph: StateGraphBuildResult,
        observer: BattleSide = BattleSide.ATTACKER,
    ) -> BattleGraphSolveResult:
        """把图和观察方原样交给注入的求解器。

        Args:
            graph: #24 已构建的完整或明确截断状态图。
            observer: 胜负概率所采用的观察方。

        Returns:
            注入求解器返回的稳定求解结果。
        """
        return self.solver.solve(graph, observer)


__all__ = ["SolveBattleGraphUseCase"]
