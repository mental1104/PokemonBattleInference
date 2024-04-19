import os
import uvicorn
from importlib import import_module
import logging
import sys

sys.path.append("../")

logging.basicConfig(
    level=getattr(logging, "INFO"),
    format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
           " %(message)s"
)

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    title="Blue Espeon",
    description="Blue Espeon's little httpserver",
    version="0.0.1"
)

absolute_path = os.path.dirname(os.path.abspath(__file__)) + "/static"
app.mount("/static", StaticFiles(directory=absolute_path), name="static")

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css"
    )
    
def include_routers(module, prefix):
    if hasattr(module, "router"):
        app.include_router(module.router, prefix=prefix, tags=[prefix.split("/")[-1]])


def register_routes(directory, module_name, prefix):
    suffix = ".py"
    for file_name in os.listdir(directory):
        file_path = os.path.join(directory, file_name)
        sub_module_name = f"{module_name}.{file_name}"
        if os.path.isdir(file_path):
            next_prefix= prefix + '/' + file_name
            register_routes(file_path, sub_module_name, next_prefix[:])
        elif sub_module_name.endswith(suffix):
            next_prefix = prefix + '/' + file_name[:-len(suffix)]
            module = import_module(sub_module_name[:-len(suffix)])
            if module:
                include_routers(module, next_prefix[:])


router_path = os.path.dirname(os.path.abspath(__file__)) + "/routers"
router_package_path = "api.routers"
common_prefix = "/nexus/api"

register_routes(router_path, router_package_path, common_prefix)

def set_logging(process_name, log_level="INFO"):
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] %(levelname)s"
            " %(message)s"
    )


def main():
    uvicorn.run(
        app='run:app',
        host='0.0.0.0',
        port=8000,
        workers=2
    )

if __name__ == "__main__":
    main()