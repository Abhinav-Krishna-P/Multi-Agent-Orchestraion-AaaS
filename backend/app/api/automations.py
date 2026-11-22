import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import posthog
from app.api.deps import get_current_user, get_owned_agent
from app.api.schemas import AutomationOut, AutomationStatusIn, RunOut, SessionOut
from app.api.sessions import agent_not_live
from app.automations import service
from app.automations.run import run_automation, spawn_run
from app.automations.schedule import next_run
from app.core.errors import not_found
from app.db.base import get_db
from app.db.models import Agent, Automation, AutomationRun, ChatSession, User

router = APIRouter()
RUNS_SHOWN = 20


async def get_owned_automation(
    automation_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Automation:
    automation = await db.scalar(select(Automation).where(Automation.id == automation_id, Automation.user_id == user.id))
    if automation is None:
        raise not_found()
    return automation


async def _recent_runs(db: AsyncSession, automation_id: uuid.UUID, limit: int) -> list[AutomationRun]:
    return (await db.scalars(
        select(AutomationRun).where(AutomationRun.automation_id == automation_id)
        .order_by(AutomationRun.started_at.desc()).limit(limit)
    )).all()


async def _out(db: AsyncSession, automation: Automation) -> AutomationOut:
    out = AutomationOut.model_validate(automation)
    runs = await _recent_runs(db, automation.id, 1)
    out.last_run = RunOut.model_validate(runs[0]) if runs else None
    return out


@router.get("/agents/{agent_id}/automations", response_model=list[AutomationOut])
async def list_automations(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Automation).where(Automation.agent_id == agent.id).order_by(Automation.created_at.desc()))
    return [await _out(db, row) for row in rows.all()]


@router.patch("/automations/{automation_id}", response_model=AutomationOut)
async def set_status(
    body: AutomationStatusIn, automation: Automation = Depends(get_owned_automation), db: AsyncSession = Depends(get_db)
):
    if body.status == "active":
        agent = await db.get(Agent, automation.agent_id)
        if agent.status != "live":
            raise agent_not_live()
        automation.failure_streak, automation.status_reason = 0, None
        automation.next_run_at = next_run(automation.trigger_kind, automation.trigger, datetime.now(UTC))
    automation.status = body.status
    await db.commit()
    await db.refresh(automation)
    await service.set_triggers_enabled(db, [automation], body.status == "active")
    posthog.capture("automation_status_changed", automation.user_id, agent_id=automation.agent_id,
                    automation_id=automation.id, status=automation.status)
    return await _out(db, automation)


@router.delete("/automations/{automation_id}", status_code=204)
async def delete_automation(automation: Automation = Depends(get_owned_automation), db: AsyncSession = Depends(get_db)):
    await service.delete_triggers(db, [automation])
    await db.delete(automation)
    await db.commit()
    return Response(status_code=204)


@router.post("/automations/{automation_id}/test", status_code=202)
async def test_automation(automation: Automation = Depends(get_owned_automation), db: AsyncSession = Depends(get_db)) -> dict:
    row = AutomationRun(automation_id=automation.id, user_id=automation.user_id, source="test")
    db.add(row)
    await db.commit()
    spawn_run(run_automation(automation.id, "test", wait=True, run_id=row.id))
    return {"run_id": str(row.id)}


@router.get("/automations/{automation_id}/runs", response_model=list[RunOut])
async def list_runs(automation: Automation = Depends(get_owned_automation), db: AsyncSession = Depends(get_db)):
    return await _recent_runs(db, automation.id, RUNS_SHOWN)


@router.post("/agents/{agent_id}/automation-conversations", response_model=SessionOut, status_code=201)
async def start_conversation(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    if agent.status != "live":
        raise agent_not_live()
    session = ChatSession(agent_id=agent.id, user_id=agent.user_id, purpose="automation")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/agents/{agent_id}/automation-conversations/latest", response_model=SessionOut)
async def latest_conversation(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    session = await db.scalar(
        select(ChatSession)
        .where(ChatSession.agent_id == agent.id, ChatSession.purpose == "automation")
        .order_by(ChatSession.created_at.desc())
        .limit(1)
    )
    if session is None:
        raise not_found()
    return session
