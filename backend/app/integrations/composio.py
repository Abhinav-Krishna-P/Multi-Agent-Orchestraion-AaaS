"""Outside apps (Gmail, Slack, ...) through Composio, which runs each app's sign-in and keeps
its tokens. The platform holds one Composio key and, per connection, only Composio's handle."""
import asyncio
import base64
import hashlib
import hmac
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy import update

from app.analytics import posthog
from app.core.config import get_settings
from app.db.base import session_factory
from app.db.models import AgentIntegration
from app.tools.http import NotFound, ToolError, fetch_json, wrap

logger = logging.getLogger(__name__)

SERVICE = "Composio"
BASE_URL = "https://backend.composio.dev/api/v3"
BASE_V31 = "https://backend.composio.dev/api/v3.1"  # webhook subscriptions live only here
WEBHOOK_TOLERANCE = 300  # seconds a signed event may be old (or early) before it is refused
MAX_ACTION_NAME = 64  # the longest tool name a model accepts
MAX_PAGES = 10  # of an app's action list; a paging fault at Composio must not loop forever
BUILD_SECONDS = 5  # how long a chat reply waits for Composio before going on without apps


@dataclass(frozen=True)
class App:
    slug: str  # Composio's name for it
    name: str
    category: str


# The apps offered in the wizard. All have Composio's ready-made sign-in.
APPS = {app.slug: app for app in (
    App("gmail", "Gmail", "Email and calendar"),
    App("googlecalendar", "Google Calendar", "Email and calendar"),
    App("outlook", "Outlook", "Email and calendar"),
    App("googledrive", "Google Drive", "Files and documents"),
    App("googledocs", "Google Docs", "Files and documents"),
    App("googlesheets", "Google Sheets", "Files and documents"),
    App("notion", "Notion", "Files and documents"),
    App("slack", "Slack", "Team chat"),
    App("github", "GitHub", "Work and projects"),
    App("linear", "Linear", "Work and projects"),
    App("trello", "Trello", "Work and projects"),
    App("hubspot", "HubSpot", "Work and projects"),
)}

_auth_configs: dict[str, str] = {}  # app -> the ID of its sign-in setup at Composio


def enabled() -> bool:
    return bool(get_settings().composio_api_key)


async def _call(method: str, path: str, *, params: dict | None = None, json: dict | None = None, cache: bool = False, base: str = BASE_URL):
    return await fetch_json(
        SERVICE, f"{base}{path}", method=method, params=params, json=json,
        headers={"x-api-key": get_settings().composio_api_key}, cache=cache,
    )


async def actions(app: str) -> list[dict]:
    """The app's actions the platform offers: the ones Composio marks as the useful ones.
    Each is a `read` (runs straight away) or a `write` (changes something, so it waits for the
    user's approval each time). Actions that delete are never offered."""
    found, cursor = [], None
    for _ in range(MAX_PAGES):
        page = await _call("GET", "/tools", params={"toolkit_slug": app, "limit": 200, **({"cursor": cursor} if cursor else {})}, cache=True)
        found += page.get("items") or []
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return [
        {"slug": tool["slug"], "name": tool.get("name") or tool["slug"], "description": tool.get("description") or "",
         "parameters": tool.get("input_parameters") or {"type": "object", "properties": {}},
         "kind": "read" if "readOnlyHint" in tool["tags"] else "write"}
        for tool in found
        if "important" in (tool.get("tags") or [])
        and "destructiveHint" not in tool["tags"]
        and not tool.get("is_deprecated")
        and len(tool["slug"]) <= MAX_ACTION_NAME
    ]


async def trigger_types(app: str) -> list[dict]:
    """The events the app can start an automation on, with each one's settings as a JSON schema."""
    found, cursor = [], None
    for _ in range(MAX_PAGES):
        page = await _call("GET", "/triggers_types", params={"toolkit_slugs": app, "limit": 50, **({"cursor": cursor} if cursor else {})}, cache=True)
        found += page.get("items") or []
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return [{"slug": t["slug"], "name": t.get("name") or t["slug"], "description": t.get("description") or "",
             "config": t.get("config") or {"type": "object", "properties": {}}} for t in found]


