import json
import logging
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import runner
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
from app.rag.retrieve import document_names
from app.rag.vector_store import VectorStore, get_vector_store
from app.tools import forms, knowledge_base
from app.tools.http import ToolError, Unavailable

logger = logging.getLogger(__name__)
from app.tools.registry import APPROVAL_INSTRUCTION, CARDS_INSTRUCTION, REGISTRY, available, reconnect_instruction

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


async def _decide(db: AsyncSession, session: ChatSession, decision: ApprovalIn) -> list[dict]:
    """Records the user's answer to the newest message's request, runs the action if approved,
    and saves the answer as the user's message. Returns the action as the reply's first tool."""
    last = await _newest(db, session.id)
    if last is None or last.id != decision.message_id or last.role != "assistant" or (last.approval or {}).get("status") != "pending":
        raise _not_pending()
    request, approve = dict(last.approval), decision.decision == "approve"
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
        return []
    outcome = await _run_approved(db, session.agent, str(session.user_id), request)
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
        # Read everything the stream needs now; the stream uses its own database sessions.
        specs = [REGISTRY[name] for name in agent.tools if name in REGISTRY and available(REGISTRY[name])]
        turn = {
            "prior_tools": prior_tools,
            "session_id": session.id,
            "system_prompt": agent.system_prompt,
            "summary": session.summary,
            "tools": [spec.tool for spec in specs],
            "labels": {spec.name: spec.activity for spec in specs},
        }
        instructions = [CARDS_INSTRUCTION] if specs else []
        form_specs = {spec.name: spec for spec in specs if spec.form}
        if form_specs:
            turn["tools"].append(forms.build_ask_tool(form_specs))
            turn["labels"][forms.ASK_TOOL] = forms.ASK_LABEL
            turn["forms"] = form_specs
            instructions.append(forms.details_instruction(form_specs))
        # The knowledge-base tools exist only while there is something to search.
        ready_documents = await document_names(db, agent.id) if agent.kb_enabled else []
        if ready_documents:
            turn["tools"] += knowledge_base.build_kb_tools(agent.id, agent.search_mode, embedder=embedder, store=store)
            turn["labels"] |= knowledge_base.LABELS
            instructions.append(knowledge_base.kb_instruction(ready_documents, strict=agent.kb_strict))
        # The actions of the apps this agent is connected to. The account each runs on is bound here.
        if composio.enabled():
            connected = (await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id))).all()
            broken = [composio.APPS[row.app].name for row in connected if row.status == "expired" and row.app in composio.APPS]
            if broken:  # so the agent explains, instead of saying it has no such app
                instructions.append(reconnect_instruction(broken))
            app_tools, app_labels = await composio.build_tools(connected, str(session.user_id))
            turn["tools"] += app_tools
            turn["labels"] |= app_labels
            if any((tool.metadata or {}).get("approval") for tool in app_tools):
                instructions.append(APPROVAL_INSTRUCTION)
        turn["extra_instruction"] = "\n\n".join(instructions) or None
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
