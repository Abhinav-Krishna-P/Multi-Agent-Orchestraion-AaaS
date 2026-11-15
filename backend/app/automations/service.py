"""Turning an approved proposal into a live automation, and switching or removing one."""
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.toolset import build_toolset
from app.analytics import posthog
from app.automations.schedule import next_run
from app.automations.watch import has_list, item_keys
from app.db.models import AgentIntegration, Automation, ChatSession
from app.integrations import composio
from app.tools.http import ToolError


logger = logging.getLogger(__name__)


def _trigger_id(automation: Automation) -> str | None:
    return automation.trigger.get("composio_trigger_id") if automation.trigger_kind == "event" else None


async def _used_elsewhere(db, trigger_id: str, these: list[Automation], *conditions) -> bool:
    """Composio reuses one trigger for the same settings, so automations can share it."""
    return await db.scalar(select(Automation.id).where(
        Automation.trigger["composio_trigger_id"].astext == trigger_id, Automation.id.not_in([a.id for a in these]),
        *conditions).limit(1)) is not None


async def set_triggers_enabled(db, automations: list[Automation], enabled: bool) -> None:
    """Turns the automations' Composio triggers on or off, keeping on any that another active
    automation still uses. Never blocks the user: a trigger left on only delivers events that a
    paused automation skips."""
    ids = {_trigger_id(a) for a in automations} - {None}
    if not ids or not composio.enabled():
        return
    for trigger_id in ids:
        if not enabled and await _used_elsewhere(db, trigger_id, automations, Automation.status == "active"):
            continue
        try:
            await composio.set_trigger_enabled(trigger_id, enabled)
        except ToolError:
            logger.warning("A trigger could not be turned %s at Composio: %s", "on" if enabled else "off", trigger_id)


async def delete_triggers(db, automations: list[Automation]) -> None:
    """Deletes the automations' Composio triggers (best effort), keeping any that an automation
    outside this list still uses. The rows themselves are the caller's to remove."""
    ids = {_trigger_id(a) for a in automations} - {None}
    if not ids or not composio.enabled():
        return
    for trigger_id in ids:
        if await _used_elsewhere(db, trigger_id, automations):
            continue
        try:
            await composio.delete_trigger(trigger_id)
        except ToolError:
            logger.warning("A trigger could not be deleted at Composio: %s", trigger_id)


async def pause_for_stopped_agent(db, agent_id) -> None:
    automations = (await db.scalars(select(Automation).where(Automation.agent_id == agent_id))).all()
    for automation in automations:
        if automation.status != "paused":
            automation.status, automation.status_reason = "paused", "Agent was stopped"
    await set_triggers_enabled(db, automations, False)


def _failed(reason: str) -> dict:
    return {"outcome": "failed", "reason": reason}


async def activate(db, session: ChatSession, proposal: dict) -> dict:
    """Checks the proposal still holds, starts what the trigger needs, and saves the automation."""
    agent, user_id = session.agent, str(session.user_id)
    if agent.status != "live":
        return _failed("This agent isn't live any more.")
    toolset = await build_toolset(db, agent, user_id, embedder=None, store=None)
    available = {tool.name.lower() for tool in toolset.tools}
    missing = [name for name in proposal["tools"] if name not in available]
    if missing:
        return _failed(f"{', '.join(missing)} isn't available to this agent any more.")

    kind, trigger = proposal["trigger_kind"], dict(proposal["trigger"])
    if kind == "schedule":  # the chat's zone, never one the model supplied
        trigger = {"every_minutes": trigger["every_minutes"]} if "every_minutes" in trigger else {
            "cron": trigger["cron"], "timezone": proposal["timezone"]}
    else:
        app = composio.APPS[trigger["app"]]
        row = await db.scalar(select(AgentIntegration).where(
            AgentIntegration.agent_id == agent.id, AgentIntegration.app == trigger["app"], AgentIntegration.status == "active"))
        if row is None or not composio.enabled():
            return _failed(f"{app.name} isn't connected any more.")
        try:
            if kind == "event":
                trigger["composio_trigger_id"] = await composio.upsert_trigger(
                    trigger["trigger_slug"], user_id, row.connected_account_id, trigger.get("config") or {})
            else:  # what is there now is not news
                data = await composio.run_action(trigger["action"], row.connected_account_id, user_id, trigger.get("arguments") or {})
                if not has_list(data):  # no baseline would make the first check fire for everything there is
                    return _failed(f"That {app.name} action doesn't return a list to watch.")
                trigger["seen"] = [key for key, _ in item_keys(data)]
        except ToolError:
            return _failed(f"Couldn't set up {app.name} to send its events. Try again." if kind == "event"
                           else f"Couldn't read {app.name} to start watching. Try again.")

    automation = Automation(
        user_id=session.user_id, agent_id=agent.id, name=proposal["name"], task=proposal["task"],
        trigger_text=proposal["trigger_text"], trigger_kind=kind, trigger=trigger, tools=proposal["tools"],
        locked=proposal["locked"], status="active", conversation_id=session.id,
        next_run_at=next_run(kind, trigger, datetime.now(UTC)),
    )
    db.add(automation)
    await db.commit()
    posthog.capture("automation_created", session.user_id, agent_id=agent.id, automation_id=automation.id, trigger_kind=kind)
    return {"outcome": "done", "automation_id": str(automation.id)}
