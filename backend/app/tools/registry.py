"""Every tool the platform writes itself. An agent is only given the ones its owner switched on.

To add a tool: write it, then register() it here with the words the user sees.
"""
from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.tools.builtin import calculator, get_current_datetime


@dataclass(frozen=True)
class ToolSpec:
    name: str  # what the model calls; must equal tool.name
    label: str  # what the user sees in the wizard
    description: str  # one line for the wizard (the model reads the tool's own docstring)
    group: str  # heading in the wizard, by what the tool does
    activity: str  # shown in chat while it runs
    tool: BaseTool
    access: str = "read"  # "write" tools will need approval in stage 3


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    assert spec.name == spec.tool.name and spec.name not in REGISTRY, spec.name
    REGISTRY[spec.name] = spec


register(ToolSpec("calculator", "Calculator", "Works out arithmetic exactly.", "Basics", "Calculating…", calculator))
register(
    ToolSpec(
        "get_current_datetime",
        "Current date and time",
        "Tells the agent today's date and the time in any time zone.",
        "Basics",
        "Checking the date and time…",
        get_current_datetime,
    )
)


def catalog() -> dict:
    """The tools grouped for the wizard, in the order they were registered."""
    groups: dict[str, list[dict]] = {}
    for spec in REGISTRY.values():
        groups.setdefault(spec.group, []).append(
            {"name": spec.name, "label": spec.label, "description": spec.description}
        )
    return {"groups": [{"name": name, "tools": tools} for name, tools in groups.items()]}
