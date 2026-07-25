"""组合后台任务路由依赖并统一异常映射。"""

from __future__ import annotations

from typing import Annotated, NoReturn

from fastapi import Depends, HTTPException, Request

from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.battle_candidate_pool.admission import (
    ValidateFixedMechanismSelectionUseCase,
)
from pokeop.application.battle_candidate_pool.listing import (
    ListBattleCandidatePoolUseCase,
)
from pokeop.application.composition.battle_inference_repository import (
    FactoryReconciledBattleInferenceRepository,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceJobNotFound,
)
from pokeop.application.use_cases.battle_inference_jobs import (
    CreateBattleInferenceJobUseCase,
    StrictBattleInferenceAdmissionValidator,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    InferOneOnOneBattleUseCase,
)
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)
from pokeop.persistence.battle_inference.runtime_repository import (
    BattleInferenceExecutionSpecNotFound,
    PostgresBattleInferenceJobStore,
)


def job_store() -> PostgresBattleInferenceJobStore:
    """创建无状态 PostgreSQL 任务 store dependency。"""
    return PostgresBattleInferenceJobStore()


def graph_store(request: Request) -> BattleGraphStore:
    """读取 backend 进程生命周期共享的完整图 store。"""
    value = getattr(request.app.state, "battle_graph_store", None)
    if not isinstance(value, BattleGraphStore):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "battle_graph_store_unavailable",
                "message": "battle graph store is not available",
            },
        )
    return value


JobStoreDependency = Annotated[PostgresBattleInferenceJobStore, Depends(job_store)]
GraphStoreDependency = Annotated[BattleGraphStore, Depends(graph_store)]


def inference_use_case() -> InferOneOnOneBattleUseCase:
    """创建与现有固定推演入口一致的 repository/effect composition。"""
    effect_factory = TransparentPokemonChampionEffectFactory()
    repository = FactoryReconciledBattleInferenceRepository(
        repository=MaterializedViewBattleInferenceRepository(),
        effect_factory=effect_factory,
    )
    return InferOneOnOneBattleUseCase(
        repository=repository,
        effect_factory=effect_factory,
    )


def candidate_pool_use_case() -> ListBattleCandidatePoolUseCase:
    """创建与任务准入共享 repository 和 effect factory 的候选池用例。"""
    inference = inference_use_case()
    return ListBattleCandidatePoolUseCase(
        repository=inference.repository,
        effect_factory=inference.effect_factory,
    )


CandidatePoolDependency = Annotated[
    ListBattleCandidatePoolUseCase,
    Depends(candidate_pool_use_case),
]


def create_use_case(
    store: PostgresBattleInferenceJobStore,
) -> CreateBattleInferenceJobUseCase:
    """组合严格候选准入与持久化任务创建用例。"""
    inference = inference_use_case()
    admission = StrictBattleInferenceAdmissionValidator(
        ValidateFixedMechanismSelectionUseCase(
            inference.repository,
            inference.effect_factory,
        )
    )
    return CreateBattleInferenceJobUseCase(
        store=store,
        admission_validator=admission,
    )


def raise_job_http_error(error: Exception) -> NoReturn:
    """把任务 store 和输入异常映射为稳定 HTTP 语义。"""
    if isinstance(error, (BattleInferenceJobNotFound, BattleInferenceExecutionSpecNotFound)):
        status_code, code = 404, "battle_inference_job_not_found"
    elif isinstance(error, ValueError):
        status_code, code = 422, "battle_inference_job_invalid_request"
    else:
        status_code, code = 409, "battle_inference_job_conflict"
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": str(error)},
    ) from error
