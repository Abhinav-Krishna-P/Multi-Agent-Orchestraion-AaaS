"""Request and response shapes."""
import uuid
from datetime import datetime

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


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


class PersonaOut(_FromRow):
    key: str
    name: str
    description: str
    prompt: str


AgentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
AgentDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
SystemPrompt = Annotated[str, StringConstraints(max_length=20000)]


class AgentOut(_FromRow):
    id: uuid.UUID
    name: str
    description: str
    persona_key: str | None
    custom_prompt: str | None
    system_prompt: str
    llm_provider: str | None
    llm_model: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class AgentCreate(BaseModel):
    name: AgentName
    description: AgentDescription = ""


class AgentUpdate(BaseModel):
    """Only the fields that are sent are changed."""

    name: AgentName | None = None
    description: AgentDescription | None = None
    persona_key: str | None = None
    system_prompt: SystemPrompt | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
