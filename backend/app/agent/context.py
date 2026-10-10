"""Builds what the model sees for one turn: prompt, summary, recent messages."""
from collections.abc import Sequence
from typing import Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

HISTORY_LIMIT = 20


class _Row(Protocol):
    role: str
    content: str


def build_messages(system_prompt: str, summary: str | None, history: Sequence[_Row]) -> list[BaseMessage]:
    """`history` is the chat's most recent rows, oldest first, ending with the user message to answer.

    Leading assistant rows are dropped: the window can start mid-exchange, and providers
    expect the first message after the system prompt to come from the user.
    """
    system = system_prompt
    if summary:
        system = f"{system_prompt}\n\nSummary of the conversation so far:\n{summary}"
    rows = list(history)
    while rows and rows[0].role != "user":
        rows.pop(0)
    messages: list[BaseMessage] = [SystemMessage(content=system)]
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content))
    return messages
