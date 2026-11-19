"""FastAPI application."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.automations import scheduler
from app.automations.run import sweep_interrupted_runs
from app.api import agent_api, public, analytics, automations, integrations, agents, chat, documents, llm_keys, me, personas, sessions, tools, webhooks
from app.core import cache
from app.core.config import export_tracing_env, get_settings
from app.core.errors import ApiError, api_error_handler
from app.rag.ingest import sweep_interrupted_documents


logger = logging.getLogger("uvicorn.error")  # uvicorn's logger is the one that prints INFO at startup


@asynccontextmanager
async def _lifespan(_: FastAPI):
    logger.info("Cache: %s", cache.backend_name())
    # Document processing runs in background tasks, which a restart kills.
    await sweep_interrupted_documents()
    await sweep_interrupted_runs()
    if get_settings().scheduler_enabled:
        scheduler.start()
    yield
    await scheduler.stop()
    await cache.close()


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

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/v1/"):
            return await request_validation_exception_handler(request, exc)
        message = str(exc.errors()[0]["msg"]).removeprefix("Value error, ")
        return JSONResponse(status_code=422, content={"detail": {"code": "invalid_request", "message": message}})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    for module in (me, llm_keys, personas, agents, sessions, chat, tools, documents, integrations, analytics, automations, webhooks, agent_api, public):
        app.include_router(module.router)

    return app


app = create_app()
