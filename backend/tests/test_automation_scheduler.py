"""The scheduler claims due automations once; watches fire only for items not seen before."""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import AgentIntegration, Automation
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approvals import switch_on
from tests.test_automation_run import fresh, make
from tests.test_chat import live_chat  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)

WATCH = {"app": "gmail", "action": "GMAIL_FETCH_EMAILS", "arguments": {"query": "in:inbox"}, "every_minutes": 5, "seen": ["1", "2"]}


def ok(data):
    return {"successful": True, "data": data, "error": None}


async def due(db, agent, **change) -> Automation:
    return await make(db, agent, next_run_at=datetime.now(UTC) - timedelta(minutes=1), **change)


def record(monkeypatch) -> list[tuple]:
    from app.automations import run

    calls = []

    async def fake(automation_id, source, event=None, event_key=None, *, wait=True, run_id=None):
        calls.append((automation_id, source, event, event_key, wait))

    monkeypatch.setattr(run, "run_automation", fake)
    return calls


def test_item_keys_shapes():
    from app.automations.watch import has_list, item_keys

    assert [k for k, _ in item_keys({"repositories": [{"id": 1}, {"id": 2}]})] == ["1", "2"]
    assert item_keys({"total": 3}) == [] and item_keys([]) == []
    assert len(item_keys([{"title": "x"}])[0][0]) == 40  # hashed
    assert has_list([]) and has_list({"items": []}) and has_list({"a": 1, "b": [{"id": 1}]})
    assert not has_list({"ok": True}) and not has_list({"tags": ["a"]}) and not has_list(None)


