"""验证后台任务 router 可以复用 `/v1/inference` 公共前缀。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI

from pokeop.main import include_router
from pokeop.api.routers import jobs


def test_include_router_uses_explicit_prefix_override() -> None:
    """验证显式前缀覆盖在当前 FastAPI 路由包装结构下仍可检查。

    后台任务模块必须复用 `/v1/inference` 资源前缀，而不是根据私有目录名暴露
    `/v1/configuration_jobs`。测试展开 FastAPI 的 included router 包装对象，保护
    新增固定任务和通用任务入口继续挂在同一个 inference 产品资源下。
    """
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

    registered_paths: set[str] = set()
    for route in application.routes:
        prefix = getattr(getattr(route, "include_context", None), "prefix", "")
        nested_router = getattr(route, "original_router", None)
        candidates = getattr(nested_router, "routes", None) or (route,)
        for candidate in candidates:
            registered_paths.add(f"{prefix}{getattr(candidate, 'path', '')}")

    assert "/v1/inference/configuration-jobs" in registered_paths


def test_generic_inference_job_routes_share_inference_prefix() -> None:
    """验证通用任务查看入口不会被文件名注册到错误资源。

    固定配置任务创建响应中的链接指向 `/v1/inference/jobs/{job_id}`，因此通用任务
    router 必须显式覆盖动态扫描默认前缀。该测试保护列表、详情和取消三个路径同时
    属于 inference 产品资源，前端任务面板才能用同一 API 家族轮询状态。
    """
    assert jobs.ROUTE_PREFIX_OVERRIDE == "/v1/inference"
    paths = {route.path for route in jobs.router.routes}

    assert "/jobs" in paths
    assert "/jobs/{job_id}" in paths
    assert "/jobs/{job_id}/cancel" in paths
