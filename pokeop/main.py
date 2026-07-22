from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pokeop.infrastructure.logging import configure_logging

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "assets_static"
ROUTER_DIR = BASE_DIR / "api" / "routers"
ROUTER_PACKAGE = "pokeop.api.routers"
COMMON_PREFIX = "/v1"


@asynccontextmanager
async def lifespan(application: FastAPI):
    """FastAPI 生命周期入口，启动时幂等准备 raw 数据和 calculator 物化视图。"""
    from pokeop.persistence.bootstrap import init_db

    init_db(create_tables=True, import_csv=True, create_materialized_views=True)
    yield


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册静态资源、路由、文档和异常处理器。"""
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        title="Blue Espeon",
        description="Blue Espeon's little httpserver",
        version="0.0.1",
        lifespan=lifespan,
    )

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_routes(ROUTER_DIR, ROUTER_PACKAGE, COMMON_PREFIX, application)
    register_documentation(application)
    register_exception_handlers(application)
    return application


def include_router(application: FastAPI, module, prefix: str) -> None:
    """把带有 router 变量的模块挂载到统一 /v1 前缀下。"""
    if hasattr(module, "router"):
        application.include_router(
            module.router,
            prefix=prefix,
            tags=[prefix.split("/")[-1]],
        )


def register_routes(
    directory: Path, module_name: str, prefix: str, application: FastAPI
) -> None:
    """递归扫描 api/routers 目录并按文件路径生成路由前缀。"""
    if not directory.exists():
        return
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("__"):
            continue
        if entry.is_dir():
            register_routes(
                entry,
                f"{module_name}.{entry.name}",
                f"{prefix}/{entry.name}",
                application,
            )
        elif entry.suffix == ".py":
            module = import_module(f"{module_name}.{entry.stem}")
            include_router(application, module, f"{prefix}/{entry.stem}")


def register_documentation(application: FastAPI) -> None:
    """注册使用本地静态资源的 Swagger UI 页面。"""

    @application.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """返回绑定本地 swagger 静态文件的文档页面。"""
        return get_swagger_ui_html(
            openapi_url=application.openapi_url,
            title=application.title + " - ",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )


def register_exception_handlers(application: FastAPI) -> None:
    """注册统一异常处理器，保持 HTTP 错误响应结构稳定。"""

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """把 FastAPI/Pydantic 校验错误转换成 JSON 响应。"""
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors())},
        )


app = create_app()


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """返回轻量健康状态，供 Compose healthcheck 判断应用进程已经可响应。"""
    return {"status": "ok"}


def main() -> None:
    """本地命令行启动入口，监听 41104 端口。"""
    configure_logging("INFO")
    uvicorn.run(
        "pokeop.main:app", host="0.0.0.0", port=41104, workers=2
    )


if __name__ == "__main__":
    main()
