"""Broken app connections: found, remembered, and fixed with Reconnect."""
import asyncio
import time

import httpx
import pytest

from tests.fakes import scripted
from tests.test_agents import create_agent
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_chat import live_chat, send, use_model  # noqa: F401  (fixtures)
from tests.test_integration_api import connect, entry, gmail_ready
from tests.test_integrations import HOST, composio  # noqa: F401  (fixture)
from tests.test_tool_loop import call


def deleted(composio):  # noqa: F811
    """The connection was removed at Composio: it answers 404 for it."""

    def reply(request):
        path = request.url.path
        if "/connected_accounts/ca_" in path or "/tools/execute/" in path:
            return httpx.Response(404, json={"error": {"message": "Connected account not found"}})
        return composio(request)

    return reply


async def test_a_404_is_its_own_error_but_reads_the_same(web):  # noqa: F811
    from app.tools.http import NotFound, ToolError, Unavailable, fetch_json

    web.replies["example.test"] = httpx.Response(404)
    with pytest.raises(NotFound) as raised:
        await fetch_json("Example", "https://example.test/x")
    assert isinstance(raised.value, ToolError) and not isinstance(raised.value, Unavailable)
    assert str(raised.value) == "Example could not be reached right now."


async def test_a_connection_deleted_at_composio_shows_reconnect(client, user_a, composio, web):  # noqa: F811
    agent = await create_agent(client, user_a)
    await connect(client, user_a, agent["id"])
    web.replies[HOST] = deleted(composio)
    r = await client.post(f"/agents/{agent['id']}/integrations/gmail/refresh", headers=user_a)
    assert r.status_code == 200 and r.json()["status"] == "expired"


async def test_check_updates_every_connection(client, user_a, user_b, composio, web):  # noqa: F811
    agent = await create_agent(client, user_a)
    await connect(client, user_a, agent["id"], "gmail")
    await connect(client, user_a, agent["id"], "slack")
    base = f"/agents/{agent['id']}/integrations/check"
    assert (await client.post(base, headers=user_b)).status_code == 404
    composio.status = "EXPIRED"
    listing = (await client.post(base, headers=user_a)).json()
    assert entry(listing, "gmail")["status"] == "expired" and entry(listing, "slack")["status"] == "expired"
    assert entry(listing, "notion")["status"] == "none"

    composio.status = "ACTIVE"
    web.replies[HOST] = httpx.ConnectError("down")  # Composio can't be asked: nothing is changed
    r = await client.post(base, headers=user_a)
    assert r.status_code == 200 and entry(r.json(), "gmail")["status"] == "expired"


async def test_a_slow_check_changes_nothing_and_returns_quickly(client, user_a, composio, monkeypatch):  # noqa: F811
    from app.api import integrations

    agent = await create_agent(client, user_a)
    await connect(client, user_a, agent["id"])

    async def never(*args):
        await asyncio.sleep(30)

    monkeypatch.setattr(integrations.composio, "connection_status", never)
    monkeypatch.setattr(integrations, "CHECK_SECONDS", 0.2)
    started = time.monotonic()
    listing = (await client.post(f"/agents/{agent['id']}/integrations/check", headers=user_a)).json()
    assert time.monotonic() - started < 5 and entry(listing)["status"] == "active"


async def test_check_without_a_composio_key(client, user_a, composio, monkeypatch):  # noqa: F811
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "composio_api_key", "")
    agent = await create_agent(client, user_a)
    r = await client.post(f"/agents/{agent['id']}/integrations/check", headers=user_a)
    assert r.json() == {"enabled": False, "apps": []}


async def test_the_agent_is_told_which_apps_need_reconnecting(client, user_a, live_chat, use_model, composio):  # noqa: F811
    from app.tools.registry import reconnect_instruction

    agent, session = live_chat
    await gmail_ready(client, user_a, agent["id"])
    model = scripted(["Hi."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert "need reconnecting" not in model.received[0][0].content

    composio.status = "EXPIRED"
    await client.post(f"/agents/{agent['id']}/integrations/check", headers=user_a)
    model = scripted(["Please reconnect Gmail."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Any new mail?"})
    assert reconnect_instruction(["Gmail"]) in model.received[0][0].content
    assert model.bound is None  # its actions are not offered while it is broken


async def test_a_deleted_connection_found_in_chat_is_marked(client, user_a, live_chat, use_model, composio, web):  # noqa: F811
    agent, session = live_chat
    await gmail_ready(client, user_a, agent["id"])
    web.replies[HOST] = deleted(composio)
    model = scripted(call("gmail_fetch_emails", query="x"), ["Please reconnect Gmail."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Any mail?"})
    assert "reconnect Gmail" in model.received[1][-1].content
    listing = (await client.get(f"/agents/{agent['id']}/integrations", headers=user_a)).json()
    assert entry(listing)["status"] == "expired"


# --- found in the owner's live test: Composio keeps saying ACTIVE after Google revoked access --------

REVOKED = ("The credentials do not contain the necessary fields need to refresh the access token. "
           "You must specify refresh_token, token_uri, client_id, and client_secret.")


@pytest.mark.parametrize("error", [REVOKED, "401 Unauthorized", "invalid_grant: Token has been expired or revoked.",
                                   "Request had invalid authentication credentials."])
async def test_a_sign_in_error_needs_a_reconnect_even_if_composio_says_active(client, user_a, live_chat, use_model, composio, error):  # noqa: F811
    agent, session = live_chat
    await gmail_ready(client, user_a, agent["id"])
    composio.result = {"successful": False, "data": {}, "error": error}  # and the account stays ACTIVE
    model = scripted(call("gmail_fetch_emails", query="x"), ["Please reconnect Gmail."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Any mail?"})
    assert "reconnect Gmail" in model.received[1][-1].content
    listing = (await client.get(f"/agents/{agent['id']}/integrations", headers=user_a)).json()
    assert entry(listing)["status"] == "expired"


async def test_a_sign_in_error_on_an_approved_action_needs_a_reconnect(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    from tests.test_approval_decisions import asked, decide
    from tests.test_tool_loop import saved_rows

    agent, session = live_chat
    message_id = await asked(client, user_a, agent, session, use_model)
    composio.result = {"successful": False, "data": {}, "error": REVOKED}
    use_model(scripted(["Please reconnect Gmail."]))
    await decide(client, user_a, session, message_id, "approve")
    approval = (await saved_rows(db, session["id"]))[1].approval
    assert approval["outcome"] == "failed" and "Reconnect it" in approval["reason"]
    listing = (await client.get(f"/agents/{agent['id']}/integrations", headers=user_a)).json()
    assert entry(listing)["status"] == "expired"
