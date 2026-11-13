"""The tools of one run, built the same way for a chat turn and an automation."""
import uuid

import pytest

from app.agent.toolset import build_toolset
from app.db.models import Agent
from app.integrations.composio import destination_args
from app.tools.registry import APPROVAL_INSTRUCTION
from tests.conftest import USER_A_ID
from tests.test_approvals import EMAIL, executed, switch_on
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_chat import live_chat, use_model  # noqa: F401  (fixtures)
from tests.test_integrations import composio  # noqa: F401  (fixture)


async def send_tool(client, user_a, live_chat, db, locked):  # noqa: F811
    agent_row, _ = live_chat
    await switch_on(client, user_a, agent_row["id"], "GMAIL_SEND_EMAIL")
    agent = await db.get(Agent, uuid.UUID(agent_row["id"]))
    ts = await build_toolset(db, agent, USER_A_ID, embedder=None, store=None, locked=locked)
    return ts, next(t for t in ts.tools if t.name == "gmail_send_email")


def call(tool, **args):
    return tool.ainvoke({"type": "tool_call", "id": "1", "name": tool.name, "args": args})


async def test_locked_values_win(client, user_a, live_chat, composio, db):  # noqa: F811
    ts, tool = await send_tool(client, user_a, live_chat, db, {"gmail_send_email": {"recipient_email": "me@example.com"}})
    msg = await call(tool, recipient_email="stranger@x.com", body="hi")
    assert executed(composio)[-1]["arguments"]["recipient_email"] == "me@example.com"
    assert msg.artifact == {"overridden": ["recipient_email"]}
    assert APPROVAL_INSTRUCTION not in ts.instructions
    assert ts.kinds["gmail_send_email"] == ("composio", "gmail")  # runs now, so it is counted now


async def test_unlocked_destinations_are_dropped(client, user_a, live_chat, composio, db):  # noqa: F811
    _, tool = await send_tool(client, user_a, live_chat, db, {"gmail_send_email": {}})
    msg = await call(tool, recipient_email="x@y", body="hi")
    assert "recipient_email" not in executed(composio)[-1]["arguments"]
    assert executed(composio)[-1]["arguments"]["body"] == "hi"
    assert msg.artifact == {"overridden": ["recipient_email"]}


async def test_chat_toolset_unchanged(client, user_a, live_chat, composio, db):  # noqa: F811
    ts, _ = await send_tool(client, user_a, live_chat, db, None)
    assert any((t.metadata or {}).get("approval") for t in ts.tools) and APPROVAL_INSTRUCTION in ts.instructions
    assert executed(composio) == []


async def test_undeclared_destinations_are_dropped(client, user_a, live_chat, composio, db):  # noqa: F811
    _, tool = await send_tool(client, user_a, live_chat, db, {"gmail_send_email": {}})
    msg = await call(tool, to="x@y", body="hi")
    assert "to" not in executed(composio)[-1]["arguments"]
    assert msg.artifact == {"overridden": ["to"]}


def test_destination_args():
    action = {"parameters": {"properties": {"recipient_email": {}, "subject": {}, "body": {}}}}
    assert destination_args(action) == ["recipient_email"]


@pytest.mark.parametrize("name, found", [
    ("Recipient_Email", True), ("email_address", True), ("attendees", True), ("webhook_url", True),
    ("subject", False), ("body", False), ("title", False),
])
def test_destination_names(name, found):
    assert destination_args({"parameters": {"properties": {name: {}}}}) == ([name] if found else [])
