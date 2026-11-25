"""暴露战斗推演候选池、后台任务和按需图入口。"""

from fastapi import APIRouter

from pokeop.api.routers._configuration_jobs.candidate_pool import (
    router as candidate_pool_router,
)
from pokeop.api.routers._configuration_jobs.lifecycle import router as lifecycle_router
from pokeop.api.routers._configuration_jobs.results import router as results_router


router = APIRouter()
router.include_router(candidate_pool_router)
router.include_router(lifecycle_router)
router.include_router(results_router)

ROUTE_PREFIX_OVERRIDE = "/v1/inference"

__all__ = ["ROUTE_PREFIX_OVERRIDE", "router"]
