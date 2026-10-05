"""Request and response shapes."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(_FromRow):
    id: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None


class LlmKeyOut(_FromRow):
    provider: str
    key_hint: str
    updated_at: datetime


class LlmKeyIn(BaseModel):
    api_key: str
