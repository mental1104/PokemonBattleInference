"""验证后台任务 router 可以复用 `/v1/inference` 公共前缀。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI

from pokeop.main import include_router


def test_include_router_uses_explicit_prefix_override() -> None:
    """新模块文件名不得把公开 URL 错误扩张为 `/configuration_jobs`。"""
    router = APIRouter()

    @router.get("/configuration-jobs")
    def list_jobs() -> dict[str, bool]:
        """返回测试占位响应。"""
        return {"ok": True}

    application = FastAPI()
    include_router(
        application,
        SimpleNamespace(
            router=router,
            ROUTE_PREFIX_OVERRIDE="/v1/inference",
        ),
        "/v1/configuration_jobs",
    )

    assert "/v1/inference/configuration-jobs" in {
        route.path for route in application.routes
    }
