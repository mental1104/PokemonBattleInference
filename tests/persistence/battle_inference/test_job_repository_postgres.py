"""使用真实 PostgreSQL 验证任务竞争领取、租约恢复和幂等进度。"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCalculationRevisionMismatch,
    BattleInferenceCaseDefinition,
    BattleInferenceCaseFilter,
    BattleInferenceCaseResult,
    BattleInferenceCaseStatus,
    BattleInferenceExpectedTurns,
    BattleInferenceExpectedTurnsKind,
    BattleInferenceFailureCode,
    BattleInferenceJobStatus,
    BattleInferenceProbability,
    CreateBattleInferenceJob,
)
from pokeop.persistence.battle_inference.job_repository import (
    PostgresBattleInferenceJobRepository,
    TransactionFactory,
)
from pokeop.persistence.runtime_schema import create_runtime_tables


_POSTGRES_URL = os.environ.get("POKEOP_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not _POSTGRES_URL,
    reason="set POKEOP_TEST_POSTGRES_URL to run PostgreSQL integration tests",
)


def _case(index: int) -> BattleInferenceCaseDefinition:
    """构造 PostgreSQL 集成测试使用的唯一配置对。

    Args:
        index: 任务内 case 序号。

    Returns:
        带双方稳定配置 ID 和规范化技能组的 case 定义。
    """
    return BattleInferenceCaseDefinition(
        configuration_pair_id=f"pair-{index:05d}",
        attacker_configuration_id=f"attacker-{index // 10:03d}",
        defender_configuration_id=f"defender-{index % 10:03d}",
        attacker_move_ids=(1, 2, 3, 4),
        defender_move_ids=(5, 6, 7, 8),
    )


def _command(job_id: str, case_count: int) -> CreateBattleInferenceJob:
    """构造指定规模的后台任务命令。

    Args:
        job_id: 本测试使用的唯一任务 ID。
        case_count: 需要生成的配置对数量。

    Returns:
        calculation revision 固定为 ``battle-inference.v2`` 的任务命令。
    """
    return CreateBattleInferenceJob(
        job_id=job_id,
        ruleset_id="pokemon-champion",
        version_group_id=25,
        calculation_revision="battle-inference.v2",
        cases=tuple(_case(index) for index in range(case_count)),
    )


@pytest.fixture(scope="module")
def postgres_engine() -> Iterator[Engine]:
    """创建隔离的 poke_runtime schema，并在模块结束后清理。

    Yields:
        可被多个并发 Session 共享的 SQLAlchemy PostgreSQL engine。
    """
    assert _POSTGRES_URL is not None
    engine = create_engine(_POSTGRES_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS poke_runtime CASCADE"))
    create_runtime_tables(engine)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS poke_runtime CASCADE"))
        engine.dispose()


@pytest.fixture
def transaction_factory(postgres_engine: Engine) -> TransactionFactory:
    """为每次 repository 调用提供独立提交/回滚事务。

    Args:
        postgres_engine: 模块级真实 PostgreSQL engine。

    Returns:
        可注入 ``PostgresBattleInferenceJobRepository`` 的事务工厂。
    """

    @contextmanager
    def factory() -> Iterator[Session]:
        """打开一个 Session，并将 repository 调用包裹在单一事务中。

        Yields:
            当前调用独占的 SQLAlchemy Session。
        """
        with Session(postgres_engine) as session:
            with session.begin():
                yield session

    return factory


def test_creates_and_pages_44100_case_metadata(
    transaction_factory: TransactionFactory,
) -> None:
    """真实 PostgreSQL 可批量保存 44,100 个 case 元数据且不持久化完整图。"""
    repository = PostgresBattleInferenceJobRepository(
        transaction_factory,
        insert_batch_size=2000,
    )
    created_at = datetime(2026, 7, 25, 1, 0, tzinfo=UTC)

    snapshot = repository.create_job(
        _command("job-44100-postgres", 44_100),
        created_at=created_at,
    )
    last_page = repository.list_cases(
        snapshot.job_id,
        BattleInferenceCaseFilter(offset=44_050, limit=50),
        calculation_revision="battle-inference.v2",
    )

    assert snapshot.progress.total_count == 44_100
    assert snapshot.progress.pending_count == 44_100
    assert last_page.total_count == 44_100
    assert len(last_page.items) == 50
    assert last_page.items[0].sequence_no == 44_050
    assert last_page.items[-1].sequence_no == 44_099


def test_two_workers_claim_disjoint_batches_and_results_are_idempotent(
    transaction_factory: TransactionFactory,
) -> None:
    """SKIP LOCKED 防止有效 lease 重复拥有，终态重放不会重复累计 progress。"""
    repository = PostgresBattleInferenceJobRepository(transaction_factory)
    now = datetime(2026, 7, 25, 2, 0, tzinfo=UTC)
    repository.create_job(_command("job-concurrent", 6), created_at=now)
    repository.claim_next_job(
        lease_owner="coordinator",
        now=now,
        lease_duration=timedelta(minutes=10),
    )
    barrier = Barrier(2)

    def claim(owner: str) -> tuple[str, ...]:
        """让两个线程同时尝试领取三个 case。

        Args:
            owner: 当前线程模拟的 worker 标识。

        Returns:
            当前 worker 实际领取的配置对 ID。
        """
        barrier.wait()
        claimed = repository.claim_cases(
            "job-concurrent",
            lease_owner=owner,
            now=now,
            lease_duration=timedelta(minutes=5),
            limit=3,
            calculation_revision="battle-inference.v2",
        )
        return tuple(case.definition.configuration_pair_id for case in claimed)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(claim, "worker-a")
        second_future = executor.submit(claim, "worker-b")
        first = first_future.result()
        second = second_future.result()

    assert len(first) == len(second) == 3
    assert set(first).isdisjoint(second)
    assert set(first) | set(second) == {f"pair-{index:05d}" for index in range(6)}

    result = BattleInferenceCaseResult(
        status=BattleInferenceCaseStatus.SUCCEEDED,
        attacker_win=BattleInferenceProbability(1, 2),
        defender_win=BattleInferenceProbability(1, 4),
        draw=BattleInferenceProbability(1, 4),
        expected_turns=BattleInferenceExpectedTurns(
            BattleInferenceExpectedTurnsKind.FINITE,
            3,
            2,
        ),
        node_count=10,
        edge_count=20,
        budget_consumed=30,
    )
    owner_by_pair = {pair_id: "worker-a" for pair_id in first} | {
        pair_id: "worker-b" for pair_id in second
    }
    for pair_id, owner in owner_by_pair.items():
        assert repository.record_case_result(
            "job-concurrent",
            pair_id,
            result,
            lease_owner=owner,
            completed_at=now + timedelta(minutes=1),
            calculation_revision="battle-inference.v2",
        )
    replay_pair = first[0]
    assert not repository.record_case_result(
        "job-concurrent",
        replay_pair,
        result,
        lease_owner="worker-a",
        completed_at=now + timedelta(minutes=2),
        calculation_revision="battle-inference.v2",
    )

    snapshot = repository.get_job("job-concurrent")
    assert snapshot.progress.running_count == 0
    assert snapshot.progress.succeeded_count == 6
    assert snapshot.progress.cumulative_node_count == 60
    assert snapshot.progress.cumulative_edge_count == 120
    assert snapshot.progress.budget_consumed == 180
    assert repository.finalize_job(
        "job-concurrent",
        completed_at=now + timedelta(minutes=3),
    ).status is BattleInferenceJobStatus.SUCCEEDED


def test_expired_case_reclaim_records_worker_crash_without_double_counting(
    transaction_factory: TransactionFactory,
) -> None:
    """过期 RUNNING case 可重新领取，running 桶保持不变且记录恢复诊断。"""
    repository = PostgresBattleInferenceJobRepository(transaction_factory)
    now = datetime(2026, 7, 25, 3, 0, tzinfo=UTC)
    repository.create_job(_command("job-reclaim", 2), created_at=now)
    repository.claim_next_job(
        lease_owner="coordinator",
        now=now,
        lease_duration=timedelta(minutes=10),
    )
    first = repository.claim_cases(
        "job-reclaim",
        lease_owner="worker-a",
        now=now,
        lease_duration=timedelta(minutes=1),
        limit=1,
        calculation_revision="battle-inference.v2",
    )[0]
    reclaimed = repository.claim_cases(
        "job-reclaim",
        lease_owner="worker-b",
        now=now + timedelta(minutes=2),
        lease_duration=timedelta(minutes=5),
        limit=1,
        calculation_revision="battle-inference.v2",
    )[0]
    progress = repository.get_job("job-reclaim").progress

    assert reclaimed.definition.configuration_pair_id == first.definition.configuration_pair_id
    assert reclaimed.attempt_count == 2
    assert reclaimed.lease is not None and reclaimed.lease.owner == "worker-b"
    assert reclaimed.last_failure_code is BattleInferenceFailureCode.WORKER_CRASH
    assert progress.pending_count == 1
    assert progress.running_count == 1
    with pytest.raises(BattleInferenceCalculationRevisionMismatch):
        repository.list_cases(
            "job-reclaim",
            BattleInferenceCaseFilter(),
            calculation_revision="battle-inference.v3",
        )


def test_failure_truncation_filters_and_cancellation_preserve_completed_rows(
    transaction_factory: TransactionFactory,
) -> None:
    """失败/截断详情可过滤分页，取消只终止未完成 case 并保留已有结果。"""
    repository = PostgresBattleInferenceJobRepository(transaction_factory)
    now = datetime(2026, 7, 25, 4, 0, tzinfo=UTC)
    repository.create_job(_command("job-mixed", 4), created_at=now)
    repository.claim_next_job(
        lease_owner="coordinator",
        now=now,
        lease_duration=timedelta(minutes=10),
    )
    claimed = repository.claim_cases(
        "job-mixed",
        lease_owner="worker",
        now=now,
        lease_duration=timedelta(minutes=10),
        limit=2,
        calculation_revision="battle-inference.v2",
    )
    repository.record_case_result(
        "job-mixed",
        claimed[0].definition.configuration_pair_id,
        BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.FAILED,
            failure_code=BattleInferenceFailureCode.SOLVER_UNRESOLVED,
            diagnostic="singular absorption system",
            node_count=30,
            edge_count=60,
            budget_consumed=90,
        ),
        lease_owner="worker",
        completed_at=now + timedelta(minutes=1),
        calculation_revision="battle-inference.v2",
    )
    repository.record_case_result(
        "job-mixed",
        claimed[1].definition.configuration_pair_id,
        BattleInferenceCaseResult(
            status=BattleInferenceCaseStatus.TRUNCATED,
            failure_code=BattleInferenceFailureCode.GRAPH_EDGE_LIMIT,
            diagnostic="edge limit 100000 reached",
            node_count=45_000,
            edge_count=100_000,
            budget_consumed=100_000,
        ),
        lease_owner="worker",
        completed_at=now + timedelta(minutes=1),
        calculation_revision="battle-inference.v2",
    )
    repository.request_cancel("job-mixed", requested_at=now + timedelta(minutes=2))
    assert repository.cancel_unclaimed_cases(
        "job-mixed",
        cancelled_at=now + timedelta(minutes=2),
    ) == 2

    failures = repository.list_cases(
        "job-mixed",
        BattleInferenceCaseFilter(
            statuses=(
                BattleInferenceCaseStatus.FAILED,
                BattleInferenceCaseStatus.TRUNCATED,
            ),
            failure_codes=(
                BattleInferenceFailureCode.SOLVER_UNRESOLVED,
                BattleInferenceFailureCode.GRAPH_EDGE_LIMIT,
            ),
            limit=10,
        ),
    )
    cancelled = repository.list_cases(
        "job-mixed",
        BattleInferenceCaseFilter(
            statuses=(BattleInferenceCaseStatus.CANCELLED,),
            failure_codes=(BattleInferenceFailureCode.CANCELLED,),
            limit=10,
        ),
    )
    final = repository.finalize_job(
        "job-mixed",
        completed_at=now + timedelta(minutes=3),
    )

    assert failures.total_count == 2
    assert failures.items[0].definition.attacker_move_ids == (1, 2, 3, 4)
    assert failures.items[0].failure_code is BattleInferenceFailureCode.SOLVER_UNRESOLVED
    assert failures.items[1].edge_count == 100_000
    assert failures.items[1].diagnostic == "edge limit 100000 reached"
    assert cancelled.total_count == 2
    assert final.status is BattleInferenceJobStatus.CANCELLED
    assert final.progress.failed_count == 1
    assert final.progress.truncated_count == 1
    assert final.progress.cancelled_count == 2


def test_coordinators_compete_for_job_and_expired_lease_is_reclaimed(
    transaction_factory: TransactionFactory,
) -> None:
    """同一有效 job lease 只有一个 owner，过期后其他 coordinator 可恢复任务。"""
    repository = PostgresBattleInferenceJobRepository(transaction_factory)
    now = datetime(2026, 7, 25, 5, 0, tzinfo=UTC)
    repository.create_job(_command("job-coordinator-reclaim", 1), created_at=now)
    barrier = Barrier(2)

    def claim(owner: str):
        """让两个 coordinator 同时竞争唯一 PENDING 任务。

        Args:
            owner: 当前线程模拟的 coordinator 标识。

        Returns:
            成功领取的任务快照；未领取时返回 None。
        """
        barrier.wait()
        return repository.claim_next_job(
            lease_owner=owner,
            now=now,
            lease_duration=timedelta(minutes=1),
            calculation_revision="battle-inference.v2",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim, "coordinator-a")
        second = executor.submit(claim, "coordinator-b")
        snapshots = (first.result(), second.result())

    claimed = [snapshot for snapshot in snapshots if snapshot is not None]
    assert len(claimed) == 1
    assert claimed[0].lease is not None
    original_owner = claimed[0].lease.owner
    recovery_owner = (
        "coordinator-b" if original_owner == "coordinator-a" else "coordinator-a"
    )
    recovered = repository.claim_next_job(
        lease_owner=recovery_owner,
        now=now + timedelta(minutes=2),
        lease_duration=timedelta(minutes=5),
        calculation_revision="battle-inference.v2",
    )

    assert recovered is not None
    assert recovered.attempt_count == 2
    assert recovered.lease is not None and recovered.lease.owner == recovery_owner
    assert recovered.last_failure_code is BattleInferenceFailureCode.WORKER_CRASH
