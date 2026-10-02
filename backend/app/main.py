"""FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import export_tracing_env, get_settings
from app.core.errors import ApiError, api_error_handler


def create_app() -> FastAPI:
    export_tracing_env()
    settings = get_settings()
    app = FastAPI(title="Custom Agent Platform")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(ApiError, api_error_handler)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
