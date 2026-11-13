"""Composio pushes app events here: no sign-in, the signature is the credential."""
import json
import time

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.automations.run import MAX_EVENT_CHARS, run_automation, spawn_run
from app.core.config import get_settings
from app.db.base import session_factory
from app.db.models import Agent, Automation
from app.integrations import composio

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/composio")
async def composio_event(request: Request) -> dict:
    body = await request.body()
    if not composio.verify_webhook(request.headers, body, get_settings().composio_webhook_secret, time.time()):
        raise HTTPException(401, "Bad signature")
    try:
        event = json.loads(body)
    except ValueError:
        return {"ok": True}
    if not isinstance(event, dict):
        return {"ok": True}
    kind = event.get("type")
    if kind == "composio.trigger.message":
        await _start_runs(event)
    elif kind == "composio.connected_account.expired":
        await _expire(event)
    return {"ok": True}


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


async def _start_runs(event: dict) -> None:
    meta, data = _dict(event.get("metadata")), event.get("data")
    trigger_id = meta.get("trigger_id")
    if not trigger_id:
        return
    # The run itself skips automations that are not active or whose agent is not live.
    async with session_factory() as db:
        ids = (await db.scalars(
            select(Automation.id).join(Agent, Agent.id == Automation.agent_id).where(
                Automation.status == "active", Agent.status == "live", Automation.trigger_kind == "event",
                Automation.trigger["composio_trigger_id"].astext == str(trigger_id)))).all()
    if not isinstance(data, dict):
        data = {"data": data}
    # Cut here as well as in the run: the stored copy of the event is bounded too.
    if len(json.dumps(data, default=str)) > MAX_EVENT_CHARS:
        data = {"truncated": json.dumps(data, default=str)[:MAX_EVENT_CHARS]}
    key = str(meta.get("log_id") or event.get("id") or "")
    for id_ in ids:
        spawn_run(run_automation(id_, "event", event=data, event_key=key or None, wait=True))


async def _expire(event: dict) -> None:
    meta, data = _dict(event.get("metadata")), _dict(event.get("data"))
    account = meta.get("connected_account_id") or data.get("connected_account_id") or data.get("id")
    if not account:
        return
    changed = await composio.mark_expired(composio.AgentIntegration.connected_account_id == str(account))
    for row in changed:
        app = composio.APPS.get(row.app)
        if app is None:
            continue
        mine = {slug.lower() for slug in row.actions}
        async with session_factory() as db:
            for automation in await db.scalars(select(Automation).where(Automation.agent_id == row.agent_id)):
                if mine.intersection(automation.tools) or automation.trigger.get("app") == row.app:
                    automation.status, automation.status_reason = "error", f"Reconnect {app.name}"
            await db.commit()
