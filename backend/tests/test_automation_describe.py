"""The "Describe your automation" chat: forms for missing details, and a checked proposal card."""
import pytest

from tests.fakes import scripted
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approvals import switch_on
from tests.test_chat import live_chat, read_events, send, use_model  # noqa: F401  (fixtures)
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_tool_loop import call, enable, saved_rows

PROPOSAL = {
    "name": "Rate mail", "task": "Get the USD to INR rate and email it.", "trigger_text": "every 10 minutes",
    "trigger_kind": "schedule", "trigger": {"every_minutes": 10}, "tools": ["convert_currency", "GMAIL_SEND_EMAIL"],
    "locked": {"gmail_send_email": {"recipient_email": "me@example.com"}},
}


async def conversation(client, headers, agent_id: str) -> dict:
    r = await client.post(f"/agents/{agent_id}/automation-conversations", headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def ready(client, headers, agent) -> dict:
    """Currency conversion and Gmail sending switched on; returns a new describe conversation."""
    await enable(client, headers, agent, "convert_currency")
    await switch_on(client, headers, agent["id"], "GMAIL_FETCH_EMAILS", "GMAIL_SEND_EMAIL")
    return await conversation(client, headers, agent["id"])


async def test_a_valid_proposal_shows_the_card(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    assert conv["purpose"] == "automation"
    model = scripted(call("propose_automation", **PROPOSAL))
    use_model(model)
    r = await send(client, user_a, conv["id"], {"message": "Email me the USD to INR rate every 10 minutes", "timezone": "Asia/Kolkata"})
    events = read_events(r.text)
    approval = dict(events)["approval_required"]["approval"]
    assert approval["kind"] == "automation" and approval["status"] == "pending"
    assert approval["trigger"]["every_minutes"] == 10 and approval["timezone"] == "Asia/Kolkata"
    assert approval["tools"] == ["convert_currency", "gmail_send_email"]
    assert approval["locked"] == {"gmail_send_email": {"recipient_email": "me@example.com"}}
    assert approval["tool_labels"] == {"convert_currency": "Currency conversion", "gmail_send_email": "Gmail Send Email (Gmail)"}
    assert approval["name"] == "Rate mail" and approval["trigger_text"] == "every 10 minutes"
    assert len(model.received) == 1  # the turn ends at the card
    assert sorted(model.bound) == ["ask_automation_details", "list_event_triggers", "propose_automation"]  # never the real tools
    assert (await saved_rows(db, conv["id"]))[-1].approval == approval
    assert composio.made("POST", "/tools/execute/GMAIL_SEND_EMAIL") == []


@pytest.mark.parametrize("change, problem", [
    ({"tools": ["search_stays"]}, "not one of this agent's tools"),
    ({"trigger": {"every_minutes": 1}}, "5 minutes"),
    ({"locked": {}}, "recipient_email"),
    ({"locked": {"gmail_send_email": {"recipient_email": ""}}}, "recipient_email"),
    ({"locked": {"gmail_send_email": {"recipient_email": "me@example.com"}, "gmail_fetch_emails": {"query": "x"}}}, "gmail_fetch_emails"),
    ({"locked": {**PROPOSAL["locked"], "convert_currency": {"to": "INR"}}}, "remove 'convert_currency' from locked"),
    ({"tools": [*PROPOSAL["tools"], "gmail_fetch_emails"], "locked": {**PROPOSAL["locked"], "gmail_fetch_emails": {"query": "x"}}},
     "remove 'gmail_fetch_emails' from locked"),
    ({"locked": {"gmail_send_email": {"recipient_email": "me@example.com", "to": "x@example.com"}}}, "no argument named to"),
    ({"trigger_kind": "watch", "trigger": {"action": "GMAIL_SEND_EMAIL"}}, "read action"),
    ({"trigger_kind": "watch", "trigger": {"action": "gmail_fetch_emails", "arguments": {"nope": 1}}}, "no argument named nope"),
    ({"trigger_kind": "event", "trigger": {"app": "gmail", "trigger_slug": "GMAIL_NOPE", "config": {}}}, "GMAIL_NOPE"),
    ({"trigger_kind": "event", "trigger": {"app": "slack", "trigger_slug": "SLACK_NEW_MESSAGE", "config": {}}}, "not connected"),
])
async def test_bad_proposals_go_back_to_the_model(client, user_a, live_chat, use_model, composio, db, change, problem):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    model = scripted(call("propose_automation", **{**PROPOSAL, **change}), ["Let me fix that."])
    use_model(model)
    r = await send(client, user_a, conv["id"], {"message": "Set it up", "timezone": "Asia/Kolkata"})
    assert "approval_required" not in dict(read_events(r.text))
    assert problem in model.received[1][-1].content
    assert (await saved_rows(db, conv["id"]))[-1].approval is None


async def test_event_and_watch_proposals_are_accepted(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    event = {"app": "gmail", "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE", "config": {}}
    use_model(scripted(call("propose_automation", **{**PROPOSAL, "trigger_kind": "event", "trigger": event})))
    await send(client, user_a, conv["id"], {"message": "On new mail"})
    assert (await saved_rows(db, conv["id"]))[-1].approval["trigger"] == event
    use_model(scripted(call("propose_automation", **{**PROPOSAL, "trigger_kind": "watch", "trigger": {"action": "gmail_fetch_emails"}})))
    await send(client, user_a, conv["id"], {"message": "Watch instead"})
    assert (await saved_rows(db, conv["id"]))[-1].approval["trigger"] == {"action": "GMAIL_FETCH_EMAILS", "app": "gmail"}
    trigger = {"action": "gmail_fetch_emails", "arguments": {"query": "is:unread"}}
    use_model(scripted(call("propose_automation", **{**PROPOSAL, "trigger_kind": "watch", "trigger": trigger})))
    await send(client, user_a, conv["id"], {"message": "Only unread"})
    assert (await saved_rows(db, conv["id"]))[-1].approval["trigger"] == {
        "action": "GMAIL_FETCH_EMAILS", "app": "gmail", "arguments": {"query": "is:unread"}}


async def test_a_cron_schedule_gets_the_chat_time_zone(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    use_model(scripted(call("propose_automation", **{**PROPOSAL, "trigger": {"cron": "0 9 * * *"}})))
    await send(client, user_a, conv["id"], {"message": "Daily at 9", "timezone": "Mars/Olympus"})  # not a zone: UTC
    approval = (await saved_rows(db, conv["id"]))[-1].approval
    assert approval["trigger"] == {"cron": "0 9 * * *", "timezone": "UTC"} and approval["timezone"] == "UTC"


async def test_the_instruction_names_missing_apps_and_the_not_possible_sentence(client, user_a, live_chat, use_model, composio):  # noqa: F811
    from app.automations.describe import NOT_POSSIBLE

    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    model = scripted(["What should it do?"])
    use_model(model)
    await send(client, user_a, conv["id"], {"message": "Hi", "timezone": "Asia/Kolkata"})
    system = model.received[0][0].content
    assert NOT_POSSIBLE in system and "Slack" in system  # not connected -> listed as available to connect
    assert "gmail_send_email (Gmail, write)" in system and "gmail_fetch_emails (Gmail, read)" in system
    assert "convert_currency:" in system and "Weather forecast" in system  # on, and offered but switched off
    assert "Asia/Kolkata" in system


async def test_details_form_card(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    fields = [{"name": "recipient", "label": "Send it to", "type": "email", "required": True},
              {"name": "often", "label": "How often", "type": "select", "options": [{"value": "10", "label": "Every 10 minutes"}]}]
    model = scripted(call("ask_automation_details", title="A few details", fields=fields, known={"recipient": "me@example.com", "x": 1}))
    use_model(model)
    r = await send(client, user_a, conv["id"], {"message": "Email me the rate"})
    assert [name for name, _ in read_events(r.text)] == ["tool_start", "tool_end", "token", "done"]
    assert len(model.received) == 1  # waits for the user's answers
    form = (await saved_rows(db, conv["id"]))[-1].form
    assert form["kind"] == "ask" and form["tool"] == "automation" and form["title"] == "A few details"
    assert form["fields"][0] == {"name": "recipient", "label": "Send it to", "type": "email", "required": True, "options": []}
    assert form["fields"][1]["options"] == [{"value": "10", "label": "Every 10 minutes"}]
    assert form["values"] == {"recipient": "me@example.com"}


async def test_listing_event_triggers_needs_a_connected_app(client, user_a, live_chat, use_model, composio):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    model = scripted(call("list_event_triggers", app="gmail"), call("list_event_triggers", app="slack"), ["Done."])
    use_model(model)
    await send(client, user_a, conv["id"], {"message": "What events are there?"})
    assert "GMAIL_NEW_GMAIL_MESSAGE" in model.received[1][-1].content
    assert "not connected" in model.received[2][-1].content


async def test_a_new_message_skips_the_proposal(client, user_a, live_chat, use_model, composio, db):  # noqa: F811
    agent, _ = live_chat
    conv = await ready(client, user_a, agent)
    use_model(scripted(call("propose_automation", **PROPOSAL)))
    await send(client, user_a, conv["id"], {"message": "Set it up"})
    model = scripted(["Okay."])
    use_model(model)
    r = await send(client, user_a, conv["id"], {"message": "Actually, wait"})
    assert read_events(r.text)[-1][0] == "done"
    assert (await saved_rows(db, conv["id"]))[1].approval["status"] == "skipped"
    assert 'you proposed the automation "Rate mail" (every 10 minutes).' in model.received[0][0].content
    assert "The user did not answer, so it was not done." in model.received[0][0].content
    messages = await client.get(f"/sessions/{conv['id']}/messages", headers=user_a)
    assert messages.status_code == 200 and messages.json()[1]["approval"]["kind"] == "automation"


def test_approval_note_for_automations():
    from app.agent.context import approval_note

    proposal = {"kind": "automation", "name": "Rate ] mail", "trigger_text": "every | 10 minutes", "task": "Email it.",
                "tools": ["gmail_send_email"], "locked": {"gmail_send_email": {"recipient_email": "me@example.com"}}}
    live = approval_note({**proposal, "status": "approved", "outcome": "done"})
    assert 'you proposed the automation "Rate mail" (every 10 minutes).' in live
    assert "The user approved it and the automation is now live." in live and "me@example.com" in live
    assert live.count("]") == 1
    failed = approval_note({**proposal, "status": "approved", "outcome": "failed", "reason": "Gmail is broken"})
    assert "it failed: Gmail is broken" in failed
    assert "The user declined it" in approval_note({**proposal, "status": "rejected"})
    assert approval_note({**proposal, "status": "pending"}) == ""


async def test_conversations_need_a_live_agent_and_are_private(client, user_a, user_b, live_chat):  # noqa: F811
    agent, chat_session = live_chat
    latest = f"/agents/{agent['id']}/automation-conversations/latest"
    assert (await client.get(latest, headers=user_a)).status_code == 404
    await conversation(client, user_a, agent["id"])
    second = await conversation(client, user_a, agent["id"])
    assert (await client.get(latest, headers=user_a)).json()["id"] == second["id"]
    sessions = (await client.get(f"/agents/{agent['id']}/sessions", headers=user_a)).json()
    assert [s["id"] for s in sessions] == [chat_session["id"]]  # hidden from the chat list
    assert (await client.get(latest, headers=user_b)).status_code == 404
    assert (await client.post(f"/agents/{agent['id']}/automation-conversations", headers=user_b)).status_code == 404
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    r = await client.post(f"/agents/{agent['id']}/automation-conversations", headers=user_a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "agent_not_live"
