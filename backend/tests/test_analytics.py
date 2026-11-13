"""Usage events sent to PostHog, and the analytics read back from it."""
import httpx
import pytest

from tests.conftest import USER_A_ID
from tests.fakes import scripted
from tests.rag_fakes import make_pdf  # noqa: F401
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approval_decisions import asked, decide
from tests.test_chat import live_chat, send, use_model  # noqa: F401  (fixtures)
from tests.test_documents import paste, rag, upload  # noqa: F401  (fixtures)
from tests.test_integration_api import gmail_ready
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_retrieve import kb_chat  # noqa: F401  (fixture)
from tests.test_tool_loop import call, enable

ALLOWED = {"user_id", "agent_id", "session_id", "tool_name", "tool_type", "app", "success", "duration_ms",
           "search_mode", "results_count", "decision", "outcome", "source_type", "chunk_count", "status",
           "trigger_kind", "source", "automation_id", "$process_person_profile"}


@pytest.fixture
def events(monkeypatch):
    from app.analytics import posthog

    recorded: list[dict] = []
    monkeypatch.setattr(posthog, "recorder", recorded)
    return recorded


def named(events, name: str) -> list[dict]:
    """The properties of each event with this name. Every event is checked for content on the way."""
    for event in events:
        assert set(event["properties"]) <= ALLOWED, event
        assert event["distinct_id"] == event["properties"]["user_id"]
    return [event["properties"] for event in events if event["event"] == name]


# --- sending -----------------------------------------------------------------------------------


@pytest.fixture
def posthog_on(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "posthog_api_key", "phc_test")
    monkeypatch.setattr(settings, "posthog_host", "https://us.i.posthog.com")
    return settings


async def test_capture_sends_in_the_background(posthog_on, web):  # noqa: F811
    from app.analytics import posthog

    web.replies["us.i.posthog.com"] = {"status": "Ok"}
    posthog.capture("session_started", USER_A_ID, agent_id="a1", session_id="s1")
    await posthog.flush()
    request = web.last
    assert request.url.path == "/i/v0/e/"
    assert web.body() == {
        "api_key": "phc_test", "event": "session_started", "distinct_id": USER_A_ID,
        "properties": {"user_id": USER_A_ID, "agent_id": "a1", "session_id": "s1", "$process_person_profile": False},
    }


async def test_a_posthog_outage_changes_nothing(posthog_on, web):  # noqa: F811
    from app.analytics import posthog

    web.replies["us.i.posthog.com"] = httpx.ConnectError("down")
    posthog.capture("message_sent", USER_A_ID, agent_id="a1")
    await posthog.flush()  # no exception reaches the caller


async def test_nothing_is_sent_without_a_key(web):  # noqa: F811
    from app.analytics import posthog

    posthog.capture("message_sent", USER_A_ID, agent_id="a1")
    await posthog.flush()
    assert web.requests == []


def test_content_can_never_be_sent():
    from app.analytics import posthog

    with pytest.raises(ValueError):
        posthog.capture("message_sent", USER_A_ID, message="my secret question")


# --- what is counted ----------------------------------------------------------------------------


async def test_chats_messages_and_builtin_tools(client, user_a, live_chat, use_model, events):  # noqa: F811
    agent, session = live_chat
    await client.post(f"/agents/{agent['id']}/sessions", headers=user_a)
    started = named(events, "session_started")
    assert started and started[-1]["agent_id"] == agent["id"] and started[-1]["user_id"] == USER_A_ID

    await enable(client, user_a, agent, "calculator")
    use_model(scripted(call("calculator", expression="6*7"), ["42."]))
    await send(client, user_a, session["id"], {"message": "6 times 7?"})
    assert named(events, "message_sent")[-1] == {"user_id": USER_A_ID, "agent_id": agent["id"], "session_id": session["id"],
                                                 "$process_person_profile": False}
    tool = named(events, "tool_called")[-1]
    assert tool["tool_name"] == "calculator" and tool["tool_type"] == "builtin" and tool["success"] is True
    assert isinstance(tool["duration_ms"], int) and tool["duration_ms"] >= 0 and "app" not in tool
    assert tool["session_id"] == session["id"]

    use_model(scripted(call("calculator", wrong_name="2+2"), ["Sorry."]))
    await send(client, user_a, session["id"], {"message": "2+2?"})
    assert named(events, "tool_called")[-1]["success"] is False


