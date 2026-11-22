from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_claims, get_current_user
from app.api.schemas import UserOut
from app.core.security import Claims
from app.db.base import get_db
from app.db.models import User

router = APIRouter()


@router.get("/me", response_model=UserOut)
async def me(
    claims: Claims = Depends(get_claims),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """The signed-in user. Also refreshes their profile from Google and records the login."""
    user.email = claims.email
    user.name = claims.name
    user.avatar_url = claims.avatar_url
    user.last_login_at = func.now()
    await db.commit()
    await db.refresh(user)
    return user
