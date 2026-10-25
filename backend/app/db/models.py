"""Database tables for stage 1 (spec §14). Later stages add tables with new migrations."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    # Same value as the Supabase user ID, so it is never generated here.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmKey(Base):
    __tablename__ = "llm_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_llm_keys_user_provider"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'live', 'stopped')", name="ck_agents_status"),
        CheckConstraint("search_mode in ('semantic', 'keyword', 'hybrid')", name="ck_agents_search_mode"),
        Index("ix_agents_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    persona_key: Mapped[str | None] = mapped_column(Text)
    custom_prompt: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    llm_provider: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(Text)
    # Unused until the knowledge base arrives in stage 2.
    kb_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    search_mode: Mapped[str] = mapped_column(Text, nullable=False, default="hybrid", server_default="hybrid")
    # True: answer only from the documents. False: documents first, then general knowledge.
    kb_strict: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tool_rows: Mapped[list["AgentTool"]] = relationship(lazy="selectin", cascade="all, delete-orphan")

    @property
    def tools(self) -> list[str]:
        """Names of the registry tools switched on for this agent."""
        return sorted(row.tool_name for row in self.tool_rows)


class AgentTool(Base):
    """One registry tool switched on for one agent."""

    __tablename__ = "agent_tools"
    __table_args__ = (UniqueConstraint("agent_id", "tool_name", name="uq_agent_tools_agent_tool"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class Document(Base):
    """One document in an agent's knowledge base. Its text lives in document_chunks, its vectors in Chroma."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("source_type in ('pdf', 'txt', 'paste')", name="ck_documents_source_type"),
        CheckConstraint("status in ('pending', 'processing', 'ready', 'failed')", name="ck_documents_status"),
        UniqueConstraint("agent_id", "content_hash", name="uq_documents_agent_hash"),
        Index("ix_documents_agent_id", "agent_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Recorded so vectors from different models or methods are never mixed up later.
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    chunking_method: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_document_chunks_agent_id", "agent_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # `content` is the text that is searched. `context` is what the model is given
    # instead, when it differs (parent-child chunking); null means use `content`.
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created_at()


class ChatSession(Base):
    """One conversation between a user and one agent. Table name: sessions."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_agent_last_message", "agent_id", "last_message_at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New chat", server_default="New chat")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent: Mapped[Agent] = relationship(lazy="joined")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role in ('user', 'assistant', 'tool')", name="ck_messages_role"),
        Index("ix_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # For assistant rows: the tools that ran, as [{label, ok}], and the sources shown,
    # as [{document_name, page, excerpt}].
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    sources: Mapped[list | None] = mapped_column(JSONB)
    # A details form shown with this reply: {kind: "ask" | "refine", tool, title, fields, values}.
    form: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp(), nullable=False
    )
