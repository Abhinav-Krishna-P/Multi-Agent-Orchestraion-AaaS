from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.llm import KeyValidator, get_key_validator
from app.api.deps import get_current_user
from app.api.schemas import LlmKeyIn, LlmKeyOut
from app.core.encryption import encrypt_key, key_hint
from app.core.errors import ApiError, not_found
from app.core.llm_catalog import CATALOG, is_provider
from app.db.base import get_db
from app.db.models import LlmKey, User

router = APIRouter()


def _invalid_key() -> ApiError:
    return ApiError(422, "invalid_api_key", "This key didn't work. Check it and try again.")


@router.get("/llm-models")
async def llm_models(_: User = Depends(get_current_user)) -> dict:
    return CATALOG


@router.get("/llm-keys", response_model=list[LlmKeyOut])
async def list_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(LlmKey).where(LlmKey.user_id == user.id).order_by(LlmKey.provider))
    return rows.all()


@router.put("/llm-keys/{provider}", response_model=LlmKeyOut)
async def save_key(
    provider: str,
    body: LlmKeyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    validate: KeyValidator = Depends(get_key_validator),
):
    if not is_provider(provider):
        raise not_found()
    api_key = body.api_key.strip()
    if not api_key or not await validate(provider, api_key):
        raise _invalid_key()
    values = {"encrypted_key": encrypt_key(api_key), "key_hint": key_hint(api_key)}
    statement = (
        insert(LlmKey)
        .values(user_id=user.id, provider=provider, **values)
        .on_conflict_do_update(constraint="uq_llm_keys_user_provider", set_={**values, "updated_at": func.now()})
        .returning(LlmKey)
    )
    row = (await db.scalars(statement, execution_options={"populate_existing": True})).one()
    await db.commit()
    return row


@router.delete("/llm-keys/{provider}", status_code=204)
async def delete_key(provider: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not is_provider(provider):
        raise not_found()
    await db.execute(delete(LlmKey).where(LlmKey.user_id == user.id, LlmKey.provider == provider))
    await db.commit()
    return Response(status_code=204)
