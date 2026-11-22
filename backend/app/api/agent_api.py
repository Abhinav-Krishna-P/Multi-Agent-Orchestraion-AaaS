"""The owner's side of the Agent API: keys, settings and the call log."""
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.analytics import _zone
from app.api.deps import get_current_user, get_owned_agent
from app.core.api_keys import new_key
from app.core.errors import ApiError, not_found
from app.db.base import get_db
from app.db.models import Agent, AgentApiKey, AgentIntegration, ApiCall, User
from app.integrations import composio

router = APIRouter()
MAX_KEYS = 10
CALLS_SHOWN = 10
RECENT_CALLS = 5


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


def _local_day(tz: str):
    return func.date(func.timezone(tz, ApiCall.created_at))


@router.get("/agents/{agent_id}/api/calls/days")
async def list_call_days(tz: str = "UTC", agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    _zone(tz)
    day = _local_day(tz)
    failed = func.count().filter(ApiCall.outcome != "ok")
    rows = await db.execute(
        select(day, func.count(), failed).where(ApiCall.agent_id == agent.id).group_by(day).order_by(day.desc()).limit(366)
    )
    return {"days": [{"date": d.isoformat(), "calls": n, "failed": f} for d, n, f in rows]}


def _call_out(call: ApiCall, key_name: str | None) -> dict:
    return {
        "id": call.id, "created_at": call.created_at, "outcome": call.outcome, "duration_ms": call.duration_ms,
        "message": call.message, "reply": call.reply, "tools_used": call.tools_used, "sources": call.sources,
        "key_name": key_name,
    }


def _calls_query(*where):
    return (
        select(ApiCall, AgentApiKey.name)
        .outerjoin(AgentApiKey, AgentApiKey.id == ApiCall.key_id)
        .where(*where)
        .order_by(ApiCall.created_at.desc())
    )


@router.get("/agents/{agent_id}/api/calls/recent")
async def recent_calls(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(_calls_query(ApiCall.agent_id == agent.id).limit(RECENT_CALLS))).all()
    return {"calls": [_call_out(*row) for row in rows]}


@router.get("/agents/{agent_id}/api/calls")
async def list_calls(
    day: date, tz: str = "UTC", page: int = Query(1, ge=1),
    agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db),
) -> dict:
    _zone(tz)
    on_day = (ApiCall.agent_id == agent.id, _local_day(tz) == day)
    total = await db.scalar(select(func.count()).select_from(ApiCall).where(*on_day))
    rows = (await db.execute(_calls_query(*on_day).limit(CALLS_SHOWN).offset((page - 1) * CALLS_SHOWN))).all()
    return {"calls": [_call_out(*row) for row in rows], "page": page, "pages": -(-total // CALLS_SHOWN), "total": total}
