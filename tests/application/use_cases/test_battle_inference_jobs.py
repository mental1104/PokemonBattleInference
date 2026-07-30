"""验证后台任务创建、预算冻结和 canonical 配置恢复。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from pokeop.application.configuration_space.one_on_one import (
    FixedPokemonConfiguration,
    OneOnOneMovePoolCommand,
    PokemonMovePoolSelection,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseFilter,
    BattleInferenceCasePage,
    BattleInferenceCaseSnapshot,
    BattleInferenceCaseStatus,
    BattleInferenceJobAlreadyExists,
    BattleInferenceJobProgress,
    BattleInferenceJobSnapshot,
    BattleInferenceJobStatus,
    CreateBattleInferenceJob,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    BattleInferenceExecutionSpec,
    BattleInferenceRuntimeSnapshot,
    CreateBattleInferenceJobUseCase,
    SubmitBattleInferenceJobCommand,
    decode_one_on_one_configuration_id,
)
from pokeop.application.use_cases.fixed_battle_jobs import (
    CreateFixedBattleInferenceJobUseCase,
    SubmitFixedBattleJobCommand,
)
from pokeop.application.use_cases.fixed_battle_workflow import FixedBattleSideSelection
from pokeop.application.use_cases.infer_one_on_one_battle import BattleActionPolicyKind
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BATTLE_INFERENCE_CALCULATION_REVISION,
)


@dataclass(slots=True)
class _AcceptAllAdmission:
    """记录准入调用并接受测试命令。"""

    calls: list[OneOnOneMovePoolCommand] = field(default_factory=list)

    def validate(self, command: OneOnOneMovePoolCommand) -> None:
        """记录已完成结构校验的公开命令。"""
        self.calls.append(command)


@dataclass(slots=True)
class _CapturingStore:
    """捕获任务和执行规格，不依赖 PostgreSQL。"""

    command: CreateBattleInferenceJob | None = None
    execution_spec: BattleInferenceExecutionSpec | None = None

    def create_job_with_execution_spec(
        self,
        command: CreateBattleInferenceJob,
        execution_spec: BattleInferenceExecutionSpec,
        *,
        created_at: datetime,
    ) -> object:
        """保存创建参数并返回本测试不使用的占位对象。"""
        assert created_at.tzinfo is not None
        self.command = command
        self.execution_spec = execution_spec
        return object()


@dataclass(slots=True)
class _IdempotentStore:
    """模拟唯一约束并允许相同幂等提交读取既有任务。"""

    created: BattleInferenceRuntimeSnapshot | None = None
    command: CreateBattleInferenceJob | None = None
    create_calls: int = 0

    def create_job_with_execution_spec(
        self,
        command: CreateBattleInferenceJob,
        execution_spec: BattleInferenceExecutionSpec,
        *,
        created_at: datetime,
    ) -> BattleInferenceRuntimeSnapshot:
        """首次创建快照，后续相同 job ID 模拟数据库唯一冲突。"""
        self.create_calls += 1
        if self.created is not None:
            raise BattleInferenceJobAlreadyExists(command.job_id)
        self.command = command
        job = BattleInferenceJobSnapshot(
            job_id=command.job_id,
            ruleset_id=command.ruleset_id,
            version_group_id=command.version_group_id,
            calculation_revision=command.calculation_revision,
            status=BattleInferenceJobStatus.PENDING,
            attempt_count=0,
            progress=BattleInferenceJobProgress(
                total_count=len(command.cases),
                pending_count=len(command.cases),
                running_count=0,
                succeeded_count=0,
                failed_count=0,
                truncated_count=0,
                cancelled_count=0,
                cumulative_node_count=0,
                cumulative_edge_count=0,
                budget_consumed=0,
            ),
            lease=None,
            last_failure_code=None,
            last_failure_diagnostic=None,
            created_at=created_at,
            updated_at=created_at,
            started_at=None,
            completed_at=None,
            cancel_requested_at=None,
        )
        self.created = BattleInferenceRuntimeSnapshot(
            job=job,
            execution_spec=execution_spec,
        )
        return self.created

    def get_job(
        self,
        job_id: str,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot:
        """返回首次创建的任务快照。"""
        assert self.created is not None
        assert self.created.job.job_id == job_id
        assert calculation_revision in {None, self.created.job.calculation_revision}
        return self.created.job

    def get_execution_spec(self, job_id: str) -> BattleInferenceExecutionSpec:
        """返回首次创建的冻结执行规格。"""
        assert self.created is not None
        assert self.created.job.job_id == job_id
        return self.created.execution_spec

    def list_cases(
        self,
        job_id: str,
        query: BattleInferenceCaseFilter,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceCasePage:
        """返回首次创建任务的稳定 case 快照页。"""
        assert self.created is not None
        assert self.command is not None
        assert self.created.job.job_id == job_id
        cases = tuple(
            BattleInferenceCaseSnapshot(
                job_id=job_id,
                sequence_no=sequence_no,
                definition=definition,
                status=BattleInferenceCaseStatus.PENDING,
                attempt_count=0,
                lease=None,
                attacker_win=None,
                defender_win=None,
                draw=None,
                expected_turns=None,
                node_count=0,
                edge_count=0,
                progress_phase=None,
                observed_node_count=0,
                observed_edge_count=0,
                expanded_node_count=0,
                frontier_count=0,
                action_pair_completed_count=0,
                action_pair_total_count=0,
                budget_consumed=0,
                failure_code=None,
                diagnostic=None,
                last_failure_code=None,
                last_failure_diagnostic=None,
                created_at=self.created.job.created_at,
                updated_at=self.created.job.created_at,
                started_at=None,
                completed_at=None,
            )
            for sequence_no, definition in enumerate(self.command.cases)
        )
        return BattleInferenceCasePage(
            items=cases[query.offset : query.offset + query.limit],
            total_count=len(cases),
            offset=query.offset,
            limit=query.limit,
        )


def _fixed(pokemon_id: int) -> FixedPokemonConfiguration:
    """创建能够参与 v1 canonical 身份计算的固定配置。"""
    return FixedPokemonConfiguration(
        pokemon_id=pokemon_id,
        form_id=None,
        level=50,
        stat_profile_id="max_atk_plus",
        ability_identifier="none",
        item_identifier=None,
    )


def _move_pool_command() -> OneOnOneMovePoolCommand:
    """创建 5 × 5 候选池，对应 25 个四招配置对。"""
    return OneOnOneMovePoolCommand(
        ruleset_id="pokemon-champion",
        version_group_id=31,
        calculation_revision=BATTLE_INFERENCE_CALCULATION_REVISION,
        attacker=PokemonMovePoolSelection(
            fixed=_fixed(149),
            candidate_move_ids=(5, 4, 3, 2, 1),
        ),
        defender=PokemonMovePoolSelection(
            fixed=_fixed(461),
            candidate_move_ids=(15, 14, 13, 12, 11),
        ),
    )


def test_create_job_freezes_budget_and_enumerates_canonical_cases() -> None:
    """创建任务应立即持久化全部轻量身份，不执行任何状态图。"""
    store = _CapturingStore()
    admission = _AcceptAllAdmission()
    move_pool = _move_pool_command()
    execution_spec = BattleInferenceExecutionSpec.from_command(
        move_pool,
        process_count=2,
        queue_depth=3,
        max_nodes_per_pair=123,
        max_edges_per_pair=456,
        max_turns=9,
    )
    created_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    submitted = CreateBattleInferenceJobUseCase(
        store=store,  # type: ignore[arg-type]
        admission_validator=admission,
    ).execute(
        SubmitBattleInferenceJobCommand(
            move_pool=move_pool,
            execution_spec=execution_spec,
            job_id="job-87",
        ),
        created_at=created_at,
    )

    assert submitted.job_id == "job-87"
    assert submitted.submitted_configuration_pairs == 25
    assert admission.calls == [move_pool]
    assert store.execution_spec == execution_spec
    assert store.command is not None
    assert len(store.command.cases) == 25
    assert len({case.configuration_pair_id for case in store.command.cases}) == 25

    first = store.command.cases[0]
    decoded = decode_one_on_one_configuration_id(first.configuration_pair_id)
    assert decoded.attacker.pokemon_id == 149
    assert decoded.defender.pokemon_id == 461
    assert decoded.attacker_move_ids == first.attacker_move_ids
    assert decoded.defender_move_ids == first.defender_move_ids


def test_execution_spec_rejects_queue_smaller_than_process_count() -> None:
    """队列深度不得小于子进程数，避免配置看似并发但无法填满进程池。"""
    with pytest.raises(ValueError, match="queue_depth"):
        BattleInferenceExecutionSpec.from_command(
            _move_pool_command(),
            process_count=4,
            queue_depth=2,
        )


def test_decode_rejects_noncanonical_configuration_id() -> None:
    """worker 不得接受调用方伪造的非 v1 配置身份。"""
    with pytest.raises(ValueError, match="canonical prefix"):
        decode_one_on_one_configuration_id("not-a-configuration")


def test_idempotency_key_reuses_the_same_persisted_job() -> None:
    """相同幂等键和完整输入重复提交时不得创建第二组配置结果。"""
    store = _IdempotentStore()
    move_pool = _move_pool_command()
    use_case = CreateBattleInferenceJobUseCase(
        store=store,  # type: ignore[arg-type]
        admission_validator=_AcceptAllAdmission(),
    )
    command = SubmitBattleInferenceJobCommand(
        move_pool=move_pool,
        execution_spec=BattleInferenceExecutionSpec.from_command(move_pool),
        idempotency_key="request-87",
    )
    created_at = datetime(2026, 7, 25, tzinfo=timezone.utc)

    first = use_case.execute(command, created_at=created_at)
    second = use_case.execute(command, created_at=created_at)

    assert first == second
    assert first.job_id.startswith("battle-inference-idempotent-")
    assert store.create_calls == 2
    assert store.created is not None
    assert store.created.job.progress.total_count == 25


def test_fixed_battle_job_creates_one_recoverable_case() -> None:
    """固定配置任务必须退化为一个后台 case，而不是重新执行同步 solver。

    用户在页面已经从左右技能组中各选定唯一一组招式；创建固定任务时 application 只应
    执行严格准入、冻结预算和持久化单个 canonical 配置身份。该测试保护 504 修复的核心
    产品边界：HTTP 创建入口立即返回 job，不在请求线程构建状态图。
    """
    store = _IdempotentStore()
    created_at = datetime(2026, 7, 30, tzinfo=timezone.utc)

    submitted = CreateFixedBattleInferenceJobUseCase(
        store=store,  # type: ignore[arg-type]
        create_job_use_case=CreateBattleInferenceJobUseCase(
            store=store,  # type: ignore[arg-type]
            admission_validator=_AcceptAllAdmission(),
        ),
    ).execute(
        SubmitFixedBattleJobCommand(
            ruleset_id="pokemon-champion",
            version_group_id=25,
            attacker=FixedBattleSideSelection(
                pokemon_id=149,
                form_id=None,
                level=50,
                stat_profile_id="max_atk_plus",
                ability_identifier="multiscale",
            ),
            attacker_move_ids=(337,),
            defender=FixedBattleSideSelection(
                pokemon_id=149,
                form_id=None,
                level=50,
                stat_profile_id="max_hp",
                ability_identifier="multiscale",
            ),
            defender_move_ids=(337,),
            attacker_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
            defender_policy=BattleActionPolicyKind.UNIFORM_RANDOM,
            max_nodes=50_000,
            max_edges=300_000,
            max_turns=20,
            idempotency_key="fixed-dragonite-dragon-claw",
        ),
        created_at=created_at,
    )

    assert submitted.submitted_configuration_pairs == 1
    assert submitted.job.status is BattleInferenceJobStatus.PENDING
    assert store.command is not None
    assert len(store.command.cases) == 1
    assert store.created is not None
    assert store.created.execution_spec.process_count == 1
    assert store.created.execution_spec.queue_depth == 1
    assert store.created.execution_spec.max_nodes_per_pair == 50_000
    assert store.created.execution_spec.max_edges_per_pair == 300_000
    case = store.command.cases[0]
    assert case.attacker_move_ids == (337,)
    assert case.defender_move_ids == (337,)


def test_submit_rejects_explicit_form_before_worker_execution() -> None:
    """当前 worker 未支持 form_id 时必须在创建阶段明确拒绝整批任务。"""
    move_pool = _move_pool_command()
    attacker = PokemonMovePoolSelection(
        fixed=FixedPokemonConfiguration(
            pokemon_id=149,
            form_id=10001,
            level=50,
            stat_profile_id="max_atk_plus",
            ability_identifier="none",
            item_identifier=None,
        ),
        candidate_move_ids=move_pool.attacker.candidate_move_ids,
    )
    with pytest.raises(ValueError, match="form_id"):
        SubmitBattleInferenceJobCommand(
            move_pool=OneOnOneMovePoolCommand(
                ruleset_id=move_pool.ruleset_id,
                version_group_id=move_pool.version_group_id,
                calculation_revision=move_pool.calculation_revision,
                attacker=attacker,
                defender=move_pool.defender,
            ),
            execution_spec=BattleInferenceExecutionSpec.from_command(move_pool),
        )
