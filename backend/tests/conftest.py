"""Shared test setup.

Tests run against the separate test database and never call a real provider:
the environment is switched before any app module is imported.
"""
import os
import time
import uuid
from pathlib import Path

import jwt
import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_JWT_SECRET = "test-secret-0123456789-0123456789-abcdef"
USER_A_ID = "11111111-1111-1111-1111-111111111111"
USER_B_ID = "22222222-2222-2222-2222-222222222222"


class _TestEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")
    test_database_url: str


_test_db_url = _TestEnv().test_database_url
assert _test_db_url.rsplit("/", 1)[-1].endswith("_test"), "TEST_DATABASE_URL must name a *_test database"

os.environ["DATABASE_URL"] = _test_db_url
os.environ["DB_NULL_POOL"] = "true"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ["PLATFORM_GEMINI_API_KEY"] = ""
os.environ["SUMMARY_MODEL"] = "test-summary-model"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["CHUNKING_METHOD"] = "recursive"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["REDIS_URL"] = ""  # tests use the in-process cache, never the owner's Redis
os.environ["DEFAULT_COUNTRY"] = "in"
os.environ["DEFAULT_CURRENCY"] = "INR"
for _name in ("POSTHOG_API_KEY", "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_ID"):  # tests never send an event
    os.environ[_name] = ""
for _name in ("SERPAPI", "SERPER", "FINNHUB", "COMPOSIO"):  # stand-in keys: tests never reach a real service
    os.environ[f"{_name}_API_KEY"] = f"test-{_name.lower()}-key"


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _empty_cache():
    from app.core import cache

    cache.reset()


@pytest.fixture(autouse=True)
async def _clean_tables():
    yield
    from sqlalchemy import text

    from app.db.base import Base, engine

    names = [t.name for t in Base.metadata.sorted_tables]
    if names:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {', '.join(names)} CASCADE"))


@pytest.fixture
def app():
    from app.core.errors import ApiError
    from app.main import create_app

    application = create_app()

    @application.get("/__test_error")
    async def _raise():
        raise ApiError(409, "agent_not_live", "x")

    return application


@pytest.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def db():
    from app.db.base import session_factory

    async with session_factory() as session:
        yield session


def make_token(
    sub: str = USER_A_ID,
    email: str = "a@example.com",
    name: str = "User A",
    *,
    secret: str = TEST_JWT_SECRET,
    audience: str = "authenticated",
    expires_in: int | None = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "aud": audience,
        "iat": now,
        "user_metadata": {"full_name": name, "avatar_url": "https://example.com/a.png"},
    }
    if expires_in is not None:
        payload["exp"] = now + expires_in
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def headers_for():
    def _headers(sub: str = USER_A_ID, email: str = "a@example.com", name: str = "User A", **kwargs) -> dict:
        return {"Authorization": f"Bearer {make_token(sub, email, name, **kwargs)}"}

    return _headers


@pytest.fixture
def user_a(headers_for):
    return headers_for(USER_A_ID, "a@example.com", "User A")


@pytest.fixture
def user_b(headers_for):
    return headers_for(USER_B_ID, "b@example.com", "User B")


def new_id() -> str:
    return str(uuid.uuid4())
