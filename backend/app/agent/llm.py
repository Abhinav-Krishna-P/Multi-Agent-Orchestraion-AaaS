"""Everything that touches a user's LLM key: checking it and reading it back."""
import uuid
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import decrypt_key
from app.db.models import LlmKey

KeyValidator = Callable[[str, str], Awaitable[bool]]

# Read-only "list models" requests: they prove a key works without spending tokens.
_CHECKS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key", "{key}"),
    "openai": ("https://api.openai.com/v1/models", "Authorization", "Bearer {key}"),
}


async def validate_key(provider: str, api_key: str) -> bool:
    url, header, template = _CHECKS[provider]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers={header: template.format(key=api_key)})
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def get_key_validator() -> KeyValidator:
    return validate_key


async def get_user_api_key(db: AsyncSession, user_id: uuid.UUID, provider: str) -> str | None:
    row = await db.scalar(select(LlmKey).where(LlmKey.user_id == user_id, LlmKey.provider == provider))
    return decrypt_key(row.encrypted_key) if row else None
