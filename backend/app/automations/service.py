"""Turning an approved proposal into a live automation."""
from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.toolset import build_toolset
from app.analytics import posthog
from app.automations.schedule import next_run
from app.automations.watch import has_list, item_keys
from app.db.models import AgentIntegration, Automation, ChatSession
from app.integrations import composio
from app.tools.http import ToolError


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
            return _failed(f"Couldn't set up {app.name} to start watching. Try again." if kind == "event"
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
