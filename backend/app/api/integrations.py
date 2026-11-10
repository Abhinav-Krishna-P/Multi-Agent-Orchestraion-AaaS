"""The apps an agent is connected to: sign in, choose actions, disconnect."""
import asyncio
import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import posthog
from app.api.deps import get_owned_agent
from app.core.config import get_settings
from app.core.errors import ApiError, not_found
from app.db.base import get_db
from app.db.models import Agent, AgentIntegration
from app.integrations import composio
from app.tools.http import ToolError

router = APIRouter()
logger = logging.getLogger(__name__)
CHECK_SECONDS = 5  # the most the Apps step or the chat page waits for Composio when it opens


class ActionsIn(BaseModel):
    actions: list[str]


def _unavailable() -> ApiError:
    return ApiError(503, "integrations_unavailable", "App connections can't be reached right now. Try again in a moment.")


def _app(app: str) -> composio.App:
    """The app, if it is one the platform offers and connections are set up."""
    if app not in composio.APPS:
        raise not_found()
    if not composio.enabled():
        raise _unavailable()
    return composio.APPS[app]


async def _row(db: AsyncSession, agent: Agent, app: str) -> AgentIntegration | None:
    return await db.scalar(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id, AgentIntegration.app == app))


async def _entry(app: composio.App, row: AgentIntegration | None) -> dict:
    """One app as the wizard shows it. Actions are listed only once it is connected."""
    actions = []
    if row is not None and row.status == "active":
        actions = [
            {"slug": action["slug"], "name": action["name"], "description": action["description"],
             "kind": action["kind"], "on": action["slug"] in row.actions}
            for action in await composio.actions(app.slug)
        ]
    return {
        "app": app.slug, "name": app.name, "category": app.category, "logo": composio.logo(app.slug),
        "status": row.status if row else "none", "actions": actions,
    }


async def disconnect_quietly(account_id: str) -> None:
    """Removes a connection at Composio. Our own record goes either way: a connection we no
    longer list must never block the user, and nothing here can use it again."""
    try:
        await composio.disconnect(account_id)
    except ToolError:
        # The ID is Composio's handle, not a secret: it is what the owner needs to remove it by hand.
        logger.warning("A connection could not be removed at Composio: %s", account_id)


@router.get("/agents/{agent_id}/integrations")
async def list_integrations(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    if not composio.enabled():
        return {"enabled": False, "apps": []}
    rows = {row.app: row for row in await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id))}
    try:
        return {"enabled": True, "apps": [await _entry(app, rows.get(app.slug)) for app in composio.APPS.values()]}
    except ToolError as error:
        raise _unavailable() from error


@router.post("/agents/{agent_id}/integrations/check")
async def check_connections(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    """Asks Composio about each of the agent's connections, together and briefly, and saves
    any change, so a connection that broke since is shown as needing a reconnect."""
    if not composio.enabled():
        return {"enabled": False, "apps": []}
    rows = [row for row in await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id))
            if row.status in ("active", "expired")]

    async def status_of(row) -> str | None:
        try:
            return await composio.connection_status(row.connected_account_id, str(agent.user_id))
        except Exception:
            return None  # can't tell: leave it as it was

    try:
        found = await asyncio.wait_for(asyncio.gather(*(status_of(row) for row in rows)), CHECK_SECONDS)
    except TimeoutError:
        found = [None] * len(rows)
    for row, status in zip(rows, found):
        if status in ("active", "expired"):
            if status == "expired" and row.status != "expired":
                posthog.capture("connection_expired", agent.user_id, agent_id=agent.id, app=row.app)
            row.status = status
    await db.commit()
    return await list_integrations(agent, db)


@router.post("/agents/{agent_id}/integrations/{app}/connect")
async def connect(app: str, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    """Starts the app's sign-in. The connection counts only once Composio says it is active."""
    _app(app)
    row = await _row(db, agent, app)
    try:
        redirect_url, account_id = await composio.start_connection(
            app, str(agent.user_id), f"{get_settings().frontend_origin}/app/connected"
        )
    except ToolError as error:
        raise _unavailable() from error
    if row is None:
        db.add(AgentIntegration(agent_id=agent.id, user_id=agent.user_id, app=app, connected_account_id=account_id))
    else:
        await disconnect_quietly(row.connected_account_id)
        row.connected_account_id, row.status = account_id, "pending"  # the chosen actions are kept
    await db.commit()
    return {"redirect_url": redirect_url}


@router.post("/agents/{agent_id}/integrations/{app}/refresh")
async def refresh(app: str, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    """Asks Composio whether the sign-in finished (or whether a connection still works)."""
    spec = _app(app)
    row = await _row(db, agent, app)
    if row is None:
        raise not_found()
    try:
        status = await composio.connection_status(row.connected_account_id, str(agent.user_id))
        if status == "expired" and row.status == "active":
            posthog.capture("connection_expired", agent.user_id, agent_id=agent.id, app=app)
        row.status = status
        await db.commit()
        return await _entry(spec, row)
    except ToolError as error:
        raise _unavailable() from error


@router.put("/agents/{agent_id}/integrations/{app}/actions")
async def set_actions(
    body: ActionsIn, app: str, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)
) -> dict:
    spec = _app(app)
    row = await _row(db, agent, app)
    if row is None:
        raise not_found()
    if row.status != "active":
        raise ApiError(409, "not_connected", f"Connect {spec.name} before choosing its actions.")
    try:
        offered = {action["slug"] for action in await composio.actions(app)}
        if not set(body.actions) <= offered:
            raise ApiError(422, "invalid_actions", "One of those actions isn't available. Reload the page and try again.")
        row.actions = sorted(set(body.actions))
        await db.commit()
        return await _entry(spec, row)
    except ToolError as error:
        raise _unavailable() from error


@router.delete("/agents/{agent_id}/integrations/{app}", status_code=204)
async def disconnect(app: str, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    if app not in composio.APPS:
        raise not_found()
    row = await _row(db, agent, app)
    if row is None:
        raise not_found()
    if composio.enabled():
        await disconnect_quietly(row.connected_account_id)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)
