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


def _stream(events) -> StreamingResponse:
    return StreamingResponse(
        events, media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.post("/sessions/{session_id}/chat")
async def chat(
    body: ChatIn,
    session: ChatSession = Depends(get_owned_session),
    db: AsyncSession = Depends(get_db),
    build_model: ModelFactory = Depends(get_model_factory),
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
        # Read everything the stream needs now: the request's database session closes before it runs.
        turn = {"session_id": session.id, "system_prompt": agent.system_prompt, "summary": session.summary}
        provider, model_id = agent.llm_provider, agent.llm_model
    except BaseException:
        runner.end(session.id)
        raise

    try:
        model = build_model(provider, model_id, api_key)
    except Exception as exc:
        runner.logger.warning("A model could not be set up: %s", type(exc).__name__)
        return _stream(runner.failed_turn(session.id))
    return _stream(runner.run_turn(model=model, **turn))
