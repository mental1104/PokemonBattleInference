from collections.abc import Callable
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pokeop.application.battle_graph_store import BattleGraphStore
from pokeop.infrastructure.battle_graph_store import InMemoryBattleGraphStore
from pokeop.infrastructure.logging import configure_logging
from pokeop.persistence.bootstrap import register_postgres_runtime

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "assets_static"
ROUTER_DIR = BASE_DIR / "api" / "routers"
ROUTER_PACKAGE = "pokeop.api.routers"
COMMON_PREFIX = "/v1"

BattleGraphStoreFactory = Callable[[], BattleGraphStore]


def create_app(
    graph_store_factory: BattleGraphStoreFactory = InMemoryBattleGraphStore,
) -> FastAPI:
    """创建 FastAPI 应用并注册运行时依赖、路由、文档和异常处理器。

    数据库 schema、CSV 资产和物化视图由独立的一次性初始化命令准备；HTTP 服务
    生命周期不得修改数据库结构。完整战斗图 store 由工厂在 lifespan 中创建一次，
    同一 backend 进程内的首次推演和后续探索请求共享该实例。

    Args:
        graph_store_factory: 创建 application 生命周期 graph store 的无参工厂；测试可注入
            fake clock 或固定容量实现，生产默认使用进程内有界 TTL store。

    Returns:
        已完成运行时依赖、路由和异常处理器注册的 FastAPI 应用。

    Raises:
        ValueError: graph store 工厂不可调用时抛出。
    """
    if not callable(graph_store_factory):
        raise ValueError("graph_store_factory must be callable")
    application = FastAPI(
        docs_url=None,
        redoc_url=None,
        lifespan=application_lifespan,
        title="Blue Espeon",
        description="Blue Espeon's little httpserver",
        version="0.0.1",
    )
    application.state.battle_graph_store_factory = graph_store_factory
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    register_routes(ROUTER_DIR, ROUTER_PACKAGE, COMMON_PREFIX, application)
    register_documentation(application)
    register_exception_handlers(application)
    return application


@asynccontextmanager
async def application_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """管理 HTTP 服务生命周期中的数据库运行时和共享 graph store。

    数据库内容仍由 `db-init` 一次性命令准备；这里把 PostgreSQL 连接写入当前 backend
    进程的 shared common registry，并创建一次有界 graph store。store 不按请求重建，
    因而首次推演返回的 graph ID 可被后续探索请求读取。

    Args:
        application: 正在启动的 FastAPI 应用，包含 ``battle_graph_store_factory``。

    Yields:
        应用运行控制权；退出阶段移除 application state 对完整图 store 的强引用。

    Raises:
        RuntimeError: 工厂缺失，或返回对象没有实现 ``BattleGraphStore`` port 时抛出。
    """
    register_postgres_runtime()
    graph_store_factory = getattr(
        application.state,
        "battle_graph_store_factory",
        None,
    )
    if not callable(graph_store_factory):
        raise RuntimeError("battle graph store factory is not configured")
    graph_store = graph_store_factory()
    if not isinstance(graph_store, BattleGraphStore):
        raise RuntimeError("battle graph store factory returned an invalid store")

    application.state.battle_graph_store = graph_store
    try:
        yield
    finally:
        # 进程退出时释放 store 及其持有的完整图；不启动额外后台清理线程。
        delattr(application.state, "battle_graph_store")


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
    """本地命令行启动入口，以单进程模式监听 41104 端口。

    进程内 graph store 无法跨 worker 共享；在引入 Redis 等外部 store 前必须保持单 worker，
    否则首次推演和后续探索可能落到不同进程并把有效 graph ID 误报为不存在。
    """
    configure_logging("INFO")
    uvicorn.run(
        "pokeop.main:app", host="0.0.0.0", port=41104, workers=1
    )


if __name__ == "__main__":
    main()
