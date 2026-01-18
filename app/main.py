from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.logging import configure_logging
from app.ui.routes import router as ui_router


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Trading Bot")

    app.include_router(api_router, prefix="/api")
    app.include_router(ui_router)
    app.mount("/static", StaticFiles(directory="app/ui/static"), name="static")

    return app


app = create_app()
