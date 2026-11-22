"""Watching a read action of a connected app for items it has not returned before."""
import hashlib
import json
import logging

from sqlalchemy import select, update

from app.db.base import session_factory
from app.db.models import AgentIntegration, Automation
from app.integrations import composio
from app.tools.http import ToolError

logger = logging.getLogger(__name__)

ID_FIELDS = ("id", "node_id", "url", "html_url", "name")
MAX_SEEN = 1000
MAX_NEW_PER_CHECK = 5


def _first_list(data) -> list[dict] | None:
    """The first non-empty list of objects at the top or one level down; [] if the reply has
    only empty lists; None if it has no list at all."""
    lists = [data] if isinstance(data, list) else [v for v in data.values() if isinstance(v, list)] if isinstance(data, dict) else []
    for found in lists:
        if found and isinstance(found[0], dict):
            return [item for item in found if isinstance(item, dict)]
    return [] if any(not found for found in lists) else None


def has_list(data) -> bool:
    return _first_list(data) is not None


def item_keys(data) -> list[tuple[str, dict]]:
    """(key, item) for each item of the first list of objects, at the top or one level down."""
    return [(_key(item), item) for item in _first_list(data) or []]


def _key(item: dict) -> str:
    for name in ID_FIELDS:
        if item.get(name) is not None:
            return str(item[name])
    return hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()


async def _connection(automation: Automation) -> AgentIntegration | None:
    async with session_factory() as db:
        return await db.scalar(select(AgentIntegration).where(
            AgentIntegration.agent_id == automation.agent_id, AgentIntegration.app == automation.trigger.get("app"),
            AgentIntegration.status == "active"))


async def _read(automation: Automation, row: AgentIntegration):
    trigger = automation.trigger
    return await composio.run_action(trigger["action"], row.connected_account_id, str(automation.user_id), trigger.get("arguments") or {})


async def _needs_reconnect(automation: Automation) -> None:
    """Turns the watch off with the reason the list shows: it can't run again until the app is reconnected."""
    app = composio.APPS.get(automation.trigger.get("app"))
    async with session_factory() as db:
        await db.execute(update(Automation).where(Automation.id == automation.id).values(
            status="error", status_reason=f"Reconnect {app.name if app else 'the app'}"))
        await db.commit()


async def newest(automation: Automation) -> dict | None:
    """The newest item the watched action returns now (a test run's event), or None if there is
    none or it can't be read. What has been seen is left alone: a test is not news."""
    row = await _connection(automation)
    if row is None:
        return None
    try:
        items = item_keys(await _read(automation, row))
    except ToolError:
        return None
    return items[0][1] if items else None


async def check(automation: Automation) -> list[tuple[str, dict]]:
    """Runs the watched action and returns the items not seen before, oldest first (a reply lists
    the newest first), at most MAX_NEW_PER_CHECK. A dead connection turns the watch off with
    "Reconnect"; any other problem returns [] and is retried next time."""
    trigger = automation.trigger
    row = await _connection(automation)
    if row is None:
        logger.info("A watch has no active connection to read from")
        await _needs_reconnect(automation)
        return []
    try:
        data = await _read(automation, row)
    except ToolError as error:
        if await composio.stopped_working(row.id, row.connected_account_id, str(automation.user_id), str(error)):
            await _needs_reconnect(automation)
        logger.warning("A watch could not read its app")
        return []
    if not has_list(data):  # an odd reply says nothing about what is new
        return []
    seen = set(trigger.get("seen") or [])
    fresh = [(key, item) for key, item in reversed(item_keys(data)) if key not in seen][:MAX_NEW_PER_CHECK]
    if fresh:
        async with session_factory() as db:
            # Re-read: the trigger may have changed while the action ran.
            current = await db.scalar(select(Automation.trigger).where(Automation.id == automation.id))
            if current is not None:
                kept = [*(current.get("seen") or []), *(key for key, _ in fresh)][-MAX_SEEN:]
                await db.execute(update(Automation).where(Automation.id == automation.id).values(trigger={**current, "seen": kept}))
                await db.commit()
    return fresh
