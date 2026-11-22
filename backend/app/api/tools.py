from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_owned_agent
from app.api.schemas import AgentOut, AgentToolsIn
from app.core.errors import ApiError
from app.db.base import get_db
from app.db.models import Agent, AgentTool, User
from app.tools.registry import REGISTRY, available, catalog

router = APIRouter()


@router.get("/tools")
async def list_tools(_: User = Depends(get_current_user)) -> dict:
    return catalog()


@router.put("/agents/{agent_id}/tools", response_model=AgentOut)
async def set_agent_tools(
    body: AgentToolsIn, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)
):
    """Replaces the set of tools switched on for the agent."""
    wanted = set(body.tools)
    have = {row.tool_name for row in agent.tool_rows}
    # Only tools being added are checked. One the agent already has may have lost its key
    # since; the wizard still sends it back, and refusing that would block every save.
    if not (wanted - have) <= {name for name, spec in REGISTRY.items() if available(spec)}:
        raise ApiError(422, "invalid_tools", "One of those tools isn't available. Reload the page and try again.")
    # Rows that stay are kept as they are: re-inserting one would break the unique rule mid-save.
    agent.tool_rows = [row for row in agent.tool_rows if row.tool_name in wanted] + [
        AgentTool(tool_name=name) for name in sorted(wanted - have)
    ]
    await db.commit()
    await db.refresh(agent)
    return agent
