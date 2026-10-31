"""Builds what the model sees for one turn: prompt, summary, recent messages."""
import re
from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

HISTORY_LIMIT = 20


class _Row(Protocol):
    role: str
    content: str


def _plain(value) -> str:
    """Service text for the note: one short line that cannot imitate the note's own brackets and separators."""
    return re.sub(r"[\[\]|;\s]+", " ", str(value)).strip()[:120]


def _link(value) -> str | None:
    """A link is kept only whole: cutting or cleaning one would make it a different address."""
    return value if isinstance(value, str) and re.fullmatch(r"https?://[^\s\[\]|;]{1,300}", value) else None


def cards_note(tool_calls: list | None) -> str:
    """What an earlier reply's cards listed, for the model only. Replies are short summaries
    now, so without this a follow-up like "the second one" would have nothing to point at."""
    lines = []
    for call in tool_calls or []:
        for item in ((call.get("card") or {}).get("items") or [])[:8]:
            rating = f"rated {item['rating']}" if item.get("rating") else None
            name, price = item.get("title") or item.get("name"), item.get("price")
            parts = [name and _plain(name), price and _plain(price), rating and _plain(rating), _link(item.get("link"))]
            lines.append(" | ".join(part for part in parts if part))
    if not lines:
        return ""
    return "\n\n[Shown to the user as cards: " + "; ".join(f"{n}. {line}" for n, line in enumerate(lines, 1)) + "]"


def build_messages(
    system_prompt: str, summary: str | None, history: Sequence[_Row], extra_instruction: str | None = None
) -> list[BaseMessage]:
    """`history` is the chat's most recent rows, oldest first, ending with the user message to answer.

    Leading assistant rows are dropped: the window can start mid-exchange, and providers
    expect the first message after the system prompt to come from the user.
    `extra_instruction` is a platform rule added for this reply only (it is never saved
    into the agent's own prompt).
    """
    system = system_prompt
    if summary:
        system = f"{system_prompt}\n\nSummary of the conversation so far:\n{summary}"
    if extra_instruction:
        system = f"{system}\n\n{extra_instruction}"
    rows = list(history)
    while rows and rows[0].role != "user":
        rows.pop(0)
    messages: list[BaseMessage] = [SystemMessage(content=system)]
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content + cards_note(getattr(row, "tool_calls", None))))
    return messages
