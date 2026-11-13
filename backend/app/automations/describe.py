"""The "Describe your automation" chat: the agent's model, told what the agent can do, asks for
missing details with form cards and ends with a checked proposal the user approves or rejects.
It never runs the agent's real tools."""
from datetime import datetime
from types import SimpleNamespace
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.toolset import build_toolset
from app.automations.schedule import check_schedule
from app.db.models import AgentIntegration
from app.integrations import composio
from app.tools.forms import ASK_TOOL, FormField, form_spec
from app.tools.http import ToolError
from app.tools.registry import REGISTRY, available

NOT_POSSIBLE = "This automation is currently not possible. We will work on it in the upcoming days."
ASK_AUTOMATION_TOOL = "ask_automation_details"
LABELS = {
    ASK_AUTOMATION_TOOL: "Asking for details…",
    "list_event_triggers": "Checking the app's events…",
    "propose_automation": "Preparing the automation…",
}

SYSTEM_PROMPT = (
    'You help the user set up an automation for their agent "{name}": a standing job the agent runs on its own, '
    "on a schedule or when something happens. Here you only work out the details and propose it; you never run "
    "the agent's tools yourself."
)

RULES = f"""Rules:
- If the automation needs an app listed as not connected, reply: "This automation needs <app>. Connect <app> to this agent (agent settings → Apps), then describe it again." If it needs a switched-off platform tool, say the same with the tool's name and the Tools step. If it needs a broken app, tell the user to reconnect it in the agent's Apps step.
- If nothing above can do what it needs, reply with exactly this sentence and nothing else: "{NOT_POSSIBLE}" Never improvise or pretend a capability.
- Ask for every missing detail (recipient, how often, which repository...) with {ASK_AUTOMATION_TOOL}, never in plain text. Never ask for app sign-ins or passwords: apps use the agent's connections.
- A run cannot ask anyone anything, so every value the task needs must be known before you propose.
- Triggers: "schedule" is {{"every_minutes": N}} (N at least 5) or {{"cron": "<5 fields>"}} in the user's time zone, with runs at least 5 minutes apart. "event" is a Composio event of a connected app: call list_event_triggers, then use {{"app", "trigger_slug", "config"}} with its required settings filled. "watch" is for events no Composio event covers: {{"action": "<a read action of a connected app>", "arguments": {{...}}}} (arguments optional: the action's own parameters, such as the repository), run every 5 minutes; each new item it returns starts one run. Prefer an event when one fits, otherwise watch.
- For each write tool, put the values that decide where or to whom it acts (recipient, channel, repository, owner, ids...) in "locked", by tool name, exactly as the user gave them. Runs can never change them.
- Propose one automation at a time with propose_automation, using only the agent's tools. If it reports a problem, fix it and propose again."""


def _zone(name: str | None) -> str:
    try:
        ZoneInfo(name or "UTC")
        return name or "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


class _Option(BaseModel):
    value: str
    label: str


class _Field(BaseModel):
    name: str = Field(description="A short key for the answer, such as recipient_email.")
    label: str = Field(description="What the user sees, such as 'Send it to'.")
    type: Literal["text", "number", "date", "select", "email"] = "text"
    required: bool = False
    options: list[_Option] = Field(default_factory=list, description="The choices, for a select.")


class _AskArgs(BaseModel):
    title: str = Field(max_length=100, description="The form's heading.")
    fields: list[_Field] = Field(min_length=1, max_length=10)
    known: dict = Field(default_factory=dict, description="Values already known, by field name.")


class _ListArgs(BaseModel):
    app: str = Field(description="A connected app, such as github.")


class _ProposeArgs(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="A short name for the automation.")
    task: str = Field(min_length=1, max_length=2000, description="What each run does, in plain words, with every value it needs.")
    trigger_text: str = Field(min_length=1, max_length=200, description="The trigger in a few plain words, such as 'every 10 minutes'.")
    trigger_kind: Literal["schedule", "event", "watch"]
    trigger: dict = Field(description="The trigger's settings (see the rules).")
    tools: list[str] = Field(description="The names of the agent's tools a run may use.")
    locked: dict[str, dict] = Field(default_factory=dict, description="For each write tool, its fixed values by argument name.")


