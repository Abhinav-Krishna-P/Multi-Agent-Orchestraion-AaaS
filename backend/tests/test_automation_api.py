"""Managing automations over the API, and stopping or deleting an agent reaching them."""
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import Automation, AutomationRun
from tests.conftest import USER_A_ID
from tests.fakes import scripted
from tests.test_analytics import events, named  # noqa: F401  (fixture and helper)
from tests.test_automation_run import fresh, make, use_run_model  # noqa: F401  (helpers and fixture)
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_chat import live_chat  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)

EVENT = {"composio_trigger_id": "ti_1"}


def event_automation(db, agent, **change):
    return make(db, agent, trigger_kind="event", trigger=EVENT, trigger_text="when mail arrives", **change)


def trigger_calls(composio, method):
    return [(p, b) for m, p, b in composio.calls if m == method and p.startswith("/trigger_instances/manage/")]


async def test_list_shows_newest_first_with_the_last_run(client, user_a, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    old = await make(db, agent, name="Old")
    new = await make(db, agent, name="New")
    now = datetime.now(UTC)
    db.add_all([
        AutomationRun(automation_id=new.id, user_id=new.user_id, source="schedule", status="succeeded",
                      started_at=now - timedelta(minutes=5), output="first"),
        AutomationRun(automation_id=new.id, user_id=new.user_id, source="test", status="failed",
                      started_at=now, error="boom", tool_calls=[{"label": "Using Gmail…", "ok": False}]),
    ])
    await db.commit()
    r = await client.get(f"/agents/{agent['id']}/automations", headers=user_a)
    assert r.status_code == 200
    body = r.json()
    assert [a["name"] for a in body] == ["New", "Old"] and old.id
    assert set(body[0]) == {"id", "name", "task", "trigger_kind", "trigger_text", "trigger", "tools", "locked", "status",
                            "status_reason", "next_run_at", "last_run_at", "created_at", "last_run"}
    assert body[0]["trigger"] == {"every_minutes": 10}
    assert body[0]["last_run"]["status"] == "failed" and body[0]["last_run"]["error"] == "boom"
    assert set(body[0]["last_run"]) == {"id", "source", "status", "started_at", "finished_at", "output", "tool_calls", "error"}
    assert body[1]["last_run"] is None


async def test_the_list_shows_the_real_trigger_but_not_its_internals(client, user_a, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    await make(db, agent, trigger_kind="event", trigger={"app": "gmail", "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE",
                                                         "config": {"labelIds": "INBOX"}, "composio_trigger_id": "ti_1"})
    await make(db, agent, trigger_kind="watch", trigger={"app": "gmail", "action": "GMAIL_FETCH_EMAILS",
                                                         "arguments": {"query": "in:inbox"}, "seen": ["1", "2"]})
    watch, event = (await client.get(f"/agents/{agent['id']}/automations", headers=user_a)).json()
    assert event["trigger"] == {"app": "gmail", "trigger_slug": "GMAIL_NEW_GMAIL_MESSAGE", "config": {"labelIds": "INBOX"}}
    assert watch["trigger"] == {"app": "gmail", "action": "GMAIL_FETCH_EMAILS", "arguments": {"query": "in:inbox"}}


async def test_turn_off_and_on(client, user_a, live_chat, composio, db, events):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent, status="error", status_reason="Failed 3 times in a row", failure_streak=3)
    r = await client.patch(f"/automations/{a.id}", json={"status": "paused"}, headers=user_a)
    assert r.status_code == 200 and r.json()["status"] == "paused"
    assert trigger_calls(composio, "PATCH") == [("/trigger_instances/manage/ti_1", {"status": "disable"})]

    r = await client.patch(f"/automations/{a.id}", json={"status": "active"}, headers=user_a)
    assert r.json()["status"] == "active" and r.json()["status_reason"] is None
    assert trigger_calls(composio, "PATCH")[-1] == ("/trigger_instances/manage/ti_1", {"status": "enable"})
    a = await fresh(db, Automation, a.id)
    assert a.failure_streak == 0 and a.status_reason is None
    assert [e["status"] for e in named(events, "automation_status_changed")] == ["paused", "active"]


async def test_turning_off_keeps_a_trigger_another_automation_still_uses(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent, name="A")
    b = await event_automation(db, agent, name="B")
    assert (await client.patch(f"/automations/{a.id}", json={"status": "paused"}, headers=user_a)).status_code == 200
    assert trigger_calls(composio, "PATCH") == []  # B still needs it
    await client.patch(f"/automations/{b.id}", json={"status": "paused"}, headers=user_a)
    assert trigger_calls(composio, "PATCH") == [("/trigger_instances/manage/ti_1", {"status": "disable"})]
    await client.patch(f"/automations/{a.id}", json={"status": "active"}, headers=user_a)
    assert trigger_calls(composio, "PATCH")[-1] == ("/trigger_instances/manage/ti_1", {"status": "enable"})


async def test_turning_a_schedule_on_sets_the_next_run(client, user_a, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    a = await make(db, agent, status="paused", next_run_at=None)
    r = await client.patch(f"/automations/{a.id}", json={"status": "active"}, headers=user_a)
    assert r.status_code == 200
    next_run = datetime.fromisoformat(r.json()["next_run_at"])
    assert timedelta(minutes=9) < next_run - datetime.now(UTC) <= timedelta(minutes=10)


async def test_turning_on_needs_a_live_agent(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent)
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    r = await client.patch(f"/automations/{a.id}", json={"status": "active"}, headers=user_a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "agent_not_live"
    # Turning off still works while stopped.
    r = await client.patch(f"/automations/{a.id}", json={"status": "paused"}, headers=user_a)
    assert r.status_code == 200


async def test_a_failing_composio_does_not_block_turning_off(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent)
    composio.trigger_manage_fails = True
    r = await client.patch(f"/automations/{a.id}", json={"status": "paused"}, headers=user_a)
    assert r.status_code == 200 and r.json()["status"] == "paused"


async def test_delete_removes_the_trigger_unless_another_automation_shares_it(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent, name="A")
    b = await event_automation(db, agent, name="B")
    assert (await client.delete(f"/automations/{a.id}", headers=user_a)).status_code == 204
    assert trigger_calls(composio, "DELETE") == []
    assert (await client.delete(f"/automations/{b.id}", headers=user_a)).status_code == 204
    assert trigger_calls(composio, "DELETE") == [("/trigger_instances/manage/ti_1", {})]
    assert await db.scalar(select(func.count()).select_from(Automation)) == 0


async def test_delete_goes_ahead_when_the_trigger_cannot_be_deleted(client, user_a, live_chat, composio, db, caplog):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent)
    composio.trigger_manage_fails = True
    with caplog.at_level(logging.WARNING):
        r = await client.delete(f"/automations/{a.id}", headers=user_a)
    assert r.status_code == 204 and "ti_1" in caplog.text
    assert await db.scalar(select(func.count()).select_from(Automation)) == 0


async def test_test_run_starts_in_the_background_and_shows_in_history(client, user_a, live_chat, db, use_run_model):  # noqa: F811
    from app.automations import run

    agent, _ = live_chat
    a = await make(db, agent, tools=[], locked={}, status="paused")
    use_run_model(scripted(["All done."]))
    r = await client.post(f"/automations/{a.id}/test", headers=user_a)
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    await run.wait_for_runs()
    history = (await client.get(f"/automations/{a.id}/runs", headers=user_a)).json()
    assert [h["id"] for h in history] == [run_id]
    assert history[0]["source"] == "test" and history[0]["status"] == "succeeded" and history[0]["output"] == "All done."


async def test_runs_are_the_last_20_newest_first(client, user_a, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    a = await make(db, agent)
    now = datetime.now(UTC)
    db.add_all(AutomationRun(automation_id=a.id, user_id=a.user_id, source="schedule", status="succeeded",
                             started_at=now - timedelta(minutes=i), output=str(i)) for i in range(25))
    await db.commit()
    history = (await client.get(f"/automations/{a.id}/runs", headers=user_a)).json()
    assert [h["output"] for h in history] == [str(i) for i in range(20)]


async def test_another_users_automation_is_not_found(client, user_a, user_b, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    a = await make(db, agent)
    missing = uuid.uuid4()
    for method, path, kwargs in [
        ("get", f"/agents/{agent['id']}/automations", {}),
        ("patch", f"/automations/{a.id}", {"json": {"status": "paused"}}),
        ("delete", f"/automations/{a.id}", {}),
        ("post", f"/automations/{a.id}/test", {}),
        ("get", f"/automations/{a.id}/runs", {}),
        ("get", f"/automations/{missing}/runs", {}),
    ]:
        r = await getattr(client, method)(path, headers=user_b, **kwargs)
        assert r.status_code == 404, (method, path)
    assert (await fresh(db, Automation, a.id)).status == "active"


async def test_stopping_the_agent_pauses_its_automations_and_their_triggers(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    a = await event_automation(db, agent)
    b = await make(db, agent)
    r = await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    assert r.status_code == 200
    for row in (a, b):
        row = await fresh(db, Automation, row.id)
        assert row.status == "paused" and row.status_reason == "Agent was stopped"
    assert trigger_calls(composio, "PATCH") == [("/trigger_instances/manage/ti_1", {"status": "disable"})]


async def test_deleting_the_agent_deletes_its_triggers_and_rows(client, user_a, live_chat, composio, db):  # noqa: F811
    agent, _ = live_chat
    await event_automation(db, agent)
    composio.trigger_manage_fails = True  # best effort: the agent still goes
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204
    assert trigger_calls(composio, "DELETE") == [("/trigger_instances/manage/ti_1", {})]
    assert await db.scalar(select(func.count()).select_from(Automation)) == 0
