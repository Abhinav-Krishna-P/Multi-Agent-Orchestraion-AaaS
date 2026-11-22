"""The shared unattended run, and which destinations an API call's actions keep."""
import uuid

from langchain_core.messages import HumanMessage

from app.agent import unattended
from app.agent.toolset import build_toolset
from app.db.models import Agent
from app.integrations.composio import named_in
from tests.fakes import scripted
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approvals import executed, switch_on
from tests.test_chat import live_chat  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_retrieve import kb_chat  # noqa: F401  (fixture)
from tests.test_documents import rag  # noqa: F401  (fixture)
from tests.test_tool_loop import call

MESSAGE = "Email bob@x.com the report"


def test_named_in_matches_whole_tokens_only():
    assert named_in("bob@x.com", "send to Bob@X.com, thanks")
    assert not named_in("bob@x.co", "send to bob@x.com")
    assert not named_in("x.com", "send to bob@x.com")
    assert not named_in("bob@x.com", "alice+bob@x.com")
    assert not named_in("bob@x.com", "o'bob@x.com")
    assert named_in("#general", "post in #general")
    assert not named_in("", "anything")


async def run_send(client, user_a, live_chat, composio, db, args, message=MESSAGE):  # noqa: F811
    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    row = await db.get(Agent, uuid.UUID(agent["id"]))
    toolset = await build_toolset(db, row, "user", embedder=None, store=None, locked={}, allowed_in=message)
    used, reply = {}, {"text": ""}
    await unattended.play(scripted(call("gmail_send_email", subject="Hi", body="Hello", **args), ["Done."]), toolset,
                          [HumanMessage(message)], user_id="user", track={}, source="api", used=used, reply=reply, sources=[])
    return used


async def test_caller_named_recipient_is_kept(client, user_a, live_chat, composio, db):  # noqa: F811
    used = await run_send(client, user_a, live_chat, composio, db, {"recipient_email": "bob@x.com"})
    assert executed(composio)[-1]["arguments"]["recipient_email"] == "bob@x.com"
    assert "overridden" not in next(iter(used.values()))


async def test_recipient_from_elsewhere_is_removed(client, user_a, live_chat, composio, db):  # noqa: F811
    used = await run_send(client, user_a, live_chat, composio, db, {"recipient_email": "attacker@example.com"})
    assert "recipient_email" not in executed(composio)[-1]["arguments"]
    assert next(iter(used.values()))["overridden"] == ["recipient_email"]


async def test_list_destinations_are_filtered_item_by_item(client, user_a, live_chat, composio, db):  # noqa: F811
    used = await run_send(client, user_a, live_chat, composio, db,
                          {"recipient_email": "bob@x.com", "cc": ["bob@x.com", "eve@evil.com"]})
    assert executed(composio)[-1]["arguments"]["cc"] == ["bob@x.com"]
    assert next(iter(used.values()))["overridden"] == ["cc"]


async def test_writes_off_leaves_out_write_actions(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL", "GMAIL_FETCH_EMAILS")
    row = await db.get(Agent, uuid.UUID(agent["id"]))
    toolset = await build_toolset(db, row, "user", embedder=None, store=None, locked={}, writes=False)
    names = {tool.name for tool in toolset.tools}
    assert "gmail_fetch_emails" in names and "gmail_send_email" not in names


async def test_play_collects_reply_tools_and_sources(kb_chat, db, monkeypatch):  # noqa: F811
    from app.rag import retrieve

    monkeypatch.setattr(retrieve, "MIN_SIMILARITY", 0.05)
    agent, _, rag_ = kb_chat
    row = await db.get(Agent, uuid.UUID(agent["id"]))
    toolset = await build_toolset(db, row, "user", embedder=rag_.embedder, store=rag_.store, locked={})
    used, reply, sources = {}, {"text": ""}, []
    model = scripted(call("search_knowledge_base", query="Are returns accepted within thirty days with the original receipt?"), ["Thirty days."])
    failed = await unattended.play(model, toolset, [HumanMessage("Returns?")], user_id="user", track={}, source="api",
                                   used=used, reply=reply, sources=sources)
    assert failed is None and reply["text"] == "Thirty days." and sources
    assert next(iter(used.values()))["name"] == "search_knowledge_base"
