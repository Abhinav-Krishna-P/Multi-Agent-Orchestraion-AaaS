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


async def check(automation: Automation) -> list[tuple[str, dict]]:
    """Runs the watched action and returns the items not seen before, oldest first (a reply lists
    the newest first), at most MAX_NEW_PER_CHECK. Any problem returns [] and is retried next time."""
    trigger, user_id = automation.trigger, str(automation.user_id)
    async with session_factory() as db:
        row = await db.scalar(select(AgentIntegration).where(
            AgentIntegration.agent_id == automation.agent_id, AgentIntegration.app == trigger.get("app"),
            AgentIntegration.status == "active"))
    if row is None:
        logger.info("A watch has no active connection to read from")
        return []
    try:
        data = await composio.run_action(trigger["action"], row.connected_account_id, user_id, trigger.get("arguments") or {})
    except ToolError as error:
        await composio.stopped_working(row.id, row.connected_account_id, user_id, str(error))
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
