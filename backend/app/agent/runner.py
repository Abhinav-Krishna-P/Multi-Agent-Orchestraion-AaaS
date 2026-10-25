"""Runs one reply and streams it as server-sent events.

Only one reply per chat runs at a time. A reply that is stopped partway keeps the text
generated so far; a reply that fails keeps nothing, so the user can retry.
"""
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Coroutine, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, ToolMessage
from langchain_core.tools import BaseTool
from sqlalchemy import func, select, update

from app.agent.context import HISTORY_LIMIT, build_messages
from app.agent.graph import AGENT_NODE, MAX_TOOL_ROUNDS, RECURSION_LIMIT, TOOLS_NODE, build_graph
from app.db.base import session_factory
from app.db.models import ChatSession, Message
from app.tools.forms import DEFAULT_ASK_TEXT, form_spec

logger = logging.getLogger(__name__)

MODEL_ERROR_MESSAGE = "The model couldn't reply. Check your API key and try again."

_in_flight: set[uuid.UUID] = set()
_background: set[asyncio.Task] = set()


def try_begin(session_id: uuid.UUID) -> bool:
    """Claims the chat for one reply. False if another reply is already running.

    Whoever claims must call end() exactly once. The chat endpoint does it when its
    response finishes, however it finishes (see TurnResponse).
    """
    if session_id in _in_flight:
        return False
    _in_flight.add(session_id)
    return True


def end(session_id: uuid.UUID) -> None:
    _in_flight.discard(session_id)


