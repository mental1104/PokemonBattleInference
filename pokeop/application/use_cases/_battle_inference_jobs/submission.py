"""严格准入并原子创建可恢复的后台战斗推演任务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from uuid import uuid4

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceJobAlreadyExists,
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases._battle_inference_jobs.contracts import (
    BattleInferenceAdmissionValidator,
    BattleInferenceJobStore,
    SubmitBattleInferenceJobCommand,
    SubmittedBattleInferenceJob,
)
from pokeop.application.use_cases._battle_inference_jobs.identity import (
    case_definition,
    fixed_identity,
)


@dataclass(slots=True)
class CreateBattleInferenceJobUseCase:
    """严格准入、枚举 canonical 配置身份并原子创建后台任务。"""

    store: BattleInferenceJobStore
    admission_validator: BattleInferenceAdmissionValidator

    def execute(
        self,
        command: SubmitBattleInferenceJobCommand,
        *,
        created_at: datetime,
    ) -> SubmittedBattleInferenceJob:
        """创建可由独立 worker 领取的持久化任务。"""
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        self.admission_validator.validate(command.move_pool)
        cases = tuple(
            case_definition(configuration)
            for configuration in command.move_pool.iter_configurations()
        )
        job_id = _submission_job_id(command)
        create_command = CreateBattleInferenceJob(
            job_id=job_id,
            ruleset_id=command.move_pool.ruleset_id,
            version_group_id=command.move_pool.version_group_id,
            calculation_revision=command.move_pool.calculation_revision,
            cases=cases,
        )
        try:
            self.store.create_job_with_execution_spec(
                create_command,
                command.execution_spec,
                created_at=created_at,
            )
            effective_created_at = created_at
        except BattleInferenceJobAlreadyExists:
            if command.idempotency_key is None:
                raise
            existing = self.store.get_job(
                job_id,
                calculation_revision=command.move_pool.calculation_revision,
            )
            existing_spec = self.store.get_execution_spec(job_id)
            if (
                existing.ruleset_id != command.move_pool.ruleset_id
                or existing.version_group_id != command.move_pool.version_group_id
                or existing.progress.total_count != len(cases)
                or existing_spec != command.execution_spec
            ):
                raise
            effective_created_at = existing.created_at
        return SubmittedBattleInferenceJob(
            job_id=job_id,
            submitted_configuration_pairs=len(cases),
            created_at=effective_created_at,
        )


def _submission_job_id(command: SubmitBattleInferenceJobCommand) -> str:
    """生成随机 job ID，或为显式幂等键生成内容寻址 ID。"""
    if command.job_id is not None:
        return command.job_id
    if command.idempotency_key is None:
        return f"battle-inference-{uuid4().hex}"
    move_pool = command.move_pool
    spec = command.execution_spec
    payload = json.dumps(
        [
            command.idempotency_key,
            move_pool.contract_version,
            move_pool.ruleset_id,
            move_pool.version_group_id,
            move_pool.calculation_revision,
            fixed_identity(move_pool.attacker.fixed),
            list(move_pool.attacker.candidate_move_ids),
            fixed_identity(move_pool.defender.fixed),
            list(move_pool.defender.candidate_move_ids),
            move_pool.weight_assumption.value,
            move_pool.attacker_policy.value,
            move_pool.defender_policy.value,
            move_pool.mechanism_admission.value,
            spec.process_count,
            spec.queue_depth,
            spec.max_nodes_per_pair,
            spec.max_edges_per_pair,
            spec.max_turns,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"battle-inference-idempotent-{digest}"
