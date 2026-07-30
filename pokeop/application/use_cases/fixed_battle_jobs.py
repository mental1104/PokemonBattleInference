"""创建固定配置精确推演后台任务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from pokeop.application.configuration_space import (
    ConfigurationDimensionMode,
    FixedPokemonConfiguration,
    MechanismAdmissionPolicy,
    OneOnOneActionPolicy,
    OneOnOneConfigurationWeightAssumption,
    OneOnOneDimensionModes,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceJobAlreadyExists,
    BattleInferenceJobSnapshot,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    BattleInferenceJobStore,
    CreateBattleInferenceJobUseCase,
    SubmitBattleInferenceJobCommand,
)
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.application.use_cases.fixed_battle_workflow import FixedBattleSideSelection
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
    BattleActionPolicyKind,
)


FIXED_ONE_ON_ONE_JOB_TYPE = "fixed-one-on-one"
FIXED_ONE_ON_ONE_JOB_ID_PREFIX = "fixed-one-on-one-job-"


@dataclass(frozen=True, slots=True)
class SubmitFixedBattleJobCommand:
    """保存一次固定配置异步任务提交的完整 application 输入。

    Args:
        ruleset_id: 规则集稳定标识。
        version_group_id: PokeAPI version group 正整数 ID。
        attacker: 攻击方固定非招式配置。
        attacker_move_ids: 攻击方最终选择的一到四个招式 ID。
        defender: 防守方固定非招式配置。
        defender_move_ids: 防守方最终选择的一到四个招式 ID。
        attacker_policy: 攻击方行动策略。
        defender_policy: 防守方行动策略。
        max_nodes: 单固定配置状态图节点预算。
        max_edges: 单固定配置状态图边预算。
        max_turns: 单固定配置最大推演回合。
        idempotency_key: HTTP `Idempotency-Key`；相同 key 只对应同一个固定任务。
    """

    ruleset_id: str
    version_group_id: int
    attacker: FixedBattleSideSelection
    attacker_move_ids: tuple[int, ...]
    defender: FixedBattleSideSelection
    defender_move_ids: tuple[int, ...]
    attacker_policy: BattleActionPolicyKind
    defender_policy: BattleActionPolicyKind
    max_nodes: int
    max_edges: int
    max_turns: int
    idempotency_key: str

    def __post_init__(self) -> None:
        """校验固定任务只能绑定一个双方技能组快照。

        Raises:
            ValueError: 任一字段不能形成可恢复的单 case 任务时抛出。
        """
        if not self.ruleset_id or self.ruleset_id != self.ruleset_id.strip():
            raise ValueError("ruleset_id must be normalized")
        if isinstance(self.version_group_id, bool) or self.version_group_id <= 0:
            raise ValueError("version_group_id must be positive")
        if self.attacker.level != self.defender.level:
            raise ValueError("both sides must use the same level")
        if not self.idempotency_key or self.idempotency_key != self.idempotency_key.strip():
            raise ValueError("idempotency_key is required for fixed battle jobs")
        if len(self.idempotency_key) > 200:
            raise ValueError("idempotency_key must be at most 200 characters")
        for field_name, value, maximum in (
            ("max_nodes", self.max_nodes, 2_000_000),
            ("max_edges", self.max_edges, 8_000_000),
            ("max_turns", self.max_turns, 10_000),
        ):
            if isinstance(value, bool) or not 1 <= value <= maximum:
                raise ValueError(f"{field_name} must be from 1 to {maximum}")


@dataclass(frozen=True, slots=True)
class SubmittedFixedBattleJob:
    """返回固定配置任务创建后的可展示快照。

    Args:
        job: 当前持久化任务快照。
        submitted_configuration_pairs: 固定任务恒为 1，用于复用列表展示。
        created_new: 本次请求是否实际创建了新任务；幂等复用旧任务时为 False。
    """

    job: BattleInferenceJobSnapshot
    submitted_configuration_pairs: int
    created_new: bool


@dataclass(slots=True)
class CreateFixedBattleInferenceJobUseCase:
    """把固定配置推演提交为现有 worker 可领取的单 case 后台任务。

    Args:
        store: 后台任务 store，负责 job/case/spec 的事务性持久化。
        create_job_use_case: 现有配置空间任务创建用例；固定任务复用其准入和 case 创建。
    """

    store: BattleInferenceJobStore
    create_job_use_case: CreateBattleInferenceJobUseCase

    def execute(
        self,
        command: SubmitFixedBattleJobCommand,
        *,
        created_at: datetime,
    ) -> SubmittedFixedBattleJob:
        """创建或幂等返回一个固定配置后台任务。

        Args:
            command: 已由 API 转换并携带幂等键的固定配置任务命令。
            created_at: 带时区创建时间。

        Returns:
            固定任务快照和是否新建的标记。

        Raises:
            BattleInferenceJobAlreadyExists: 相同幂等键已绑定不同请求时抛出。
            ValueError: 输入无法转为现有单 case 任务时抛出。
        """
        move_pool = _move_pool_command(command)
        execution_spec = _execution_spec(command, move_pool)
        job_id = _idempotent_job_id(command.idempotency_key)
        try:
            submitted = self.create_job_use_case.execute(
                SubmitBattleInferenceJobCommand(
                    move_pool=move_pool,
                    execution_spec=execution_spec,
                    job_id=job_id,
                ),
                created_at=created_at,
            )
            return SubmittedFixedBattleJob(
                job=self.store.get_job(submitted.job_id),
                submitted_configuration_pairs=submitted.submitted_configuration_pairs,
                created_new=True,
            )
        except BattleInferenceJobAlreadyExists:
            existing = self.store.get_job(job_id)
            existing_spec = self.store.get_execution_spec(job_id)
            page = self.store.list_cases(
                job_id,
                BattleInferenceCaseFilter(limit=1),
            )
            if existing_spec != execution_spec or len(page.items) != 1:
                raise
            case = page.items[0]
            expected_case = next(move_pool.iter_configurations())
            expected_definition = case_definition(expected_case)
            if (
                case.definition.configuration_pair_id
                != expected_definition.configuration_pair_id
                or case.definition.attacker_configuration_id
                != expected_definition.attacker_configuration_id
                or case.definition.defender_configuration_id
                != expected_definition.defender_configuration_id
                or case.definition.attacker_move_ids != expected_case.attacker_move_ids
                or case.definition.defender_move_ids != expected_case.defender_move_ids
                or existing.ruleset_id != move_pool.ruleset_id
                or existing.version_group_id != move_pool.version_group_id
            ):
                raise
            return SubmittedFixedBattleJob(
                job=existing,
                submitted_configuration_pairs=1,
                created_new=False,
            )


def _move_pool_command(command: SubmitFixedBattleJobCommand) -> OneOnOneMovePoolCommand:
    """把固定技能组适配为只生成一个配置对的现有技能池命令。

    Args:
        command: 固定配置任务命令。

    Returns:
        双方候选池分别等于最终技能组的 `OneOnOneMovePoolCommand`。
    """
    return OneOnOneMovePoolCommand(
        contract_version="one-on-one-move-pool.v1",
        ruleset_id=command.ruleset_id,
        version_group_id=command.version_group_id,
        calculation_revision=BATTLE_INFERENCE_CALCULATION_REVISION,
        dimensions=OneOnOneDimensionModes(
            pokemon=ConfigurationDimensionMode.FIXED,
            form=ConfigurationDimensionMode.FIXED,
            level=ConfigurationDimensionMode.FIXED,
            stats=ConfigurationDimensionMode.FIXED,
            ability=ConfigurationDimensionMode.FIXED,
            item=ConfigurationDimensionMode.FIXED,
            moves=ConfigurationDimensionMode.CANDIDATE_POOL,
            special_mechanics=ConfigurationDimensionMode.DISABLED,
        ),
        weight_assumption=OneOnOneConfigurationWeightAssumption.UNIFORM_CONFIGURATION_PAIR,
        attacker_policy=_one_on_one_policy(command.attacker_policy),
        defender_policy=_one_on_one_policy(command.defender_policy),
        mechanism_admission=MechanismAdmissionPolicy.SUPPORTED_ONLY,
        attacker=PokemonMovePoolSelection(
            fixed=_fixed_configuration(command.attacker),
            candidate_move_ids=command.attacker_move_ids,
        ),
        defender=PokemonMovePoolSelection(
            fixed=_fixed_configuration(command.defender),
            candidate_move_ids=command.defender_move_ids,
        ),
    )


def _execution_spec(
    command: SubmitFixedBattleJobCommand,
    move_pool: OneOnOneMovePoolCommand,
) -> BattleInferenceExecutionSpec:
    """为单固定配置冻结 worker 执行预算。

    Args:
        command: 固定配置任务命令。
        move_pool: 与该固定任务对应的单 case 技能池命令。

    Returns:
        进程数和队列深度均为 1 的执行规格，避免单固定配置占用批量并发。
    """
    return BattleInferenceExecutionSpec.from_command(
        move_pool,
        process_count=1,
        queue_depth=1,
        max_nodes_per_pair=command.max_nodes,
        max_edges_per_pair=command.max_edges,
        max_turns=command.max_turns,
    )


def _fixed_configuration(selection: FixedBattleSideSelection) -> FixedPokemonConfiguration:
    """转换一侧固定配置为配置空间 canonical 身份对象。"""
    return FixedPokemonConfiguration(
        pokemon_id=selection.pokemon_id,
        form_id=selection.form_id,
        level=selection.level,
        stat_profile_id=selection.stat_profile_id,
        ability_identifier=selection.ability_identifier,
        item_identifier=selection.item_identifier,
    )


def _one_on_one_policy(policy: BattleActionPolicyKind) -> OneOnOneActionPolicy:
    """把固定推演策略枚举映射为配置空间任务策略枚举。"""
    if policy is BattleActionPolicyKind.FIRST_LEGAL:
        return OneOnOneActionPolicy.FIRST_LEGAL
    if policy is BattleActionPolicyKind.UNIFORM_RANDOM:
        return OneOnOneActionPolicy.UNIFORM_RANDOM_LEGAL_ACTION
    raise ValueError(f"unsupported fixed battle policy: {policy!r}")


def _idempotent_job_id(idempotency_key: str) -> str:
    """只由幂等键生成固定任务 ID，使同 key 不同请求稳定冲突。"""
    payload = json.dumps(
        [FIXED_ONE_ON_ONE_JOB_TYPE, idempotency_key],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()
    return f"{FIXED_ONE_ON_ONE_JOB_ID_PREFIX}{digest}"


__all__ = [
    "FIXED_ONE_ON_ONE_JOB_ID_PREFIX",
    "FIXED_ONE_ON_ONE_JOB_TYPE",
    "CreateFixedBattleInferenceJobUseCase",
    "SubmitFixedBattleJobCommand",
    "SubmittedFixedBattleJob",
]
