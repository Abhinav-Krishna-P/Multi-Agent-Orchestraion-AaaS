"""Shared request dependencies: who is calling, and what they own."""
import asyncio
import uuid

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.core.security import Claims, unauthorized, uses_shared_secret, verify_token
from app.db.base import get_db
from app.db.models import Agent, ChatSession, User


async def get_claims(authorization: str | None = Header(default=None)) -> Claims:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized()
    if uses_shared_secret():
        return verify_token(token)
    return await asyncio.to_thread(verify_token, token)


async def get_current_user(claims: Claims = Depends(get_claims), db: AsyncSession = Depends(get_db)) -> User:
    user = await db.get(User, claims.sub)
    if user is None:
        await db.execute(
            insert(User)
            .values(id=claims.sub, email=claims.email, name=claims.name, avatar_url=claims.avatar_url)
            .on_conflict_do_nothing(index_elements=[User.id])
        )
        await db.commit()
        user = await db.get(User, claims.sub)
    return user


async def get_owned_agent(
    agent_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> Agent:
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.user_id == user.id))
    if agent is None:
        raise not_found()
    return agent


async def get_owned_session(
    session_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> ChatSession:
    """The chat, with its agent loaded, if it belongs to the caller."""
    session = await db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user.id))
    if session is None:
        raise not_found()
    return session
