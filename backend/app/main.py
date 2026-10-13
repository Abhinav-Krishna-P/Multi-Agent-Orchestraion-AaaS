"""FastAPI application."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, chat, llm_keys, me, personas, sessions
from app.core.config import export_tracing_env, get_settings
from app.core.errors import ApiError, api_error_handler


def create_app() -> FastAPI:
    export_tracing_env()
    settings = get_settings()
    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise RuntimeError("Set SUPABASE_URL (or SUPABASE_JWT_SECRET) in backend/.env: sign-in tokens can't be checked.")
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

    for module in (me, llm_keys, personas, agents, sessions, chat):
        app.include_router(module.router)

    return app


app = create_app()
