"""Approving a proposal makes the automation; declining makes nothing."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import Automation
from tests.conftest import USER_A_ID
from tests.fakes import scripted
from tests.test_analytics import events, named  # noqa: F401  (fixture and helper)
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approval_decisions import decide
from tests.test_automation_describe import PROPOSAL, ready
from tests.test_chat import live_chat, read_events, send, use_model  # noqa: F401  (fixtures)
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_tool_loop import call, saved_rows


async def proposed(client, headers, agent, use_model, **change) -> tuple[dict, str]:  # noqa: F811
    conv = await ready(client, headers, agent)
    use_model(scripted(call("propose_automation", **{**PROPOSAL, **change})))
    await send(client, headers, conv["id"], {"message": "Set it up", "timezone": "Asia/Kolkata"})
    message_id = (await client.get(f"/sessions/{conv['id']}/messages", headers=headers)).json()[-1]["id"]
    return conv, message_id


async def automations(db) -> list[Automation]:
    return (await db.scalars(select(Automation))).all()


async def test_approving_a_schedule_creates_it(client, user_a, live_chat, use_model, composio, db, events):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model)
    use_model(scripted(["It's live."]))
    r = await decide(client, user_a, conv, message_id, "approve")
    tools = read_events(r.text)
    assert tools[0][0] == "tool_start" and tools[0][1]["label"] == "Rate mail (automation)" and tools[1][1]["ok"] is True
    [row] = await automations(db)
    assert row.status == "active" and str(row.conversation_id) == conv["id"] and str(row.user_id) == USER_A_ID
    assert row.trigger == {"every_minutes": 10} and row.locked == PROPOSAL["locked"]
    assert row.tools == ["convert_currency", "gmail_send_email"] and row.trigger_kind == "schedule"
    assert abs(row.next_run_at - (datetime.now(UTC) + timedelta(minutes=10))) < timedelta(seconds=30)
    messages = await saved_rows(db, conv["id"])
    assert messages[1].approval["status"] == "approved" and messages[1].approval["outcome"] == "done"
    assert messages[2].content == "Approved: Rate mail (automation)"
    [event] = named(events, "automation_created")
    assert event["automation_id"] == str(row.id) and event["trigger_kind"] == "schedule"
    assert named(events, "write_action_decision") == [] and named(events, "tool_called") == []
    assert (await decide(client, user_a, conv, message_id, "approve")).status_code == 409
    assert len(await automations(db)) == 1


async def test_a_cron_schedule_keeps_the_chat_zone(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger={"cron": "0 9 * * *"})
    use_model(scripted(["ok"]))
    await decide(client, user_a, conv, message_id, "approve")
    [row] = await automations(db)
    assert row.trigger == {"cron": "0 9 * * *", "timezone": "Asia/Kolkata"}


async def test_approving_an_event_registers_the_trigger(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    trigger = {"app": "gmail", "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE", "config": {"labelIds": "INBOX"}}
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="event", trigger=trigger)
    use_model(scripted(["ok"]))
    await decide(client, user_a, conv, message_id, "approve")
    assert composio.made("POST", "/trigger_instances/GMAIL_NEW_GMAIL_MESSAGE/upsert") == [
        {"user_id": USER_A_ID, "connected_account_id": "ca_1", "trigger_config": {"labelIds": "INBOX"}}]
    [row] = await automations(db)
    assert row.trigger["composio_trigger_id"] == "ti_1" and row.next_run_at is None


async def test_approving_a_watch_remembers_what_is_there(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    composio.result = {"successful": True, "data": {"messages": [{"id": "m1"}, {"id": "m2"}]}, "error": None}
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="watch",
                                  trigger={"action": "gmail_fetch_emails", "arguments": {"query": "in:inbox"}})
    use_model(scripted(["ok"]))
    await decide(client, user_a, conv, message_id, "approve")
    [row] = await automations(db)
    assert row.trigger["seen"] == ["m1", "m2"] and row.next_run_at is not None
    assert row.trigger["arguments"] == {"query": "in:inbox"}
    assert composio.made("POST", "/tools/execute/GMAIL_FETCH_EMAILS")[-1]["arguments"] == {"query": "in:inbox"}


async def test_a_watch_whose_reply_has_no_list_creates_nothing(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    composio.result = {"successful": True, "data": {"ok": True}, "error": None}
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="watch", trigger={"action": "gmail_fetch_emails"})
    use_model(scripted(["sorry"]))
    await decide(client, user_a, conv, message_id, "approve")
    assert await automations(db) == []
    assert (await saved_rows(db, conv["id"]))[1].approval["reason"] == "That Gmail action doesn't return a list to watch."
    composio.result = {"successful": True, "data": {"messages": []}, "error": None}  # an empty list is fine
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="watch", trigger={"action": "gmail_fetch_emails"})
    use_model(scripted(["ok"]))
    await decide(client, user_a, conv, message_id, "approve")
    [row] = await automations(db)
    assert row.trigger["seen"] == []


async def test_a_failing_watch_read_creates_nothing(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="watch", trigger={"action": "gmail_fetch_emails"})
    composio.result = {"successful": False, "data": None, "error": "boom"}
    use_model(scripted(["sorry"]))
    await decide(client, user_a, conv, message_id, "approve")
    assert await automations(db) == []
    approval = (await saved_rows(db, conv["id"]))[1].approval
    assert approval["outcome"] == "failed" and approval["reason"] == "Couldn't read Gmail to start watching. Try again."


async def test_a_tool_switched_off_since_fails(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model)
    await client.put(f"/agents/{agent['id']}/tools", json={"tools": []}, headers=user_a)
    use_model(scripted(["sorry"]))
    await decide(client, user_a, conv, message_id, "approve")
    assert await automations(db) == []
    assert (await saved_rows(db, conv["id"]))[1].approval["outcome"] == "failed"


async def test_rejecting_creates_nothing(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model)
    use_model(scripted(["Okay."]))
    r = await decide(client, user_a, conv, message_id, "reject")
    assert [name for name, _ in read_events(r.text)] == ["token", "done"]
    assert await automations(db) == []
    rows = await saved_rows(db, conv["id"])
    assert rows[1].approval["status"] == "rejected" and rows[2].content == "Declined: Rate mail (automation)"


def test_item_keys():
    from app.automations.watch import item_keys

    assert item_keys({"messages": [{"id": 1}, {"node_id": "n"}, {"url": "u"}, {"name": "x"}]}) == [
        ("1", {"id": 1}), ("n", {"node_id": "n"}), ("u", {"url": "u"}), ("x", {"name": "x"})]
    assert item_keys([{"id": "a"}]) == [("a", {"id": "a"})]
    [(key, _)] = item_keys({"items": [{"b": 1, "a": 2}]})
    assert len(key) == 40 and item_keys({"items": [{"a": 2, "b": 1}]})[0][0] == key
    assert item_keys({"x": 1}) == [] and item_keys({}) == []


async def test_an_agent_stopped_since_is_refused_and_nothing_is_created(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model)
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    r = await decide(client, user_a, conv, message_id, "approve")
    assert r.status_code == 409 and r.json()["detail"]["code"] == "agent_not_live"
    assert await automations(db) == []


async def test_a_failed_event_registration_creates_nothing(client, user_a, live_chat, use_model, composio, db, monkeypatch):  # noqa: F811
    from app.integrations import composio as module
    from app.tools.http import ToolError

    async def refuse(*args):
        raise ToolError("no")

    agent, _ = live_chat
    trigger = {"app": "gmail", "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE", "config": {}}
    conv, message_id = await proposed(client, user_a, agent, use_model, trigger_kind="event", trigger=trigger)
    monkeypatch.setattr(module, "upsert_trigger", refuse)
    use_model(scripted(["sorry"]))
    await decide(client, user_a, conv, message_id, "approve")
    assert await automations(db) == []
    assert (await saved_rows(db, conv["id"]))[1].approval["outcome"] == "failed"


async def test_an_unexpected_error_ends_with_a_failed_outcome(client, user_a, live_chat, use_model, composio, db, monkeypatch):  # noqa: F811
    from app.automations import service

    def explode(*args):
        raise RuntimeError("secret detail")

    agent, _ = live_chat
    conv, message_id = await proposed(client, user_a, agent, use_model)
    monkeypatch.setattr(service, "next_run", explode)
    use_model(scripted(["sorry"]))
    r = await decide(client, user_a, conv, message_id, "approve")
    assert r.status_code == 200 and read_events(r.text)[1][1]["ok"] is False
    assert await automations(db) == []
    approval = (await saved_rows(db, conv["id"]))[1].approval
    assert approval["outcome"] == "failed" and approval["reason"] == "Couldn't set up the automation. Try again."
    assert "secret" not in str(approval)
    assert (await decide(client, user_a, conv, message_id, "approve")).status_code == 409
