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


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册静态资源、路由、文档和异常处理器。

    数据库 schema、CSV 资产和物化视图由独立的一次性初始化命令准备；HTTP 服务
    生命周期不得修改数据库结构，以便未来安全运行多个 worker 或容器副本。

    Returns:
        已完成路由和异常处理器注册的 FastAPI 应用。
    """
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        title="Blue Espeon",
        description="Blue Espeon's little httpserver",
        version="0.0.1",
    )
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_routes(ROUTER_DIR, ROUTER_PACKAGE, COMMON_PREFIX, application)
    register_documentation(application)
    register_exception_handlers(application)
    return application


def include_router(application: FastAPI, module, prefix: str) -> None:
    """把带有 router 变量的模块挂载到统一 `/v1` 前缀下。

    Args:
        application: 接收路由注册的 FastAPI 应用。
        module: 动态导入的 router 模块；没有 `router` 属性时忽略。
        prefix: 由目录路径推导出的 HTTP 前缀。
    """
    if hasattr(module, "router"):
        application.include_router(
            module.router,
            prefix=prefix,
            tags=[prefix.split("/")[-1]],
        )


def register_routes(
    directory: Path, module_name: str, prefix: str, application: FastAPI
) -> None:
    """递归扫描 `api/routers` 目录并按文件路径生成路由前缀。

    Args:
        directory: 当前扫描的 router 文件系统目录。
        module_name: 当前目录对应的 Python package 名称。
        prefix: 当前目录对应的 HTTP 路径前缀。
        application: 接收路由注册的 FastAPI 应用。
    """
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
    """注册使用本地静态资源的 Swagger UI 页面。

    Args:
        application: 接收文档路由注册的 FastAPI 应用。
    """

    @application.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """返回绑定本地 Swagger 静态文件的文档页面。"""
        return get_swagger_ui_html(
            openapi_url=application.openapi_url,
            title=application.title + " - ",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )


def register_exception_handlers(application: FastAPI) -> None:
    """注册统一异常处理器，保持 HTTP 错误响应结构稳定。

    Args:
        application: 接收异常处理器注册的 FastAPI 应用。
    """

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """把 FastAPI/Pydantic 校验错误转换成稳定 JSON 响应。

        Args:
            request: 触发校验错误的 HTTP 请求；当前仅保留以满足处理器签名。
            exc: FastAPI 捕获的请求校验异常。

        Returns:
            HTTP 422 JSON 响应，`detail` 保存可序列化的校验错误列表。
        """
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
