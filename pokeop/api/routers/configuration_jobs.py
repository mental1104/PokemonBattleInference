"""暴露战斗推演后台任务创建、轮询、分页、取消和按需图入口。"""

from fastapi import APIRouter

from pokeop.api.routers._configuration_jobs.lifecycle import router as lifecycle_router
from pokeop.api.routers._configuration_jobs.results import router as results_router

router = APIRouter()
router.include_router(lifecycle_router)
router.include_router(results_router)

ROUTE_PREFIX_OVERRIDE = "/v1/inference"

__all__ = ["ROUTE_PREFIX_OVERRIDE", "router"]
