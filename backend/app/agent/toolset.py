"""The tools of one run, built the same way for a chat turn and an automation."""
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool
from sqlalchemy import select

from app.db.models import AgentIntegration
from app.integrations import composio
from app.rag.retrieve import document_names
from app.tools import forms, knowledge_base
from app.tools.builtin import calculator, get_current_datetime
from app.tools.registry import APPROVAL_INSTRUCTION, CARDS_INSTRUCTION, REGISTRY, available, reconnect_instruction

BUILTIN_TOOLS = {calculator.name, get_current_datetime.name}


@dataclass
class Toolset:
    tools: list[BaseTool] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    instructions: list[str] = field(default_factory=list)
    forms: dict = field(default_factory=dict)
    kinds: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # what each tool counts as in analytics
    broken_apps: list[str] = field(default_factory=list)


async def build_toolset(
    db, agent, user_id: str, *, embedder, store, locked: dict[str, dict] | None = None, only: list[str] | None = None,
    allowed_in: str | None = None, writes: bool = True,
) -> Toolset:
    """`locked=None` is a chat: app writes ask for approval and the agent may ask for details.
    With `locked` it is an automation: nobody is there, so there is no details form and app writes
    run directly with those argument values fixed. `only` keeps just those tools, and the
    instructions that describe them. `allowed_in` and `writes` go to the app tools."""

    def kept(name: str) -> bool:
        return only is None or name in only

    specs = [REGISTRY[name] for name in agent.tools if name in REGISTRY and available(REGISTRY[name]) and kept(name)]
    ts = Toolset(tools=[spec.tool for spec in specs], labels={spec.name: spec.activity for spec in specs})
    if specs:
        ts.instructions.append(CARDS_INSTRUCTION)
    form_specs = {spec.name: spec for spec in specs if spec.form}
    if form_specs and locked is None:
        ts.tools.append(forms.build_ask_tool(form_specs))
        ts.labels[forms.ASK_TOOL] = forms.ASK_LABEL
        ts.forms = form_specs
        ts.instructions.append(forms.details_instruction(form_specs))
    # The knowledge-base tools exist only while there is something to search.
    wants_kb = agent.kb_enabled and any(kept(name) for name in knowledge_base.LABELS)
    ready_documents = await document_names(db, agent.id) if wants_kb else []
    if ready_documents:
        kb_tools = knowledge_base.build_kb_tools(agent.id, agent.search_mode, embedder=embedder, store=store)
        ts.tools += [tool for tool in kb_tools if kept(tool.name)]
        ts.labels |= knowledge_base.LABELS
        ts.instructions.append(knowledge_base.kb_instruction(ready_documents, strict=agent.kb_strict))
    # The actions of the apps this agent is connected to. The account each runs on is bound here.
    if composio.enabled():
        connected = (await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id))).all()
        ts.broken_apps = [composio.APPS[row.app].name for row in connected if row.status == "expired" and row.app in composio.APPS]
        if ts.broken_apps and only is None:  # so the agent explains, instead of saying it has no such app
            ts.instructions.append(reconnect_instruction(ts.broken_apps))
        app_tools, app_labels = await composio.build_tools(connected, user_id, locked=locked, allowed_in=allowed_in, writes=writes)
        app_tools = [tool for tool in app_tools if kept(tool.name)]
        ts.tools += app_tools
        ts.labels |= app_labels
        if any((tool.metadata or {}).get("approval") for tool in app_tools):
            ts.instructions.append(APPROVAL_INSTRUCTION)
    # Actions waiting for approval are counted when they run.
    ts.kinds = {spec.name: ("builtin" if spec.name in BUILTIN_TOOLS else "api", None) for spec in specs}
    ts.kinds |= {name: ("knowledge_base", None) for name in knowledge_base.LABELS}
    ts.kinds |= {tool.name: ("composio", tool.metadata["app"]) for tool in ts.tools
                 if (tool.metadata or {}).get("app") and not tool.metadata.get("approval")}
    return ts
