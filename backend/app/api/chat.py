import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runner
from app.agent.llm import ModelFactory, get_model_factory, get_user_api_key
from app.api.deps import get_owned_session
from app.api.schemas import ChatIn
from app.api.sessions import agent_not_live
from app.core.errors import ApiError
from app.core.llm_catalog import provider_name
from app.db.base import get_db
from app.db.models import ChatSession, Message
from app.rag.embeddings import Embedder, get_embedder
from app.rag.retrieve import document_names
from app.rag.vector_store import VectorStore, get_vector_store
from app.tools import knowledge_base
from app.tools.registry import REGISTRY

router = APIRouter()

MAX_MESSAGE_LENGTH = 20000
TITLE_LENGTH = 60
DEFAULT_TITLE = "New chat"


def _new_message_text(body: ChatIn) -> str | None:
    """The trimmed message to save, or None for a retry. Anything else is refused."""
    if body.retry and body.message is None:
        return None
    text = (body.message or "").strip()
    if body.retry or not text:
        raise ApiError(422, "invalid_message", "Write a message first.")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ApiError(422, "invalid_message", "That message is too long. Shorten it and try again.")
    return text


class TurnResponse(StreamingResponse):
    """Streams one reply and releases the chat's claim when the response ends.

    Releasing here, not inside the reply generator, covers the case where the client
    disconnects before the first byte: the generator is then never run at all.
    """

    def __init__(self, events, session_id: uuid.UUID):
        super().__init__(
            events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )
        self._session_id = session_id

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            runner.end(self._session_id)


@router.post("/sessions/{session_id}/chat")
async def chat(
    body: ChatIn,
    session: ChatSession = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    build_model: ModelFactory = Depends(get_model_factory),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
):
    text = _new_message_text(body)
    agent = session.agent
    if agent.status != "live":
        raise agent_not_live()
    if not agent.llm_provider or not agent.llm_model:
        raise ApiError(409, "llm_not_configured", "Choose a model for this agent before chatting.")
    api_key = await get_user_api_key(db, session.user_id, agent.llm_provider)
    if api_key is None:
        raise ApiError(
            409, "missing_api_key", f"Add your {provider_name(agent.llm_provider)} API key to start chatting."
        )
    if not runner.try_begin(session.id):
        raise ApiError(409, "reply_in_progress", "Wait for the current reply to finish.")

    try:
        if text is None:
            last = await db.scalar(
                select(Message).where(Message.session_id == session.id).order_by(Message.created_at.desc()).limit(1)
            )
            if last is None or last.role != "user":
                raise ApiError(409, "nothing_to_retry", "There's nothing to retry in this chat.")
        else:
            db.add(Message(session_id=session.id, role="user", content=text))
            session.last_message_at = func.now()
            if session.title == DEFAULT_TITLE:
                session.title = " ".join(text.split())[:TITLE_LENGTH]
            await db.commit()
        # Read everything the stream needs now; the stream uses its own database sessions.
        specs = [REGISTRY[name] for name in agent.tools if name in REGISTRY]
        turn = {
            "session_id": session.id,
            "system_prompt": agent.system_prompt,
            "summary": session.summary,
            "tools": [spec.tool for spec in specs],
            "labels": {spec.name: spec.activity for spec in specs},
        }
        # The knowledge-base tools exist only while there is something to search.
        ready_documents = await document_names(db, agent.id) if agent.kb_enabled else []
        if ready_documents:
            turn["tools"] += knowledge_base.build_kb_tools(agent.id, agent.search_mode, embedder=embedder, store=store)
            turn["labels"] |= knowledge_base.LABELS
            turn["extra_instruction"] = knowledge_base.kb_instruction(ready_documents)
        provider, model_id = agent.llm_provider, agent.llm_model
    except BaseException:
        runner.end(session.id)
        raise

    try:
        model = build_model(provider, model_id, api_key)
    except Exception as exc:
        runner.logger.warning("A model could not be set up: %s", type(exc).__name__)
        return TurnResponse(runner.failed_turn(), session.id)
    return TurnResponse(runner.run_turn(model=model, **turn), session.id)
