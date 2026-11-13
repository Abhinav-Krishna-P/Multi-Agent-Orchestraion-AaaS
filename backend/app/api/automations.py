from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_agent
from app.api.schemas import SessionOut
from app.api.sessions import agent_not_live
from app.core.errors import not_found
from app.db.base import get_db
from app.db.models import Agent, ChatSession

router = APIRouter()


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
