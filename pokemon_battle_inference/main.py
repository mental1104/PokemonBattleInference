from importlib import import_module
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from pokemon_battle_inference.core.logging import configure_logging
from pokemon_battle_inference.infrastructure.db import setup

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ROUTER_DIR = BASE_DIR / "api" / "routers"
ROUTER_PACKAGE = "pokemon_battle_inference.api.routers"
COMMON_PREFIX = "/nexus/api"


def create_app() -> FastAPI:
    setup()
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
    if hasattr(module, "router"):
        application.include_router(
            module.router,
            prefix=prefix,
            tags=[prefix.split("/")[-1]],
        )


def register_routes(
    directory: Path, module_name: str, prefix: str, application: FastAPI
) -> None:
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
    @application.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        return get_swagger_ui_html(
            openapi_url=application.openapi_url,
            title=application.title + " - ",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
        )


def register_exception_handlers(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors())},
        )


app = create_app()


def main() -> None:
    configure_logging("INFO")
    uvicorn.run(
        "pokemon_battle_inference.main:app", host="0.0.0.0", port=8000, workers=2
    )


if __name__ == "__main__":
    main()
