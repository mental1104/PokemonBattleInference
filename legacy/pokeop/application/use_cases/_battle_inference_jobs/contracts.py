"""定义后台任务冻结规格、扩展存储端口和提交命令。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from pokeop.application.configuration_space.one_on_one import OneOnOneMovePoolCommand
from pokeop.application.configuration_space.one_on_one.model_base import (
    ONE_ON_ONE_CONTRACT_VERSION,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceFailureCode,
    BattleInferenceJobRepository,
    BattleInferenceJobSnapshot,
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
)


@dataclass(frozen=True, slots=True)
class BattleInferenceExecutionSpec:
    """冻结 worker 恢复任务时必须保持一致的策略和预算。"""

    contract_version: str
    weight_assumption: str
    attacker_policy: str
    defender_policy: str
    mechanism_admission: str
    process_count: int = 2
    queue_depth: int = 4
    max_nodes_per_pair: int = 20_000
    max_edges_per_pair: int = 80_000
    max_turns: int | None = 100

    def __post_init__(self) -> None:
        """校验执行规格有界且不会让 worker 静默改变任务语义。"""
        for field_name in (
            "contract_version",
            "weight_assumption",
            "attacker_policy",
            "defender_policy",
            "mechanism_admission",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field_name} must be non-empty and normalized")
        if self.contract_version != ONE_ON_ONE_CONTRACT_VERSION:
            raise ValueError("unsupported battle inference contract version")
        _require_bounded_positive("process_count", self.process_count, maximum=8)
        _require_bounded_positive("queue_depth", self.queue_depth, maximum=32)
        if self.queue_depth < self.process_count:
            raise ValueError("queue_depth must be greater than or equal to process_count")
        _require_bounded_positive(
            "max_nodes_per_pair", self.max_nodes_per_pair, maximum=2_000_000
        )
        _require_bounded_positive(
            "max_edges_per_pair", self.max_edges_per_pair, maximum=8_000_000
        )
        _require_optional_positive("max_turns", self.max_turns, maximum=10_000)

    @classmethod
    def from_command(
        cls,
        command: OneOnOneMovePoolCommand,
        *,
        process_count: int = 2,
        queue_depth: int = 4,
        max_nodes_per_pair: int = 20_000,
        max_edges_per_pair: int = 80_000,
        max_turns: int | None = 100,
    ) -> BattleInferenceExecutionSpec:
        """从已验证公开命令构造可持久化执行规格。"""
        return cls(
            contract_version=command.contract_version,
            weight_assumption=command.weight_assumption.value,
            attacker_policy=command.attacker_policy.value,
            defender_policy=command.defender_policy.value,
            mechanism_admission=command.mechanism_admission.value,
            process_count=process_count,
            queue_depth=queue_depth,
            max_nodes_per_pair=max_nodes_per_pair,
            max_edges_per_pair=max_edges_per_pair,
            max_turns=max_turns,
        )


@dataclass(frozen=True, slots=True)
class BattleInferenceRuntimeSnapshot:
    """组合任务生命周期快照和创建时冻结的执行规格。"""

    job: BattleInferenceJobSnapshot
    execution_spec: BattleInferenceExecutionSpec


@runtime_checkable
class BattleInferenceJobStore(BattleInferenceJobRepository, Protocol):
    """扩展 #85 repository，增加执行规格的原子创建与读取。"""

    def create_job_with_execution_spec(
        self,
        command: CreateBattleInferenceJob,
        execution_spec: BattleInferenceExecutionSpec,
        *,
        created_at: datetime,
    ) -> BattleInferenceRuntimeSnapshot:
        """在同一事务中创建任务、配置元数据和冻结执行规格。"""
        ...

    def get_execution_spec(self, job_id: str) -> BattleInferenceExecutionSpec:
        """读取 worker 恢复任务所需的冻结执行规格。"""
        ...

    def fail_job_if_owned(
        self,
        job_id: str,
        *,
        lease_owner: str,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot | None:
        """仅在 coordinator 仍持有有效 lease 时原子记录任务失败。"""
        ...


@runtime_checkable
class BattleInferenceAdmissionValidator(Protocol):
    """定义任务进入持久化前的双方候选机制严格准入端口。"""

    def validate(self, command: OneOnOneMovePoolCommand) -> None:
        """验证候选招式、固定特性和固定道具均可进入精确推演。"""
        ...


@dataclass(frozen=True, slots=True)
class SubmitBattleInferenceJobCommand:
    """保存一次异步任务创建所需的公开命令和冻结预算。"""

    move_pool: OneOnOneMovePoolCommand
    execution_spec: BattleInferenceExecutionSpec
    job_id: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        """确保执行规格与公开命令使用相同策略语义。"""
        if not isinstance(self.move_pool, OneOnOneMovePoolCommand):
            raise ValueError("move_pool must be OneOnOneMovePoolCommand")
        if not isinstance(self.execution_spec, BattleInferenceExecutionSpec):
            raise ValueError("execution_spec must be BattleInferenceExecutionSpec")
        if self.move_pool.calculation_revision != BATTLE_INFERENCE_CALCULATION_REVISION:
            raise ValueError(
                "calculation_revision must match the current worker calculation revision"
            )
        expected = (
            self.move_pool.contract_version,
            self.move_pool.weight_assumption.value,
            self.move_pool.attacker_policy.value,
            self.move_pool.defender_policy.value,
            self.move_pool.mechanism_admission.value,
        )
        actual = (
            self.execution_spec.contract_version,
            self.execution_spec.weight_assumption,
            self.execution_spec.attacker_policy,
            self.execution_spec.defender_policy,
            self.execution_spec.mechanism_admission,
        )
        if actual != expected:
            raise ValueError("execution_spec policies must match the move pool command")
        if self.move_pool.attacker.fixed.level != self.move_pool.defender.fixed.level:
            raise ValueError("both sides must use the same battle level")
        if self.job_id is not None and (
            not self.job_id or self.job_id != self.job_id.strip()
        ):
            raise ValueError("job_id must be normalized when provided")
        if self.idempotency_key is not None and (
            not self.idempotency_key
            or self.idempotency_key != self.idempotency_key.strip()
            or len(self.idempotency_key) > 200
        ):
            raise ValueError(
                "idempotency_key must be normalized and at most 200 characters"
            )
        if self.job_id is not None and self.idempotency_key is not None:
            raise ValueError("job_id and idempotency_key cannot be used together")
        if (
            self.move_pool.attacker.fixed.form_id is not None
            or self.move_pool.defender.fixed.form_id is not None
        ):
            raise ValueError("explicit form_id is not supported by the v1 worker")


@dataclass(frozen=True, slots=True)
class SubmittedBattleInferenceJob:
    """返回 HTTP 202 所需的最小异步任务确认信息。"""

    job_id: str
    submitted_configuration_pairs: int
    created_at: datetime


def _require_bounded_positive(field_name: str, value: int, *, maximum: int) -> None:
    """校验正整数预算不超过服务端安全上限。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer from 1 to {maximum}")


def _require_optional_positive(
    field_name: str,
    value: int | None,
    *,
    maximum: int,
) -> None:
    """校验可选正整数预算；None 表示不启用该上限。"""
    if value is not None:
        _require_bounded_positive(field_name, value, maximum=maximum)
