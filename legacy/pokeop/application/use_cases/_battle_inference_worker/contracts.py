"""定义 coordinator 与子进程之间的不可变输入合同。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pokeop.application.configuration_space import BattleConfiguration
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseSnapshot,
    BattleInferenceJobSnapshot,
)
from pokeop.application.solver.models import StateGraphLimits
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


@dataclass(frozen=True, slots=True)
class PreparedBattleInferenceCase:
    """保存可安全传给子进程的不可变单配置输入。"""

    configuration_pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    configuration: BattleConfiguration
    rules: BattleInferenceRules
    attacker_policy: BattleActionPolicyKind
    defender_policy: BattleActionPolicyKind
    graph_limits: StateGraphLimits


class BattleInferenceCasePreparer(Protocol):
    """定义父 coordinator 中的 version-aware 配置准备端口。"""

    def prepare(
        self,
        job: BattleInferenceJobSnapshot,
        case: BattleInferenceCaseSnapshot,
        execution_spec: BattleInferenceExecutionSpec,
    ) -> PreparedBattleInferenceCase:
        """读取 profile 并返回不再依赖 PostgreSQL 的不可变配置。"""
        ...
