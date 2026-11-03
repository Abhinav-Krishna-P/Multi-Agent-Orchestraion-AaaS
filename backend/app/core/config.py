"""Settings read from backend/.env (environment variables win over the file)."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    database_url: str
    test_database_url: str | None = None
    db_null_pool: bool = False

    supabase_url: str = ""
    supabase_jwt_secret: str | None = None

    fernet_master_key: str

    platform_gemini_api_key: str | None = None
    summary_model: str = ""

    frontend_origin: str = "http://localhost:5173"

    # Knowledge base
    chroma_url: str = ""
    chroma_token: str = ""  # sent as the X-Chroma-Token header when set; the proxy in front of Chroma checks it
    embedding_model: str = "gemini-embedding-2"
    chunking_method: str = "recursive"  # or "parent_child"; chosen by the LangSmith comparison

    # Platform keys for the outside-service tools. A tool whose key is empty is not offered.
    serpapi_api_key: str = ""
    serper_api_key: str = ""
    finnhub_api_key: str = ""
    composio_api_key: str = ""  # one key for the whole platform; never sent to the browser
    # Used by searches when the user does not say where: Google country, currency for stays.
    default_country: str = "in"
    default_currency: str = "INR"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def export_tracing_env() -> None:
    """LangSmith reads its settings from the process environment, not from our Settings."""
    for key, value in dotenv_values(ENV_FILE).items():
        if key.startswith("LANGSMITH_") and value and key not in os.environ:
            os.environ[key] = value