def _spawn(coro: Coroutine) -> None:
    """Runs work that must outlive the request (which may already be cancelled)."""
    task = asyncio.ensure_future(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


async def wait_for_background() -> None:
    while _background:
        await asyncio.gather(*list(_background), return_exceptions=True)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def chunk_text(chunk) -> str:
    """The visible text of a streamed chunk. Content is a string or a list of parts;
    parts that are not text (such as a model's thinking) are left out."""
    content = chunk.content
    if isinstance(content, str):
        return content
    pieces = []
    for part in content:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            pieces.append(part.get("text", ""))
    return "".join(pieces)


async def _recent_history(session_id: uuid.UUID) -> list[Message]:
    async with session_factory() as db:
        rows = await db.scalars(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(HISTORY_LIMIT)
        )
        return list(reversed(rows.all()))


async def _save_reply(
    session_id: uuid.UUID, text: str, tools: list[dict], sources: list[dict], form: dict | None = None
) -> uuid.UUID:
    async with session_factory() as db:
        message = Message(
            session_id=session_id, role="assistant", content=text, tool_calls=tools or None,
            sources=sources or None, form=form,
        )
        db.add(message)
        await db.execute(update(ChatSession).where(ChatSession.id == session_id).values(last_message_at=func.now()))
        await db.commit()
        return message.id


async def _save_partial_reply(session_id: uuid.UUID, text: str, tools: list[dict], sources: list[dict]) -> None:
    try:
        await _save_reply(session_id, text, tools, sources)
    except Exception as exc:  # the chat may have been deleted meanwhile
        logger.warning("Could not save a stopped reply: %s", type(exc).__name__)


async def _update_summary(session_id: uuid.UUID) -> None:
    from app.agent.summarizer import maybe_update_summary  # imported here: summarizer imports this module

    await maybe_update_summary(session_id)


def _failure_events() -> list[str]:
    return [
        sse("error", {"code": "model_error", "message": MODEL_ERROR_MESSAGE}),
        sse("done", {"message_id": None}),
    ]


async def failed_turn() -> AsyncIterator[str]:
    """The stream for a reply that could not even start (the model could not be set up)."""
    for event in _failure_events():
        yield event


async def run_turn(
    *,
    session_id: uuid.UUID,
    system_prompt: str,
    summary: str | None,
    model: BaseChatModel,
    tools: Sequence[BaseTool] = (),
    labels: dict[str, str] | None = None,
    extra_instruction: str | None = None,
    forms: dict | None = None,
) -> AsyncIterator[str]:
    """Answers the chat's last user message. The caller holds the chat's claim (try_begin).

    `labels` maps a tool's name to the words shown in chat while it runs. A tool result may
    carry sources (its `artifact`); they are sent once, just before the reply is done.
    """
    labels = labels or {}
    forms = forms or {}  # the switched-on tools that have a details form, by name
    calls: dict[str, tuple[str, dict]] = {}  # tool call id -> (tool name, arguments)
    asked: dict | None = None  # the form the agent asked the user to fill in
    refine: dict | None = None  # the form offered after a search that has filters
    parts: list[str] = []
    used: dict[str, dict] = {}  # tool call id -> {label, ok}, in the order the model asked
    sources: list[dict] = []
    rounds = 0
    settled = False  # the reply was saved, or its failure was reported
    try:
        history = await _recent_history(session_id)
        graph = build_graph(model, tools)
        stream = graph.astream(
            {"messages": build_messages(system_prompt, summary, history, extra_instruction)},
            stream_mode=["messages", "updates"],
            config={"recursion_limit": RECURSION_LIMIT},
        )
        async for mode, payload in stream:
            if mode == "messages":
                chunk, metadata = payload
                if metadata.get("langgraph_node") == AGENT_NODE and isinstance(chunk, AIMessageChunk):
                    piece = chunk_text(chunk)
                    if piece:
                        parts.append(piece)
                        yield sse("token", {"text": piece})
                continue
            for node, update_ in payload.items():
                messages = (update_ or {}).get("messages", [])
                if node == AGENT_NODE:
                    tool_calls = getattr(messages[-1], "tool_calls", None) or []
                    if tool_calls:
                        rounds += 1
                        if rounds > MAX_TOOL_ROUNDS:
                            raise RuntimeError("too many tool rounds")
                    for tool_call in tool_calls:
                        label = labels.get(tool_call["name"], tool_call["name"])
                        used[tool_call["id"]] = {"label": label, "ok": True}
                        calls[tool_call["id"]] = (tool_call["name"], tool_call["args"])
                        yield sse("tool_start", {"id": tool_call["id"], "label": label})
                elif node == TOOLS_NODE:
                    for message in messages:
                        if not isinstance(message, ToolMessage):
                            continue
                        ok = message.status != "error"
                        if message.tool_call_id in used:
                            used[message.tool_call_id]["ok"] = ok
                        if isinstance(message.artifact, list):
                            sources.extend(message.artifact)
                        elif isinstance(message.artifact, dict) and "form" in message.artifact:
                            asked = message.artifact["form"]
                        name, arguments = calls.get(message.tool_call_id, (None, {}))
                        if ok and name in forms:
                            refine = form_spec(forms[name], arguments, "refine")
                        yield sse("tool_end", {"id": message.tool_call_id, "ok": ok})
        if not parts and asked:
            # The model asked with a form and wrote nothing itself: say why the form is there.
            parts.append(DEFAULT_ASK_TEXT)
            yield sse("token", {"text": DEFAULT_ASK_TEXT})
        text = "".join(parts)
        if not text:
            raise RuntimeError("empty reply")
        message_id = await _save_reply(session_id, text, list(used.values()), sources, asked or refine)
        settled = True
        _spawn(_update_summary(session_id))
        if sources:
            yield sse("sources", {"sources": sources})
        yield sse("done", {"message_id": str(message_id)})
    except Exception as exc:
        # Only the exception type is logged: provider errors can carry request details.
        settled = True
        logger.warning("A reply failed: %s", type(exc).__name__)
        for event in _failure_events():
            yield event
    finally:
        if not settled and parts:
            # Stopped by the user or the connection dropped: keep what was written.
            _spawn(_save_partial_reply(session_id, "".join(parts), list(used.values()), sources))