async def upsert_trigger(slug: str, user_id: str, account_id: str, config: dict) -> str:
    reply = await _call("POST", f"/trigger_instances/{slug}/upsert", json={
        "user_id": user_id, "connected_account_id": account_id, "trigger_config": config,
    })
    return reply["trigger_id"]


async def set_trigger_enabled(trigger_id: str, enabled: bool) -> None:
    await _call("PATCH", f"/trigger_instances/manage/{trigger_id}", json={"status": "enable" if enabled else "disable"})


async def delete_trigger(trigger_id: str) -> None:
    await _call("DELETE", f"/trigger_instances/manage/{trigger_id}")


async def create_webhook(url: str) -> tuple[str, str]:
    """Registers where Composio sends events. Returns the subscription ID and the secret that signs them."""
    reply = await _call("POST", "/webhook_subscriptions", base=BASE_V31, json={
        "webhook_url": url, "version": "V3",
        "enabled_events": ["composio.trigger.message", "composio.connected_account.expired"],
    })
    return reply["id"], reply["secret"]


async def update_webhook(subscription_id: str, url: str) -> None:
    await _call("PATCH", f"/webhook_subscriptions/{subscription_id}", base=BASE_V31, json={"webhook_url": url})


def verify_webhook(headers: Mapping[str, str], body: bytes, secret: str, now: float) -> bool:
    """Is this event signed with our secret and fresh? Refuses anything else."""
    msg_id, stamp, given = (headers.get(name) for name in ("webhook-id", "webhook-timestamp", "webhook-signature"))
    if not (secret and msg_id and stamp and given):
        return False
    try:
        if abs(now - float(stamp)) > WEBHOOK_TOLERANCE:
            return False
    except ValueError:
        return False
    expected = base64.b64encode(hmac.new(secret.encode(), f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    # The header may hold several entries ("v1,<sig> v1,<sig>"), e.g. while a secret is rotated.
    # Bytes, because compare_digest raises on a str with non-ASCII characters.
    return any(hmac.compare_digest(entry.partition(",")[2].encode(), expected.encode()) for entry in given.split())


async def _auth_config(app: str) -> str:
    if app not in _auth_configs:
        existing = (await _call("GET", "/auth_configs", params={"toolkit_slug": app})).get("items") or []
        managed = next(
            (item["id"] for item in existing
             if item.get("is_composio_managed") and (item.get("toolkit") or {}).get("slug") == app),
            None,
        )
        if managed is None:
            created = await _call("POST", "/auth_configs", json={"toolkit": {"slug": app}, "auth_config": {"type": "use_composio_managed_auth"}})
            managed = created["auth_config"]["id"]
        _auth_configs[app] = managed
    return _auth_configs[app]


async def start_connection(app: str, user_id: str, callback_url: str) -> tuple[str, str]:
    """Begins a sign-in. Returns the address to send the user to, and Composio's handle for
    the connection it will become."""
    link = await _call("POST", "/connected_accounts/link", json={
        "auth_config_id": await _auth_config(app), "user_id": user_id, "callback_url": callback_url,
    })
    return link["redirect_url"], link["connected_account_id"]


async def connection_status(account_id: str, user_id: str) -> str:
    """`active`, `pending` (still signing in) or `expired` (anything that needs a new sign-in)."""
    try:
        account = await _call("GET", f"/connected_accounts/{account_id}")
    except NotFound:
        return "expired"  # removed at Composio: only a new sign-in brings it back
    if account.get("user_id") != user_id:
        return "expired"  # not this user's connection: never usable here
    status = account.get("status")
    return "active" if status == "ACTIVE" else "pending" if status in ("INITIALIZING", "INITIATED") else "expired"


async def disconnect(account_id: str) -> None:
    await _call("DELETE", f"/connected_accounts/{account_id}")


async def run_action(slug: str, account_id: str, user_id: str, arguments: dict) -> dict:
    reply = await _call("POST", f"/tools/execute/{slug}", json={
        "connected_account_id": account_id, "user_id": user_id, "arguments": arguments,
    })
    if not reply.get("successful"):
        raise ToolError(str(reply.get("error") or "The app could not do that.")[:300])
    return reply.get("data") or {}


MAX_REPLY = 12000  # an app can return a whole mailbox; the model gets a bounded amount of it
CUT_NOTE = "\n(cut: the rest was too long to include)"


async def _run_for_model(app: App, slug: str, integration_id, account_id: str, user_id: str, arguments: dict) -> str:
    """Runs an action and words its result for the model: a dead connection says how to reconnect,
    and a long reply is cut."""
    try:
        data = await run_action(slug, account_id, user_id, arguments)
    except ToolError as error:
        if await stopped_working(integration_id, account_id, user_id, str(error)):
            raise ToolError(
                f"The {app.name} connection has stopped working. Ask the user to reconnect {app.name}: "
                f"tell them to press the \"Reconnect {app.name}\" button just above the message box."
            ) from None
        raise
    text = wrap(app.name, data)
    # Cut after the header, and said so: the model must not take part of a list for all of it.
    return text if len(text) <= MAX_REPLY else text[: MAX_REPLY - len(CUT_NOTE)] + CUT_NOTE


# Arguments that say where something goes or what it acts on. In an automation, outside content
# could talk the model into changing them, so they are fixed by the user or not allowed at all.
DESTINATION_ARG = re.compile(r"(^|_)(to|cc|bcc|recipients?|recipient_email|emails?|channel(_id)?|repo(sitory)?|owner|page_id|database_id|parent(_id)?|board(_id)?|list_id|team(_id)?|project(_id)?|calendar_id|spreadsheet_id|document_id|folder(_id)?|file_id|thread_id|user_id|assignees?|email_address(es)?|to_email|attendees|webhook_url)$", re.IGNORECASE)


def destination_args(action: dict) -> list[str]:
    return [name for name in ((action.get("parameters") or {}).get("properties") or {}) if DESTINATION_ARG.search(name)]


def _as_tool(app: App, action: dict, integration_id, account_id: str, user_id: str) -> BaseTool:
    """One app action as a tool. The account it runs on is fixed here, by the platform: the
    model supplies only the action's own arguments."""

    async def run(**arguments) -> str:
        return await _run_for_model(app, action["slug"], integration_id, account_id, user_id, arguments)

    return StructuredTool.from_function(
        coroutine=run, name=action["slug"].lower(), description=action["description"][:1000] or action["name"],
        args_schema=action["parameters"], metadata={"app": app.slug},
    )


def logo(app: str) -> str:
    return f"https://logos.composio.dev/api/{app}"


def _asks_approval(app: App, action: dict) -> BaseTool:
    """An action that changes something. Calling it runs nothing: it hands back the request,
    the reply ends there, and the user approves or rejects it in the chat. Only then, and
    only from the platform's own record of the request, does it run."""
    properties = (action["parameters"] or {}).get("properties") or {}

    async def ask(**arguments) -> tuple[str, dict]:
        return (
            "The user is now being asked to approve this. Stop here and wait for their answer.",
            {"approval": {
                "app": app.slug, "app_name": app.name, "logo": logo(app.slug),
                "action": action["slug"], "action_name": action["name"], "arguments": arguments,
                "labels": {name: (properties.get(name) or {}).get("title") or name for name in arguments},
                "order": [name for name in properties if name in arguments] + [name for name in arguments if name not in properties],
                "status": "pending",
            }},
        )

    return StructuredTool.from_function(
        coroutine=ask, name=action["slug"].lower(), description=action["description"][:1000] or action["name"],
        args_schema=action["parameters"], response_format="content_and_artifact", metadata={"approval": True, "app": app.slug},
    )


def _runs_locked(app: App, action: dict, integration_id, account_id: str, user_id: str, locked: dict) -> BaseTool:
    """An action that changes something, run straight away in an automation: nobody is there to
    approve it. Locked arguments are set to the user's values and every other destination is
    removed, so the model cannot send anything anywhere the user did not say."""

    async def run(**arguments) -> tuple[str, dict]:
        sent = {name: value for name, value in arguments.items() if name in locked or not DESTINATION_ARG.search(name)} | locked
        overridden = [name for name, value in arguments.items() if sent.get(name) != value]
        text = await _run_for_model(app, action["slug"], integration_id, account_id, user_id, sent)
        return text, {"overridden": overridden}

    return StructuredTool.from_function(
        coroutine=run, name=action["slug"].lower(), description=action["description"][:1000] or action["name"],
        args_schema=action["parameters"], response_format="content_and_artifact", metadata={"app": app.slug},
    )


# Composio keeps calling a connection ACTIVE after the user revokes its access at Google (seen
# live, 2026-11-20): only the action's own error says so. These are the sign-in failures.
_SIGN_IN_ERROR = re.compile(
    r"refresh(ing)?[ _]the[ _]access[ _]token|refresh[ _]token|invalid[ _]grant|unauthori[sz]ed|\b40[13]\b"
    r"|invalid (authentication )?credentials|token has been (expired|revoked)|expired or revoked",
    re.IGNORECASE,
)


def is_sign_in_error(text: str) -> bool:
    return bool(_SIGN_IN_ERROR.search(text or ""))


async def stopped_working(integration_id, account_id: str, user_id: str, error: str = "") -> bool:
    """After a failed action: is the connection itself dead? Yes if the error is a sign-in
    failure, or Composio says so. If it is, record it, so the chat and the Apps step show
    Reconnect and the app's actions are no longer offered."""
    if not is_sign_in_error(error):
        try:
            if await connection_status(account_id, user_id) != "expired":
                return False
        except ToolError:
            return False  # Composio can't be asked right now: say nothing about the connection
    await mark_expired(AgentIntegration.id == integration_id)
    return True


async def mark_expired(*conditions) -> list[AgentIntegration]:
    """Records the matching connections as expired, so the chat and the Apps step show Reconnect
    and the app's actions are no longer offered. Returns the ones that changed."""
    async with session_factory() as db:
        changed = (await db.execute(
            update(AgentIntegration)
            .where(*conditions, AgentIntegration.status != "expired")
            .values(status="expired")
            .returning(AgentIntegration.user_id, AgentIntegration.agent_id, AgentIntegration.app, AgentIntegration.actions)
        )).all()
        await db.commit()
    for row in changed:  # counted when it breaks, not each time it is found broken
        posthog.capture("connection_expired", row.user_id, agent_id=row.agent_id, app=row.app)
    return changed


async def build_tools(
    integrations: Sequence[AgentIntegration], user_id: str, *, locked: dict[str, dict] | None = None
) -> tuple[list[BaseTool], dict[str, str]]:
    """The switched-on actions of the agent's working connections, as tools, with the words
    shown in chat while each one runs. With `locked` (an automation), writes run directly with
    those argument values fixed; without it, they ask for approval."""
    rows = [row for row in integrations if row.app in APPS and row.status == "active" and row.actions]

    async def offered_by(row) -> dict:
        try:
            return {action["slug"]: action for action in await actions(row.app)}
        except Exception as error:  # unreachable, or an answer in a shape we don't know
            logger.warning("Could not list %s actions: %s", row.app, type(error).__name__)
            return {}  # the chat goes on without this app

    # Every reply waits here before its first word, so the apps are asked together and only
    # briefly: a slow Composio costs the reply its apps, not the user a minute of silence.
    try:
        listed = await asyncio.wait_for(asyncio.gather(*(offered_by(row) for row in rows)), BUILD_SECONDS)
    except TimeoutError:
        logger.warning("Composio was too slow; replying without app actions")
        return [], {}
    tools, labels = [], {}
    for row, offered in zip(rows, listed):
        app = APPS[row.app]
        for slug in row.actions:
            if slug not in offered:  # an action Composio has since withdrawn is quietly dropped
                continue
            if offered[slug]["kind"] == "write":
                if locked is None:
                    tools.append(_asks_approval(app, offered[slug]))
                    labels[slug.lower()] = "Asking for your approval…"
                else:
                    tools.append(_runs_locked(app, offered[slug], row.id, row.connected_account_id, user_id, locked.get(slug.lower(), {})))
                    labels[slug.lower()] = f"Using {app.name}…"
            else:
                tools.append(_as_tool(app, offered[slug], row.id, row.connected_account_id, user_id))
                labels[slug.lower()] = f"Using {app.name}…"
    return tools, labels
