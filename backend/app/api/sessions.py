from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import posthog
from app.api.deps import get_owned_agent, get_owned_session
from app.api.schemas import MessageOut, SessionDetailOut, SessionOut
from app.core.errors import ApiError
from app.db.base import get_db
from app.db.models import Agent, ChatSession, Message

router = APIRouter()


def agent_not_live() -> ApiError:
    return ApiError(409, "agent_not_live", "This agent is stopped. Start it to chat.")


@router.get("/agents/{agent_id}/sessions", response_model=list[SessionOut])
async def list_sessions(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(ChatSession)
        .where(ChatSession.agent_id == agent.id, ChatSession.purpose == "chat")
        .order_by(ChatSession.last_message_at.desc())
    )
    return rows.all()


@router.post("/agents/{agent_id}/sessions", response_model=SessionOut, status_code=201)
async def create_session(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    if agent.status != "live":
        raise agent_not_live()
    session = ChatSession(agent_id=agent.id, user_id=agent.user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    posthog.capture("session_started", agent.user_id, agent_id=agent.id, session_id=session.id)
    return session


@router.get("/sessions/{session_id}", response_model=SessionDetailOut)
async def read_session(session: ChatSession = Depends(get_owned_session)):
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(session: ChatSession = Depends(get_owned_session), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Message).where(Message.session_id == session.id).order_by(Message.created_at))
    return rows.all()


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session: ChatSession = Depends(get_owned_session), db: AsyncSession = Depends(get_db)):
    await db.delete(session)
    await db.commit()
    return Response(status_code=204)
