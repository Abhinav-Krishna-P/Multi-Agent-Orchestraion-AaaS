from fastapi import APIRouter, Depends

from app.agent.personas import PERSONAS
from app.api.deps import get_current_user
from app.api.schemas import PersonaOut
from app.db.models import User

router = APIRouter()


@router.get("/personas", response_model=list[PersonaOut])
async def list_personas(_: User = Depends(get_current_user)):
    return PERSONAS
