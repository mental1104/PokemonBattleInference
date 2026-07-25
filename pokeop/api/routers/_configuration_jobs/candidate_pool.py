"""暴露通用配置页使用的真实 version-group-aware 候选池。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from pokeop.api.routers._configuration_jobs.dependencies import CandidatePoolDependency
from pokeop.api.schemas.battle_candidate_pool import (
    BattleCandidatePoolResponse,
    battle_candidate_pool_response,
)
from pokeop.application.battle_candidate_pool.listing import (
    BattleCandidatePoolNotFound,
    ListBattleCandidatePoolCommand,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules


router = APIRouter()


@router.get(
    "/candidate-pools/{pokemon_id}",
    response_model=BattleCandidatePoolResponse,
    summary="读取指定 version group 的真实战斗候选招式池",
)
def list_battle_candidate_pool(
    pokemon_id: int,
    use_case: CandidatePoolDependency,
    ruleset_id: str = Query(min_length=1),
    version_group_id: int = Query(gt=0),
) -> BattleCandidatePoolResponse:
    """复用 application 候选池用例，保留未支持机制但禁止其进入任务。"""
    try:
        pool = use_case.execute(
            ListBattleCandidatePoolCommand(
                rules=BattleInferenceRules(
                    ruleset_id=ruleset_id,
                    version_group_id=version_group_id,
                ),
                pokemon_id=pokemon_id,
            )
        )
    except BattleCandidatePoolNotFound as error:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "battle_candidate_pool_not_found",
                "message": str(error),
            },
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "battle_candidate_pool_invalid_request",
                "message": str(error),
            },
        ) from error
    return battle_candidate_pool_response(pool)
