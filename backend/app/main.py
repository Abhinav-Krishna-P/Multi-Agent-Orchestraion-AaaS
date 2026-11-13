"""FastAPI application."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.automations import scheduler
from app.api import analytics, automations, integrations, agents, chat, documents, llm_keys, me, personas, sessions, tools, webhooks
from app.core.config import export_tracing_env, get_settings
from app.core.errors import ApiError, api_error_handler
from app.rag.ingest import sweep_interrupted_documents


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Document processing runs in background tasks, which a restart kills.
    await sweep_interrupted_documents()
    if get_settings().scheduler_enabled:
        scheduler.start()
    yield
    await scheduler.stop()


def create_app() -> FastAPI:
    export_tracing_env()
    settings = get_settings()
    if not settings.supabase_url and not settings.supabase_jwt_secret:
        raise RuntimeError("Set SUPABASE_URL (or SUPABASE_JWT_SECRET) in backend/.env: sign-in tokens can't be checked.")
    app = FastAPI(title="Custom Agent Platform", lifespan=_lifespan)
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

    for module in (me, llm_keys, personas, agents, sessions, chat, tools, documents, integrations, analytics, automations, webhooks):
        app.include_router(module.router)

    return app


app = create_app()
