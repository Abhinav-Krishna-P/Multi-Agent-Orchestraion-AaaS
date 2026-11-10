"""Usage analytics in PostHog: events sent from the backend as things happen, and the numbers
read back for the Analytics page. No user content is ever sent: only IDs, names of tools and
apps, counts, outcomes and times."""
import asyncio
import logging
import uuid
from typing import Any

from app.core.config import get_settings
from app.tools.http import ToolError, fetch_json

logger = logging.getLogger(__name__)
SERVICE = "PostHog"

# Every property an event may carry. Anything else is refused, so message text, tool arguments,
# document names or email addresses cannot slip into analytics by accident.
ALLOWED = frozenset({
    "agent_id", "session_id", "tool_name", "tool_type", "app", "success", "duration_ms", "search_mode",
    "results_count", "decision", "outcome", "source_type", "chunk_count", "status",
})

recorder: list[dict] | None = None  # tests put a list here: events are kept instead of sent
_pending: set[asyncio.Task] = set()


def _plain(value: Any) -> Any:
    return str(value) if isinstance(value, uuid.UUID) else value


def capture(event: str, user_id, **properties) -> None:
    """Sends one event in the background and returns at once. A PostHog failure is logged and
    dropped: analytics must never slow or break what the user is doing."""
    unknown = set(properties) - ALLOWED
    if unknown:
        raise ValueError(f"Not an analytics property: {', '.join(sorted(unknown))}")
    user = str(user_id)
    payload = {
        "event": event, "distinct_id": user,
        "properties": {"user_id": user, **{key: _plain(value) for key, value in properties.items() if value is not None},
                       "$process_person_profile": False},  # no person profiles: events only
    }
    if recorder is not None:
        recorder.append(payload)
        return
    settings = get_settings()
    if not settings.posthog_api_key:
        return
    try:
        task = asyncio.get_running_loop().create_task(_send({"api_key": settings.posthog_api_key, **payload}))
    except RuntimeError:
        return  # not in async code: nothing to send it with
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _send(body: dict) -> None:
    try:
        await fetch_json(SERVICE, f"{get_settings().posthog_host.rstrip('/')}/i/v0/e/", method="POST", json=body, cache=False)
    except ToolError:
        pass  # already logged, without the key
    except Exception as error:
        logger.warning("An analytics event could not be sent: %s", type(error).__name__)


async def flush() -> None:
    """Waits for events still being sent (tests, and shutdown)."""
    while _pending:
        await asyncio.gather(*list(_pending), return_exceptions=True)


def queries_enabled() -> bool:
    settings = get_settings()
    return bool(settings.posthog_personal_api_key and settings.posthog_project_id)


async def query(sql: str, values: dict) -> list[list]:
    """Runs one HogQL query. Values are passed as placeholders ({name} in the text), never
    pasted into it. Uses the personal key, which can read; it never reaches the browser."""
    settings = get_settings()
    # Events go to the ingestion host (us.i.posthog.com); queries go to the app host (us.posthog.com).
    host = settings.posthog_host.rstrip("/").replace(".i.posthog.com", ".posthog.com")
    reply = await fetch_json(
        SERVICE, f"{host}/api/projects/{settings.posthog_project_id}/query/", method="POST",
        json={"query": {"kind": "HogQLQuery", "query": sql, "values": values}},
        headers={"Authorization": f"Bearer {settings.posthog_personal_api_key}"}, cache=False,
    )
    return reply.get("results") or []
