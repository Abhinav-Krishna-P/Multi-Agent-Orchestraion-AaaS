"""The details dialog: a form a tool with filters can show in the chat.

The agent calls ask_for_details when a request needs details the user has not given. That
ends its turn; the form is saved on its message and shown in the chat. The user's choices
come back as their next message, in words, and the agent then calls the real tool.
"""
import datetime as dt
from dataclasses import dataclass
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field

from app.tools.http import ToolError

ASK_TOOL = "ask_for_details"
ASK_LABEL = "Asking for details…"
DEFAULT_ASK_TEXT = "A few details will help me find the right results."


@dataclass(frozen=True)
class FormField:
    name: str  # the tool argument this fills
    label: str
    type: str = "text"  # "text" | "date" | "number" | "select"
    options: tuple[tuple[str, str], ...] = ()  # (value, label) pairs for a select
    required: bool = False


MAX_TEXT = 200


def _fitting(field: FormField, value):
    """The value as the card can show it, or None when it does not fit the field. The model
    fills these in freely ("next month" for a date), and a date or number box cannot show
    such a value, though it would still be sent."""
    if field.type == "select":
        return value if value in {option for option, _ in field.options} else None
    if field.type == "number":
        try:
            number = float(value) if not isinstance(value, bool) else None
        except (TypeError, ValueError):
            return None
        if number is None or number < 0:
            return None
        return int(number) if number.is_integer() else number
    if field.type == "date":
        try:
            return dt.date.fromisoformat(value).isoformat() if isinstance(value, str) else None
        except ValueError:
            return None
    if isinstance(value, str) and 0 < len(value.strip()) <= MAX_TEXT:
        return value.strip()
    return None


def form_spec(spec, values: dict, kind: str) -> dict:
    """What the chat needs to draw a tool's form. `kind` is "ask" (the agent is waiting for
    it) or "refine" (offered after a search, filled in with the values that were used)."""
    fitting = {field.name: _fitting(field, values.get(field.name)) for field in spec.form}
    return {
        "kind": kind,
        "tool": spec.name,
        "title": spec.label,
        "fields": [
            {
                "name": field.name, "label": field.label, "type": field.type, "required": field.required,
                "options": [{"value": value, "label": label} for value, label in field.options],
            }
            for field in spec.form
        ],
        "values": {name: value for name, value in fitting.items() if value is not None},
    }


def details_instruction(specs: dict) -> str:
    """Added to the system prompt for each reply while a tool with a form is switched on."""
    labels = ", ".join(f"{spec.name} ({spec.label})" for spec in specs.values())
    return (
        f"Some of your tools have optional filters: {labels}.\n"
        "- A plain request runs the tool straight away with what the user gave, for example "
        "'rooms in Goa' or 'news about cricket'. Do not ask for details first: the user can "
        "refine the results afterwards.\n"
        "- Call ask_for_details, with the tool's name and what you already know, only when the "
        "request itself shows that specifics matter and they are missing ('a place to stay next "
        "month', 'something within my budget', 'for our trip'), or when the tool cannot run "
        "without them (a flight search needs a date). Never guess dates or budgets, and do not "
        "ask for them in plain text.\n"
        "- When the user's message lists values for a search, use exactly those values."
    )


class _AskArgs(BaseModel):
    tool: str = Field(description="The name of the search tool the details are for.")
    known: dict = Field(default_factory=dict, description="Values already known, by the tool's argument names.")
    # Filled in by the graph, never by the model: the conversation so far.
    state: Annotated[dict, InjectedState]


def _already_ran(state: dict, tool: str) -> bool:
    """Whether `tool` has returned results earlier in this reply. Earlier turns are replayed
    as plain text, so any tool result in the state belongs to the reply being written."""
    return any(
        isinstance(message, ToolMessage) and message.name == tool and message.status != "error"
        for message in state.get("messages", [])
    )


def build_ask_tool(specs: dict) -> BaseTool:
    """`specs` are the agent's switched-on tools that have a form, by name."""

    async def ask_for_details(tool: str, state: dict, known: dict | None = None):
        spec = specs.get(tool)
        if spec is None:
            raise ToolError(f"There is no details form for '{tool}'. The tools with a form are: {', '.join(specs)}.")
        if _already_ran(state, tool):
            # Opening the form now would end the reply and throw those results away.
            raise ToolError(
                f"You have already searched with {tool} in this reply. Give the user those results now; "
                "they can change the filters afterwards with the Refine button."
            )
        return (
            "The user is now being shown a form. Stop here and wait for their reply.",
            {"form": form_spec(spec, known or {}, "ask")},
        )

    return StructuredTool.from_function(
        coroutine=ask_for_details,
        name=ASK_TOOL,
        description=(
            "Show the user a short form to collect the details a search needs (dates, guests, "
            "budget, filters). Use it instead of guessing those details or asking for them in text."
        ),
        args_schema=_AskArgs,
        response_format="content_and_artifact",
    )
