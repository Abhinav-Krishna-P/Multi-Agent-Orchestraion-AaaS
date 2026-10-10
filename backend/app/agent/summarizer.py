"""Keeps a short running summary of each chat, so long chats stay within the model's context.

Runs on the platform's own Gemini key, never the user's. A summary is a convenience:
any failure here is logged and ignored, and the chat carries on without one.
"""
import logging
import uuid

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.agent.llm import build_chat_model
from app.agent.runner import chunk_text
from app.core.config import get_settings
from app.db.base import session_factory
from app.db.models import ChatSession, Message

logger = logging.getLogger(__name__)

SUMMARY_EVERY = 10  # new messages needed before the summary is refreshed
MAX_MESSAGE_CHARS = 2000  # per message sent to the summary model

INSTRUCTIONS = (
    "You keep a running summary of a conversation between a user and an AI agent. "
    "Using the previous summary (if there is one) and the new messages, write an updated "
    "summary of 50 to 100 words. Keep the facts, names, decisions and open questions the "
    "agent will need to continue the conversation. Reply with the summary text only."
)


def _platform_model() -> BaseChatModel | None:
    settings = get_settings()
    if not settings.platform_gemini_api_key or not settings.summary_model:
        return None
    return build_chat_model("gemini", settings.summary_model, settings.platform_gemini_api_key)


def _request(previous: str | None, messages: list[Message]) -> str:
    lines = [f"{m.role}: {m.content[:MAX_MESSAGE_CHARS]}" for m in messages]
    return f"Previous summary:\n{previous or '(none)'}\n\nNew messages:\n" + "\n".join(lines)


async def maybe_update_summary(session_id: uuid.UUID, *, model: BaseChatModel | None = None) -> bool:
    """Refreshes the chat's summary once enough new messages have arrived. True if it was written."""
    try:
        async with session_factory() as db:
            session = await db.get(ChatSession, session_id)
            if session is None:
                return False
            query = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
            if session.summary_updated_at is not None:
                query = query.where(Message.created_at > session.summary_updated_at)
            new_messages = list((await db.scalars(query)).all())
            previous = session.summary
        if len(new_messages) < SUMMARY_EVERY:
            return False
        model = model or _platform_model()
        if model is None:
            return False

        response = await model.ainvoke(
            [SystemMessage(content=INSTRUCTIONS), HumanMessage(content=_request(previous, new_messages))]
        )
        summary = chunk_text(response).strip()
        if not summary:
            return False

        async with session_factory() as db:
            session = await db.get(ChatSession, session_id)
            if session is None:
                return False
            session.summary = summary
            # The newest message that was summarised, not "now": messages that arrived
            # while the model was working still count towards the next refresh.
            session.summary_updated_at = new_messages[-1].created_at
            await db.commit()
        return True
    except Exception as exc:
        logger.warning("A chat summary could not be updated: %s", type(exc).__name__)
        return False
