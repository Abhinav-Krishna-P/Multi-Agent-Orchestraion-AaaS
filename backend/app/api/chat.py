import json
import logging
import time
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runner
from app.agent.toolset import build_toolset
from app.automations import service
from app.automations.describe import build_describe_turn
from app.analytics import posthog
from app.agent.llm import ModelFactory, get_model_factory, get_user_api_key
from app.api.deps import get_owned_session
from app.api.schemas import ApprovalIn, ChatIn
from app.api.sessions import agent_not_live
from app.core.errors import ApiError
from app.core.llm_catalog import provider_name
from app.db.base import get_db
from app.db.models import AgentIntegration, ChatSession, Message
from app.integrations import composio
from app.rag.embeddings import Embedder, get_embedder
from app.rag.vector_store import VectorStore, get_vector_store
from app.tools.http import ToolError, Unavailable

logger = logging.getLogger(__name__)

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


MAX_RESULT = 2000  # of an approved action's result, kept for the agent's next reply


def _not_pending() -> ApiError:
    return ApiError(409, "approval_not_pending", "That request isn't waiting for an answer any more.")


async def _newest(db: AsyncSession, session_id) -> Message | None:
    return await db.scalar(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at.desc()).limit(1)
    )


async def _run_approved(db: AsyncSession, agent, user_id: str, request: dict) -> dict:
    """Runs an approved action from the platform's own record of it, if it may still run."""
    app_name = request["app_name"]

    def failed(reason: str) -> dict:
        return {"outcome": "failed", "reason": reason}

    if not composio.enabled():
        return failed("App connections aren't set up on this server.")
    row = await db.scalar(select(AgentIntegration).where(
        AgentIntegration.agent_id == agent.id, AgentIntegration.app == request["app"]))
    if row is None or row.status != "active":
        return failed(f"{app_name} isn't connected any more.")
    if request["action"] not in row.actions:
        return failed("This action isn't switched on any more.")
    try:
        offered = {action["slug"]: action for action in await composio.actions(row.app)}
    except Exception:  # nothing has run yet
        return failed(f"{app_name}'s actions couldn't be checked right now.")
    if (offered.get(request["action"]) or {}).get("kind") != "write":
        return failed("This action isn't available any more.")
    unknown = {"outcome": "unknown",
               "reason": f"{app_name} didn't answer in time, so it may or may not have been done. Check {app_name} before trying again."}
    try:
        data = await composio.run_action(request["action"], row.connected_account_id, user_id, request["arguments"])
    except Unavailable:
        # No proper answer is not a "no": the email may have gone. Saying "failed" would invite a second one.
        return unknown
    except ToolError as error:
        if await composio.stopped_working(row.id, row.connected_account_id, user_id, str(error)):
            return failed(f"The {app_name} connection has stopped working. Reconnect it in the agent's Apps step.")
        return failed(str(error))
    except Exception as error:  # an answer in a shape we don't know: it may have run
        logger.warning("An approved action ended unexpectedly: %s", type(error).__name__)
        return unknown
    return {"outcome": "done", "result": json.dumps(data, ensure_ascii=False, default=str)[:MAX_RESULT]}


async def _decide_automation(db: AsyncSession, session: ChatSession, last: Message, request: dict, approve: bool) -> list[dict]:
    """The same claim-then-act steps as an action, for a proposed automation."""
    status = "approved" if approve else "rejected"
    label = f"{request['name']} (automation)"
    claimed = await db.execute(
        update(Message)
        .where(Message.id == last.id, Message.approval["status"].astext == "pending")
        .values(approval={**request, "status": status})
    )
    if claimed.rowcount != 1:
        raise _not_pending()
    db.add(Message(session_id=session.id, role="user", content=f"{'Approved' if approve else 'Declined'}: {label}"))
    session.last_message_at = func.now()
    await db.commit()
    if not approve:
        return []
    message_id, agent = last.id, session.agent  # read now: a rollback expires the loaded rows
    try:
        outcome = await service.activate(db, session, request)
    except Exception as error:  # the claim is committed, so end with an outcome rather than a stuck message
        logger.warning("Activating an automation ended unexpectedly: %s", type(error).__name__)
        await db.rollback()
        await db.refresh(session)  # the reply that follows reads both
        await db.refresh(agent)
        outcome ={"outcome": "failed", "reason": "Couldn't set up the automation. Try again."}
    await db.execute(update(Message).where(Message.id == message_id).values(approval={**request, "status": status, **outcome}))
    await db.commit()
    return [{"label": label, "ok": outcome["outcome"] == "done"}]


