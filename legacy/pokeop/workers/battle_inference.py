"""启动独立战斗推演 coordinator 与受控子进程池。"""

from __future__ import annotations

import os
from datetime import timedelta

from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    InferOneOnOneBattleUseCase,
)
from pokeop.application.use_cases.run_battle_inference_worker import (
    RepositoryBackedBattleInferenceCasePreparer,
    RunBattleInferenceWorkerUseCase,
    default_worker_id,
)
from pokeop.infrastructure.logging import configure_logging
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)
from pokeop.persistence.battle_inference.runtime_repository import (
    PostgresBattleInferenceJobStore,
)
from pokeop.persistence.bootstrap import register_postgres_runtime


def _positive_float(name: str, default: float) -> float:
    """读取一个大于零的 worker 浮点环境变量。

    Args:
        name: 环境变量名。
        default: 未设置时使用的安全默认值。

    Returns:
        可直接转换为秒数的正浮点数。

    Raises:
        ValueError: 环境变量不是大于零的数字时抛出。
    """
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return value


def build_worker() -> RunBattleInferenceWorkerUseCase:
    """组合独立 worker 所需的 repository、准备器和租约参数。

    Returns:
        不依赖 FastAPI 生命周期、可持续领取 PostgreSQL 任务的 coordinator。
    """
    register_postgres_runtime()
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=MaterializedViewBattleInferenceRepository(),
        effect_factory=effect_factory,
    )
    inference = InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )
    lease_seconds = _positive_float("POKEOP_WORKER_LEASE_SECONDS", 120.0)
    heartbeat_seconds = _positive_float("POKEOP_WORKER_HEARTBEAT_SECONDS", 20.0)
    cancellation_grace_seconds = _positive_float(
        "POKEOP_WORKER_CANCELLATION_GRACE_SECONDS",
        5.0,
    )
    return RunBattleInferenceWorkerUseCase(
        store=PostgresBattleInferenceJobStore(),
        preparer=RepositoryBackedBattleInferenceCasePreparer(inference),
        worker_id=os.getenv("POKEOP_WORKER_ID", default_worker_id()),
        lease_duration=timedelta(seconds=lease_seconds),
        heartbeat_interval=timedelta(seconds=heartbeat_seconds),
        cancellation_grace=timedelta(seconds=cancellation_grace_seconds),
        poll_interval_seconds=_positive_float(
            "POKEOP_WORKER_ACTIVE_POLL_SECONDS",
            0.1,
        ),
    )


def main() -> None:
    """启动长期运行的战斗推演 worker 进程。"""
    configure_logging(os.getenv("POKEOP_LOG_LEVEL", "INFO"))
    build_worker().run_forever(
        idle_sleep_seconds=_positive_float(
            "POKEOP_WORKER_IDLE_POLL_SECONDS",
            1.0,
        )
    )


if __name__ == "__main__":
    main()
