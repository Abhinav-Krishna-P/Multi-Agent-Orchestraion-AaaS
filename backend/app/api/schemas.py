"""Request and response shapes."""
import uuid
from datetime import datetime

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


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
    kb_enabled: bool
    search_mode: str
    kb_strict: bool
    tools: list[str]
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
    kb_enabled: bool | None = None
    kb_strict: bool | None = None
    search_mode: Literal["semantic", "keyword", "hybrid"] | None = None


class AgentToolsIn(BaseModel):
    tools: list[str]


class SessionOut(_FromRow):
    id: uuid.UUID
    agent_id: uuid.UUID
    title: str
    summary: str | None
    created_at: datetime
    last_message_at: datetime


class SessionAgentOut(_FromRow):
    id: uuid.UUID
    name: str
    status: str
    llm_provider: str | None
    llm_model: str | None


class SessionDetailOut(SessionOut):
    agent: SessionAgentOut


class MessageOut(_FromRow):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    # Stored on the row as tool_calls / sources; null there means none.
    tools: list[dict] = Field(default_factory=list, validation_alias="tool_calls")
    sources: list[dict] = Field(default_factory=list)
    form: dict | None = None

    @field_validator("tools", "sources", mode="before")
    @classmethod
    def _none_is_empty(cls, value):
        return value or []


class ChatIn(BaseModel):
    """Either a new message, or a request to answer the last unanswered one again."""

    message: str | None = None
    retry: bool = False


class DocumentOut(_FromRow):
    id: uuid.UUID
    filename: str
    source_type: str
    status: str
    error: str | None
    chunk_count: int
    created_at: datetime