async def _decide(db: AsyncSession, session: ChatSession, decision: ApprovalIn) -> list[dict]:
    """Records the user's answer to the newest message's request, runs the action if approved,
    and saves the answer as the user's message. Returns the action as the reply's first tool."""
    last = await _newest(db, session.id)
    if last is None or last.id != decision.message_id or last.role != "assistant" or (last.approval or {}).get("status") != "pending":
        raise _not_pending()
    request, approve = dict(last.approval), decision.decision == "approve"
    if request.get("kind") == "automation":
        return await _decide_automation(db, session, last, request, approve)
    where = {"agent_id": session.agent_id, "session_id": session.id, "tool_name": str(request.get("action", "")).lower(),
             "app": request.get("app")}
    status = "approved" if approve else "rejected"
    what = f"{request['action_name']} ({request['app_name']})"
    # Only one answer can win, even from two tabs at once: the row changes only while still pending.
    claimed = await db.execute(
        update(Message)
        .where(Message.id == last.id, Message.approval["status"].astext == "pending")
        .values(approval={**request, "status": status})
    )
    if claimed.rowcount != 1:  # nothing changed, so there is nothing to undo
        raise _not_pending()
    # The answer is saved with the claim: if anything stops after this, the chat ends with the
    # user's message, so Retry is offered, and the record says no outcome was ever written.
    db.add(Message(session_id=session.id, role="user", content=f"{'Approved' if approve else 'Declined'}: {what}"))
    session.last_message_at = func.now()
    await db.commit()
    if not approve:
        posthog.capture("write_action_decision", session.user_id, **where, decision="rejected")
        return []
    began = time.monotonic()
    outcome = await _run_approved(db, session.agent, str(session.user_id), request)
    posthog.capture("write_action_decision", session.user_id, **where, decision="approved", outcome=outcome["outcome"])
    posthog.capture("tool_called", session.user_id, **where, tool_type="composio", success=outcome["outcome"] == "done",
                    duration_ms=int((time.monotonic() - began) * 1000))
    await db.execute(update(Message).where(Message.id == last.id).values(approval={**request, "status": status, **outcome}))
    await db.commit()
    return [{"label": what, "ok": outcome["outcome"] == "done"}]


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
    deciding = body.approval is not None
    if deciding and (body.message is not None or body.retry):
        raise ApiError(422, "invalid_message", "Send either a message or an answer to a request, not both.")
    text = None if deciding else _new_message_text(body)
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
        prior_tools = []
        if deciding:
            prior_tools = await _decide(db, session, body.approval)
        elif text is None:
            last = await _newest(db, session.id)
            if last is None or last.role != "user":
                raise ApiError(409, "nothing_to_retry", "There's nothing to retry in this chat.")
        else:
            # Writing a new message instead of answering drops a waiting request.
            last = await _newest(db, session.id)
            if last is not None and (last.approval or {}).get("status") == "pending":
                last.approval = {**last.approval, "status": "skipped"}
            db.add(Message(session_id=session.id, role="user", content=text))
            session.last_message_at = func.now()
            if session.title == DEFAULT_TITLE:
                session.title = " ".join(text.split())[:TITLE_LENGTH]
            await db.commit()
            if session.purpose == "chat":  # describing an automation is not chatting with the agent
                posthog.capture("message_sent", session.user_id, agent_id=agent.id, session_id=session.id)
        # Read everything the stream needs now; the stream uses its own database sessions.
        turn = {"prior_tools": prior_tools, "session_id": session.id, "system_prompt": agent.system_prompt, "summary": session.summary}
        if session.purpose == "automation":
            turn |= await build_describe_turn(db, agent, session, body.timezone)
        else:
            ts = await build_toolset(db, agent, str(session.user_id), embedder=embedder, store=store)
            turn |= {"tools": ts.tools, "labels": ts.labels, "extra_instruction": "\n\n".join(ts.instructions) or None}
            if ts.forms:
                turn["forms"] = ts.forms
            turn["track"] = {"user_id": str(session.user_id), "agent_id": str(agent.id), "session_id": str(session.id),
                             "search_mode": agent.search_mode, "tool_kinds": ts.kinds}
        provider, model_id = agent.llm_provider, agent.llm_model
        agent_id, purpose = agent.id, session.purpose
    except BaseException:
        runner.end(session.id)
        raise

    try:
        model = build_model(provider, model_id, api_key)
    except Exception as exc:
        runner.logger.warning("A model could not be set up: %s", type(exc).__name__)
        return TurnResponse(runner.failed_turn(), session.id)
    # Only chat replies use the model-step cache: an automation's describe chat is left out.
    scope = f"{agent_id}:{provider}:{model_id}" if purpose == "chat" else None
    return TurnResponse(runner.run_turn(model=model, cache_scope=scope, **turn), session.id)