def _ask_tool() -> BaseTool:
    async def ask(title: str, fields: list[_Field], known: dict | None = None):
        for field in fields:
            if field.type == "select" and not field.options:
                raise ToolError(f"The select field '{field.name}' needs options.")
        spec = SimpleNamespace(name="automation", label=title, form=tuple(
            FormField(f.name, f.label, f.type, tuple((o.value, o.label) for o in f.options), f.required) for f in fields))
        return "The user is now being shown a form. Stop here and wait for their reply.", {"form": form_spec(spec, known or {}, "ask")}

    return StructuredTool.from_function(
        coroutine=ask, name=ASK_AUTOMATION_TOOL, args_schema=_AskArgs, response_format="content_and_artifact",
        description="Show the user a short form card to collect details the automation needs. Use it instead of asking in text.",
    )


async def build_describe_turn(db, agent, session, timezone: str) -> dict:
    timezone, user_id = _zone(timezone), str(session.user_id)
    # Only the tools' names and descriptions are used here, so the knowledge-base search is never given its stores.
    ts = await build_toolset(db, agent, user_id, embedder=None, store=None)
    own = {tool.name: tool for tool in ts.tools if tool.name != ASK_TOOL}  # the agent's tools
    rows = (await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == agent.id))).all() if composio.enabled() else []
    active = {row.app: row for row in rows if row.status == "active" and row.app in composio.APPS}
    slugs = {slug.lower(): slug for row in active.values() for slug in row.actions}

    def app_of(name: str) -> str | None:
        return (own[name].metadata or {}).get("app")

    def is_write(name: str) -> bool:
        return bool((own[name].metadata or {}).get("approval"))

    def connected(app: str) -> str:
        app = app.strip().lower()
        if app not in active:
            raise ToolError(f"'{app}' is not connected to this agent. Connected apps: {', '.join(active) or 'none'}.")
        return app

    async def list_event_triggers(app: str) -> str:
        app = connected(app)
        lines = []
        for t in await composio.trigger_types(app):
            config = t["config"]
            required = config.get("required") or []
            others = [name for name in config.get("properties") or {} if name not in required]
            lines.append(f"- {t['slug']}: {t['name']}. {t['description'][:200]} Required settings: {', '.join(required) or 'none'}."
                         + (f" Optional: {', '.join(others)}." if others else ""))
        return f"{composio.APPS[app].name} events:\n" + ("\n".join(lines) or "None.")

    async def propose_automation(name, task, trigger_text, trigger_kind, trigger, tools: list[str], locked: dict | None = None):
        chosen = list(dict.fromkeys(t.strip().lower() for t in tools))
        for tool in chosen:
            if tool not in own:
                raise ToolError(f"'{tool}' is not one of this agent's tools. Its tools are: {', '.join(own) or 'none'}.")
        locked = {key.lower(): values for key, values in (locked or {}).items()}
        for key in locked:
            if key not in chosen:
                raise ToolError(f"Locked values are given for '{key}', which is not in the automation's tools.")
        trigger = dict(trigger)
        if trigger_kind == "schedule":
            trigger.setdefault("timezone", timezone)
            if error := check_schedule(trigger):
                raise ToolError(error)
        elif trigger_kind == "event":
            app = connected(str(trigger.get("app") or ""))
            found = {t["slug"]: t for t in await composio.trigger_types(app)}
            kind = found.get(str(trigger.get("trigger_slug")))
            if kind is None:
                raise ToolError(f"'{trigger.get('trigger_slug')}' is not an event of {composio.APPS[app].name}. Call list_event_triggers to see them.")
            config = trigger.get("config") or {}
            if not isinstance(config, dict):
                raise ToolError("The event's config must be an object of settings.")
            missing = [key for key in kind["config"].get("required") or [] if config.get(key) in (None, "")]
            if missing:
                raise ToolError(f"The event needs these settings: {', '.join(missing)}. Ask the user for them.")
            trigger = {"app": app, "trigger_slug": kind["slug"], "config": config}
        else:
            action = str(trigger.get("action") or "").lower()
            if action not in own or not app_of(action) or is_write(action):
                raise ToolError(f"'{trigger.get('action')}' is not a switched-on read action of a connected app.")
            arguments = trigger.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ToolError("The watch's arguments must be an object of the action's parameters.")
            parameters = {a["slug"].lower(): a for a in await composio.actions(app_of(action))}[action]["parameters"].get("properties") or {}
            if unknown := [arg for arg in arguments if arg not in parameters]:
                raise ToolError(f"{action} has no argument named {', '.join(unknown)}. Its arguments are: {', '.join(parameters)}.")
            trigger = {"action": slugs[action], "app": app_of(action), **({"arguments": arguments} if arguments else {})}
        labels = {}
        for tool in chosen:
            app = app_of(tool)
            action = {a["slug"].lower(): a for a in await composio.actions(app)}[tool] if app else None
            # Runs enforce locks only on app write actions, and send every locked key: anything else would be shown but not kept, or break runs.
            if tool in locked and (action is None or action["kind"] != "write"):
                raise ToolError(f"Only app actions that change something can have locked values; remove '{tool}' from locked.")
            if not app:
                labels[tool] = REGISTRY[tool].label if tool in REGISTRY else tool
                continue
            labels[tool] = f"{action['name']} ({composio.APPS[app].name})"
            if action["kind"] == "write":
                properties = action["parameters"].get("properties") or {}
                if unknown := [arg for arg in locked.get(tool, {}) if arg not in properties]:
                    raise ToolError(f"{tool} has no argument named {', '.join(unknown)}. Its arguments are: {', '.join(properties)}.")
                required = set(action["parameters"].get("required") or [])
                unlocked = [arg for arg in composio.destination_args(action)
                            if arg in required and locked.get(tool, {}).get(arg) in (None, "")]
                if unlocked:
                    raise ToolError(f"{tool} must have {', '.join(unlocked)} in locked, with the user's exact values. Ask the user if you do not know them.")
        return "The user is now being shown the proposal. Stop here and wait for their answer.", {"approval": {
            "kind": "automation", "status": "pending", "name": name, "task": task, "trigger_text": trigger_text,
            "trigger_kind": trigger_kind, "trigger": trigger, "tools": chosen, "tool_labels": labels, "locked": locked,
            "timezone": timezone,
        }}

    describe_tools = [
        _ask_tool(),
        StructuredTool.from_function(
            coroutine=list_event_triggers, name="list_event_triggers", args_schema=_ListArgs,
            description="List the events (Composio triggers) a connected app can start an automation on, with their settings.",
        ),
        StructuredTool.from_function(
            coroutine=propose_automation, name="propose_automation", args_schema=_ProposeArgs, response_format="content_and_artifact",
            description="Propose the finished automation. The user sees it as a card and approves or rejects it.",
        ),
    ]

    def listed(name: str) -> str:
        app = app_of(name)
        where = f" ({composio.APPS[app].name}, {'write' if is_write(name) else 'read'})" if app else ""
        return f"- {name}{where}: {' '.join(own[name].description.split())[:300]}"

    switched_off = [f"{spec.label} ({spec.name})" for spec in REGISTRY.values() if available(spec) and spec.name not in agent.tools]
    broken = set(ts.broken_apps)
    missing_apps = [app.name for slug, app in composio.APPS.items() if slug not in active and app.name not in broken] if composio.enabled() else []
    now = datetime.now(ZoneInfo(timezone)).strftime("%A %d %B %Y, %H:%M")
    instruction = "\n\n".join(part for part in (
        "The agent's tools (an automation may use only these):\n" + ("\n".join(map(listed, own)) or "None."),
        f"Apps whose connection is broken: {', '.join(sorted(broken))}." if broken else "",
        f"Platform tools this agent has switched off: {', '.join(switched_off)}." if switched_off else "",
        f"Apps the platform offers that this agent is not connected to: {', '.join(missing_apps)}." if missing_apps else "",
        f"The user's time zone is {timezone}; it is now {now} there.",
        RULES,
    ) if part)
    return {
        "system_prompt": SYSTEM_PROMPT.format(name=agent.name),
        "tools": describe_tools,
        "labels": LABELS,
        "extra_instruction": instruction,
        "forms": {},
        "track": {"user_id": user_id, "agent_id": str(agent.id), "session_id": str(session.id), "tool_kinds": {}},
    }