async def test_service_tools_count_as_api(client, user_a, live_chat, use_model, events, web):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "web_search")
    web.replies["serpapi.com"] = {"organic_results": [{"title": "T", "link": "https://x", "snippet": "S"}]}
    use_model(scripted(call("web_search", query="anything"), ["Found it."]))
    await send(client, user_a, session["id"], {"message": "Search"})
    tool = named(events, "tool_called")[-1]
    assert tool["tool_name"] == "web_search" and tool["tool_type"] == "api"


async def test_the_details_form_is_not_counted_as_a_tool(client, user_a, live_chat, use_model, events):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "search_stays")
    use_model(scripted({"tool": "ask_for_details", "args": {"tool": "search_stays", "known": {"location": "Goa"}}}))
    await send(client, user_a, session["id"], {"message": "A stay in Goa next month"})
    assert named(events, "tool_called") == []


async def test_app_actions_and_decisions(client, user_a, live_chat, use_model, composio, events):  # noqa: F811
    agent, session = live_chat
    await gmail_ready(client, user_a, agent["id"])
    use_model(scripted(call("gmail_fetch_emails", query="x"), ["One email."]))
    await send(client, user_a, session["id"], {"message": "Mail?"})
    tool = named(events, "tool_called")[-1]
    assert tool["tool_name"] == "gmail_fetch_emails" and tool["tool_type"] == "composio" and tool["app"] == "gmail"

    message_id = await asked(client, user_a, agent, session, use_model)
    use_model(scripted(["Sent."]))
    await decide(client, user_a, session, message_id, "approve")
    decision = named(events, "write_action_decision")[-1]
    assert decision["decision"] == "approved" and decision["outcome"] == "done"
    assert decision["tool_name"] == "gmail_send_email" and decision["app"] == "gmail"
    ran = named(events, "tool_called")[-1]
    assert ran["tool_name"] == "gmail_send_email" and ran["tool_type"] == "composio" and ran["success"] is True

    message_id = await asked(client, user_a, agent, session, use_model)
    use_model(scripted(["Okay."]))
    await decide(client, user_a, session, message_id, "reject")
    decision = named(events, "write_action_decision")[-1]
    assert decision["decision"] == "rejected" and "outcome" not in decision


async def test_broken_connections_are_counted(client, user_a, live_chat, use_model, composio, events):  # noqa: F811
    agent, session = live_chat
    await gmail_ready(client, user_a, agent["id"])
    composio.result = {"successful": False, "data": {}, "error": "401 Unauthorized"}
    use_model(scripted(call("gmail_fetch_emails", query="x"), ["Reconnect."]))
    await send(client, user_a, session["id"], {"message": "Mail?"})
    expired = named(events, "connection_expired")
    assert expired[-1]["app"] == "gmail" and expired[-1]["agent_id"] == agent["id"]


async def test_a_check_that_finds_a_broken_connection_counts_it(client, user_a, live_chat, composio, events):  # noqa: F811
    agent, _ = live_chat
    await gmail_ready(client, user_a, agent["id"])
    composio.status = "EXPIRED"
    await client.post(f"/agents/{agent['id']}/integrations/check", headers=user_a)
    assert named(events, "connection_expired")[-1]["app"] == "gmail"
    await client.post(f"/agents/{agent['id']}/integrations/check", headers=user_a)
    assert len(named(events, "connection_expired")) == 1  # counted when it breaks, not on every look


async def test_knowledge_base_searches(client, user_a, kb_chat, use_model, events, monkeypatch):  # noqa: F811
    from app.rag import retrieve

    monkeypatch.setattr(retrieve, "MIN_SIMILARITY", 0.05)
    agent, session, _ = kb_chat
    use_model(scripted(call("search_knowledge_base", query="returns within thirty days"), ["Thirty days."]))
    await send(client, user_a, session["id"], {"message": "Returns?"})
    searched = named(events, "knowledge_base_searched")[-1]
    assert searched["search_mode"] == "hybrid" and isinstance(searched["results_count"], int)
    assert named(events, "tool_called")[-1]["tool_type"] == "knowledge_base"


async def test_documents_ingested(client, user_a, rag, events):  # noqa: F811
    from tests.test_agents import create_agent

    agent = await create_agent(client, user_a)
    await paste(client, user_a, agent["id"])
    ready = named(events, "document_ingested")[-1]
    assert ready["status"] == "ready" and ready["source_type"] == "paste" and ready["chunk_count"] > 0
    assert ready["agent_id"] == agent["id"]
    await upload(client, user_a, agent["id"], "broken.pdf", b"this is not a pdf")
    failed = named(events, "document_ingested")[-1]
    assert failed["status"] == "failed" and failed["source_type"] == "pdf"
