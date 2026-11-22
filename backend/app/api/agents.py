from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.personas import get_persona
from app.api.deps import get_current_user, get_owned_agent
from app.api.schemas import AgentCreate, AgentOut, AgentUpdate
from app.core.errors import ApiError
from app.core.llm_catalog import is_valid_model
from app.db.base import get_db
from app.api.integrations import disconnect_quietly
from app.automations.service import delete_triggers, pause_for_stopped_agent
from app.db.models import Agent, AgentIntegration, Automation, Document, User
from app.integrations import composio
from app.rag.vector_store import VectorStore, VectorStoreUnavailable, get_vector_store

router = APIRouter()


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Agent).where(Agent.user_id == user.id).order_by(Agent.created_at.desc()))
    return rows.all()


@router.post("/agents", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    agent = Agent(user_id=user.id, name=body.name, description=body.description)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def read_agent(agent: Agent = Depends(get_owned_agent)):
    return agent


def _apply_behavior(agent: Agent, body: AgentUpdate, sent: set[str]) -> None:
    """Persona and prompt rules: a persona fills the prompt unless edited text is sent too;
    without a persona the prompt is the user's own, mirrored into custom_prompt."""
    if "persona_key" in sent:
        if body.persona_key is not None:
            persona = get_persona(body.persona_key)
            if persona is None:
                raise ApiError(422, "invalid_persona", "That behavior isn't available. Choose another one.")
            if "system_prompt" not in sent:
                agent.system_prompt = persona.prompt
        agent.persona_key = body.persona_key
    if "system_prompt" in sent and body.system_prompt is not None:
        agent.system_prompt = body.system_prompt
    if sent & {"persona_key", "system_prompt"}:
        agent.custom_prompt = agent.system_prompt if agent.persona_key is None else None


def _apply_model(agent: Agent, body: AgentUpdate, sent: set[str]) -> None:
    if not sent & {"llm_provider", "llm_model"}:
        return
    both_sent = {"llm_provider", "llm_model"} <= sent
    clearing = both_sent and body.llm_provider is None and body.llm_model is None
    if not clearing and not (
        both_sent and body.llm_provider and body.llm_model and is_valid_model(body.llm_provider, body.llm_model)
    ):
        raise ApiError(422, "invalid_model", "Choose a provider and one of its models.")
    agent.llm_provider = body.llm_provider
    agent.llm_model = body.llm_model


@router.patch("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    body: AgentUpdate, agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)
):
    sent = body.model_fields_set
    if "name" in sent and body.name is not None:
        agent.name = body.name
    if "description" in sent and body.description is not None:
        agent.description = body.description
    if "kb_enabled" in sent and body.kb_enabled is not None:
        agent.kb_enabled = body.kb_enabled
    if "kb_strict" in sent and body.kb_strict is not None:
        agent.kb_strict = body.kb_strict
    if "search_mode" in sent and body.search_mode is not None:
        agent.search_mode = body.search_mode
    _apply_behavior(agent, body, sent)
    _apply_model(agent, body, sent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent: Agent = Depends(get_owned_agent),
    db: AsyncSession = Depends(get_db),
    store: VectorStore = Depends(get_vector_store),
):
    # Postgres removes the agent's documents and chunks by cascade, but cannot reach Chroma:
    # remove the vectors first, and delete nothing if that fails.
    has_documents = await db.scalar(select(func.count()).select_from(Document).where(Document.agent_id == agent.id))
    if has_documents:
        try:
            await store.delete_agent(agent.id)
        except VectorStoreUnavailable as error:
            raise ApiError(
                503, "vector_store_unavailable",
                "The knowledge base can't be reached right now. Try again in a moment.",
            ) from error
    # The agent's app connections live at Composio too; its rows here go by cascade.
    if composio.enabled():
        for row in await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id)):
            await disconnect_quietly(row.connected_account_id)
    # Likewise its automations' triggers; the rows go by cascade.
    await delete_triggers(db, (await db.scalars(select(Automation).where(Automation.agent_id == agent.id))).all())
    await db.delete(agent)
    await db.commit()
    return Response(status_code=204)


@router.post("/agents/{agent_id}/deploy", response_model=AgentOut)
async def deploy_agent(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    """Draft or stopped -> live. A missing model or key is a warning in the UI, not a blocker here."""
    if not agent.system_prompt.strip():
        raise ApiError(409, "agent_incomplete", "Choose a behavior for this agent before deploying it.")
    agent.status = "live"
    await db.commit()
    await db.refresh(agent)
    return agent


@router.post("/agents/{agent_id}/stop", response_model=AgentOut)
async def stop_agent(agent: Agent = Depends(get_owned_agent), db: AsyncSession = Depends(get_db)):
    if agent.status != "live":
        raise ApiError(409, "agent_not_live", "This agent isn't running.")
    agent.status = "stopped"
    await pause_for_stopped_agent(db, agent.id)
    await db.commit()
    await db.refresh(agent)
    return agent
