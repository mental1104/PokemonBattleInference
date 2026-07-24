"""验证后台任务 application 合同可被 fake repository 替换。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseDefinition,
    BattleInferenceCaseFilter,
    BattleInferenceCasePage,
    BattleInferenceCaseResult,
    BattleInferenceCaseSnapshot,
    BattleInferenceCaseStatus,
    BattleInferenceExpectedTurns,
    BattleInferenceExpectedTurnsKind,
    BattleInferenceFailureCode,
    BattleInferenceJobRepository,
    BattleInferenceJobSnapshot,
    BattleInferenceProbability,
    CreateBattleInferenceJob,
)


class _FakeBattleInferenceJobRepository:
    """记录 application 传入的任务，不依赖 SQLAlchemy 或 PostgreSQL。"""

    def __init__(self) -> None:
        """初始化空调用记录。"""
        self.created_commands: list[CreateBattleInferenceJob] = []

    def create_job(
        self,
        command: CreateBattleInferenceJob,
        *,
        created_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """记录任务创建命令，并返回测试预置快照。

        Args:
            command: application 生成的完整任务元数据。
            created_at: application 传入的创建时间。

        Returns:
            测试不读取的占位任务快照。
        """
        self.created_commands.append(command)
        return cast(BattleInferenceJobSnapshot, object())

    def get_job(
        self,
        job_id: str,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot:
        """表示 fake 可实现任务读取入口。"""
        raise NotImplementedError

    def claim_next_job(
        self,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        calculation_revision: str | None = None,
    ) -> BattleInferenceJobSnapshot | None:
        """表示 fake 可实现 coordinator 领取入口。"""
        raise NotImplementedError

    def heartbeat_job(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> BattleInferenceJobSnapshot:
        """表示 fake 可实现任务 heartbeat 入口。"""
        raise NotImplementedError

    def claim_cases(
        self,
        job_id: str,
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
        limit: int,
        calculation_revision: str,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """表示 fake 可实现 case 批量领取入口。"""
        raise NotImplementedError

    def heartbeat_cases(
        self,
        job_id: str,
        configuration_pair_ids: tuple[str, ...],
        *,
        lease_owner: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> tuple[BattleInferenceCaseSnapshot, ...]:
        """表示 fake 可实现 case heartbeat 入口。"""
        raise NotImplementedError

    def record_case_result(
        self,
        job_id: str,
        configuration_pair_id: str,
        result: BattleInferenceCaseResult,
        *,
        lease_owner: str,
        completed_at: datetime,
        calculation_revision: str,
    ) -> bool:
        """表示 fake 可实现幂等结果写入入口。"""
        raise NotImplementedError

    def request_cancel(
        self,
        job_id: str,
        *,
        requested_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """表示 fake 可实现取消请求入口。"""
        raise NotImplementedError

    def cancel_unclaimed_cases(
        self,
        job_id: str,
        *,
        cancelled_at: datetime,
    ) -> int:
        """表示 fake 可实现未领取 case 取消入口。"""
        raise NotImplementedError

    def finalize_job(
        self,
        job_id: str,
        *,
        completed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """表示 fake 可实现任务收口入口。"""
        raise NotImplementedError

    def fail_job(
        self,
        job_id: str,
        *,
        failure_code: BattleInferenceFailureCode,
        diagnostic: str,
        failed_at: datetime,
    ) -> BattleInferenceJobSnapshot:
        """表示 fake 可实现任务级失败入口。"""
        raise NotImplementedError

    def list_cases(
        self,
        job_id: str,
        query: BattleInferenceCaseFilter,
        *,
        calculation_revision: str | None = None,
    ) -> BattleInferenceCasePage:
        """表示 fake 可实现过滤分页入口。"""
        raise NotImplementedError


def _case(index: int) -> BattleInferenceCaseDefinition:
    """构造一个规范化、稳定 ID 唯一的配置对。

    Args:
        index: 用于生成唯一配置 ID 的非负序号。

    Returns:
        双方技能组均已升序去重的 case 定义。
    """
    return BattleInferenceCaseDefinition(
        configuration_pair_id=f"pair-{index:05d}",
        attacker_configuration_id=f"attacker-{index // 210:03d}",
        defender_configuration_id=f"defender-{index % 210:03d}",
        attacker_move_ids=(1, 2, 3, 4),
        defender_move_ids=(5, 6, 7, 8),
    )


def _submit_large_job(
    repository: BattleInferenceJobRepository,
    command: CreateBattleInferenceJob,
) -> None:
    """演示 application 只依赖 Protocol 提交大任务。

    Args:
        repository: 可由 fake 或 PostgreSQL 实现替换的 application port。
        command: 包含全部 case 元数据的任务命令。
    """
    repository.create_job(command, created_at=datetime(2026, 7, 25, tzinfo=UTC))


def test_application_accepts_fake_repository_with_44100_case_metadata() -> None:
    """44,100 个配置对可通过纯 application 合同提交，不需要数据库或完整图。"""
    command = CreateBattleInferenceJob(
        job_id="job-44100",
        ruleset_id="pokemon-champion",
        version_group_id=25,
        calculation_revision="battle-inference.v2",
        cases=tuple(_case(index) for index in range(44_100)),
    )
    repository = _FakeBattleInferenceJobRepository()

    assert isinstance(repository, BattleInferenceJobRepository)
    _submit_large_job(repository, command)

    assert repository.created_commands == [command]
    assert len(repository.created_commands[0].cases) == 44_100
    assert not hasattr(repository.created_commands[0].cases[0], "graph")


def test_probability_and_expected_turns_are_canonical_for_idempotent_results() -> None:
    """等价分数规范化后产生相同 fingerprint，避免重试被误判为冲突。"""
    first = BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.SUCCEEDED,
        attacker_win=BattleInferenceProbability(2, 4),
        defender_win=BattleInferenceProbability(1, 4),
        draw=BattleInferenceProbability(1, 4),
        expected_turns=BattleInferenceExpectedTurns(
            BattleInferenceExpectedTurnsKind.FINITE,
            numerator=6,
            denominator=4,
        ),
        node_count=12,
        edge_count=24,
        budget_consumed=36,
    )
    replay = BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.SUCCEEDED,
        attacker_win=BattleInferenceProbability(1, 2),
        defender_win=BattleInferenceProbability(1, 4),
        draw=BattleInferenceProbability(1, 4),
        expected_turns=BattleInferenceExpectedTurns(
            BattleInferenceExpectedTurnsKind.FINITE,
            numerator=3,
            denominator=2,
        ),
        node_count=12,
        edge_count=24,
        budget_consumed=36,
    )

    assert first.attacker_win == BattleInferenceProbability(1, 2)
    assert first.expected_turns == BattleInferenceExpectedTurns(
        BattleInferenceExpectedTurnsKind.FINITE,
        3,
        2,
    )
    assert first.fingerprint == replay.fingerprint


def test_failure_and_truncation_results_require_stable_code_and_diagnostic() -> None:
    """失败/截断不会携带伪概率，并且必须提供可查询诊断。"""
    truncated = BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.TRUNCATED,
        failure_code=BattleInferenceFailureCode.GRAPH_NODE_LIMIT,
        diagnostic="node limit 50000 reached",
        node_count=50_000,
        edge_count=91_000,
        budget_consumed=50_000,
    )

    assert truncated.failure_code is BattleInferenceFailureCode.GRAPH_NODE_LIMIT
    assert truncated.attacker_win is None
    with pytest.raises(ValueError, match="requires diagnostic"):
        BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.FAILED,
            failure_code=BattleInferenceFailureCode.SOLVER_UNRESOLVED,
        )


def test_move_sets_and_query_pagination_reject_unstable_input() -> None:
    """技能组身份与输入顺序无关，因此合同拒绝未排序或重复 move ID。"""
    with pytest.raises(ValueError, match="unique and sorted"):
        BattleInferenceCaseDefinition(
            configuration_pair_id="pair-invalid",
            attacker_configuration_id="attacker",
            defender_configuration_id="defender",
            attacker_move_ids=(2, 1),
            defender_move_ids=(5,),
        )
    with pytest.raises(ValueError, match="must not exceed 500"):
        BattleInferenceCaseFilter(limit=501)