async def test_due_schedules_run_once_even_when_ticks_overlap(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import run
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    a = await due(db, agent)
    now = datetime.now(UTC)
    assert sorted(await asyncio.gather(tick(now), tick(now))) == [0, 1]
    await run.wait_for_runs()
    assert calls == [(a.id, "schedule", None, None, False)]
    assert (await fresh(db, Automation, a.id)).next_run_at > now
    assert await tick(now) == 0


async def test_overdue_after_restart_runs_once_then_follows_the_schedule(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import run
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    a = await make(db, agent, next_run_at=datetime.now(UTC) - timedelta(hours=5))  # every 10 minutes
    now = datetime.now(UTC)
    assert await tick(now) == 1
    after = (await fresh(db, Automation, a.id)).next_run_at
    assert abs(after - (now + timedelta(minutes=10))) < timedelta(seconds=5)
    assert await tick(now + timedelta(minutes=1)) == 0
    assert await tick(now + timedelta(minutes=11)) == 1
    await run.wait_for_runs()
    assert len(calls) == 2


async def test_paused_and_stopped_agent_automations_do_not_run(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    paused = await due(db, agent, status="paused")
    event = await due(db, agent, trigger_kind="event", trigger={"app": "gmail", "trigger_slug": "X"})
    assert await tick(datetime.now(UTC)) == 0
    live = await due(db, agent)
    await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    assert await tick(datetime.now(UTC)) == 0 and calls == []
    for a in (paused, event, live):  # untouched: still overdue
        assert (await fresh(db, Automation, a.id)).next_run_at < datetime.now(UTC)


async def test_watch_fires_only_for_new_items(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import run
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    a = await due(db, agent, trigger_kind="watch", trigger=dict(WATCH), tools=[], locked={})
    composio.result = ok({"messages": [{"id": 3}, {"id": 2}, {"id": 1}]})
    assert await tick(datetime.now(UTC)) == 1
    await run.wait_for_runs()
    assert calls == [(a.id, "watch", {"id": 3}, "3", True)]
    assert composio.made("POST", "/tools/execute/GMAIL_FETCH_EMAILS")[-1]["arguments"] == {"query": "in:inbox"}
    row = await fresh(db, Automation, a.id)
    assert row.trigger["seen"] == ["1", "2", "3"] and row.trigger["arguments"] == {"query": "in:inbox"}
    row.next_run_at = datetime.now(UTC) - timedelta(seconds=1)
    await db.commit()
    assert await tick(datetime.now(UTC)) == 0  # nothing new now


async def test_watch_hands_over_oldest_first_at_most_five_and_caps_seen(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import watch

    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    monkeypatch.setattr(watch, "MAX_SEEN", 6)
    a = await make(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    composio.result = ok([{"id": n} for n in range(9, 0, -1)])  # newest first
    new = await watch.check(a)
    assert [k for k, _ in new] == ["3", "4", "5", "6", "7"]
    assert (await fresh(db, Automation, a.id)).trigger["seen"] == ["2", "3", "4", "5", "6", "7"]
    assert [k for k, _ in await watch.check(await fresh(db, Automation, a.id))] == ["1", "8", "9"]


async def test_watch_ignores_an_odd_reply(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    a = await due(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    composio.result = ok({"ok": True})
    assert await tick(datetime.now(UTC)) == 0 and calls == []
    assert (await fresh(db, Automation, a.id)).trigger["seen"] == ["1", "2"]


async def test_watch_survives_a_failing_action_and_a_dead_connection(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import watch

    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    a = await make(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    composio.result = {"successful": False, "data": None, "error": "boom"}
    assert await watch.check(a) == []
    composio.result = {"successful": False, "data": None, "error": "401 Unauthorized"}
    assert await watch.check(a) == []
    assert (await db.scalar(select(AgentIntegration.status).execution_options(populate_existing=True))) == "expired"
    assert await watch.check(a) == []  # no active connection left
    assert (await fresh(db, Automation, a.id)).trigger["seen"] == ["1", "2"]


async def test_a_watch_whose_connection_broke_asks_for_a_reconnect(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    signed_out = await due(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    composio.result = {"successful": False, "data": None, "error": "401 Unauthorized"}
    assert await tick(datetime.now(UTC)) == 0
    row = await fresh(db, Automation, signed_out.id)
    assert row.status == "error" and row.status_reason == "Reconnect Gmail"
    # Found expired later (the connection is already marked): the same.
    later = await due(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    assert await tick(datetime.now(UTC)) == 0 and calls == []
    row = await fresh(db, Automation, later.id)
    assert row.status == "error" and row.status_reason == "Reconnect Gmail"


async def test_a_long_watch_item_is_trimmed_before_it_is_stored(client, user_a, live_chat, composio, db, monkeypatch):  # noqa: F811
    from app.automations import run
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    await switch_on(client, user_a, agent["id"], "GMAIL_FETCH_EMAILS")
    await due(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    composio.result = ok({"messages": [{"id": 3, "body": "x" * 10000}]})
    assert await tick(datetime.now(UTC)) == 1
    await run.wait_for_runs()
    [(_, _, event, key, _)] = calls
    assert key == "3" and set(event) == {"truncated"} and len(event["truncated"]) == run.MAX_EVENT_CHARS


async def test_the_loop_starts_once_and_survives_a_failing_tick(monkeypatch):
    from app.automations import scheduler

    ticks = []

    async def boom(now):
        ticks.append(now)
        raise RuntimeError("secret")

    monkeypatch.setattr(scheduler, "tick", boom)
    monkeypatch.setattr(scheduler, "TICK_SECONDS", 0.01)
    scheduler.start()
    first = scheduler._task
    scheduler.start()
    assert scheduler._task is first
    await asyncio.sleep(0.1)
    assert len(ticks) > 1
    await scheduler.stop()
    assert first.done() and scheduler._task is None


async def test_one_failing_automation_does_not_sink_the_others(client, user_a, live_chat, composio, db, monkeypatch, caplog):  # noqa: F811
    from app.automations import run, watch
    from app.automations.scheduler import tick

    agent, _ = live_chat
    calls = record(monkeypatch)
    await due(db, agent, trigger_kind="watch", trigger=dict(WATCH))
    schedule = await due(db, agent)

    async def broken(automation):
        raise RuntimeError("secret")

    monkeypatch.setattr(watch, "check", broken)
    assert await tick(datetime.now(UTC)) == 1
    await run.wait_for_runs()
    assert calls == [(schedule.id, "schedule", None, None, False)]
    assert "RuntimeError" in caplog.text and "secret" not in caplog.text
