"""The owner's side of the Agent API: keys, settings and the call log."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_agent
from app.core.api_keys import new_key
from app.core.errors import ApiError, not_found
from app.db.base import get_db
from app.db.models import Agent, AgentApiKey, AgentIntegration, ApiCall, User
from app.integrations import composio

router = APIRouter()
MAX_KEYS = 10
CALLS_SHOWN = 20


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class SettingsIn(BaseModel):
    actions: bool | None = None
    calls_per_minute: int | None = Field(default=None, ge=1, le=600)


def _key_out(key: AgentApiKey) -> dict:
    return {"id": key.id, "name": key.name, "hint": key.hint, "created_at": key.created_at, "last_used_at": key.last_used_at}


async def _write_actions(db: AsyncSession, agent: Agent) -> list[str]:
    """Display names of the agent's switched-on write actions: what a key's calls may run unasked."""
    rows = await db.scalars(
        select(AgentIntegration).where(AgentIntegration.agent_id == agent.id, AgentIntegration.status == "active")
    )
    names = []
    for row in rows:
        if not row.actions or row.app not in composio.APPS or not composio.enabled():
            continue
        try:
            found = await composio.actions(row.app)
        except Exception:  # an unreachable app is left out of the list, not an error for the page
            continue
        names += [
            f"{composio.APPS[row.app].name}: {a['name']}"
            for a in found
            if a["slug"] in row.actions and a["kind"] == "write"
        ]
    return names


async def _page(db: AsyncSession, agent: Agent) -> dict:
    keys = await db.scalars(
        select(AgentApiKey)
        .where(AgentApiKey.agent_id == agent.id, AgentApiKey.revoked_at.is_(None))
        .order_by(AgentApiKey.created_at.desc())
    )
    return {
        "settings": {"actions": agent.api_actions, "calls_per_minute": agent.api_calls_per_minute},
        "keys": [_key_out(k) for k in keys],
        "actions": await _write_actions(db, agent),
    }


@router.get("/agents/{agent_id}/api")
async def get_api(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    return await _page(db, agent)


@router.patch("/agents/{agent_id}/api")
async def update_api(body: SettingsIn, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    if body.actions is not None:
        agent.api_actions = body.actions
    if body.calls_per_minute is not None:
        agent.api_calls_per_minute = body.calls_per_minute
    await db.commit()
    return await _page(db, agent)


@router.post("/agents/{agent_id}/api/keys", status_code=201)
async def create_key(
    body: KeyIn,
    agent: Agent = Depends(get_owned_agent),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    active = await db.scalar(
        select(func.count()).select_from(AgentApiKey).where(AgentApiKey.agent_id == agent.id, AgentApiKey.revoked_at.is_(None))
    )
    if active >= MAX_KEYS:
        raise ApiError(409, "too_many_keys", f"An agent can have at most {MAX_KEYS} active keys. Revoke one first.")
    key, key_hash, hint = new_key()
    row = AgentApiKey(agent_id=agent.id, user_id=user.id, name=body.name, key_hash=key_hash, hint=hint)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {**_key_out(row), "key": key}


@router.delete("/agents/{agent_id}/api/keys/{key_id}", status_code=204)
async def revoke_key(key_id: uuid.UUID, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> Response:
    key = await db.scalar(
        select(AgentApiKey).where(
            AgentApiKey.id == key_id, AgentApiKey.agent_id == agent.id, AgentApiKey.revoked_at.is_(None)
        )
    )
    if key is None:
        raise not_found()
    key.revoked_at = datetime.now(UTC)
    await db.commit()
    return Response(status_code=204)


@router.get("/agents/{agent_id}/api/calls")
async def list_calls(
    before: datetime | None = None, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)
) -> dict:
    query = (
        select(ApiCall, AgentApiKey.name)
        .outerjoin(AgentApiKey, AgentApiKey.id == ApiCall.key_id)
        .where(ApiCall.agent_id == agent.id)
        .order_by(ApiCall.created_at.desc())
        .limit(CALLS_SHOWN + 1)
    )
    if before is not None:
        query = query.where(ApiCall.created_at < before)
    rows = (await db.execute(query)).all()
    return {
        "calls": [
            {
                "id": c.id, "created_at": c.created_at, "outcome": c.outcome, "duration_ms": c.duration_ms,
                "message": c.message, "reply": c.reply, "tools_used": c.tools_used, "sources": c.sources,
                "key_name": key_name,
            }
            for c, key_name in rows[:CALLS_SHOWN]
        ],
        "more": len(rows) > CALLS_SHOWN,
    }
