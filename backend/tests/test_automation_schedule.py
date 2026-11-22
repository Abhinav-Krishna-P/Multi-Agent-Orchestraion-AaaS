import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.automations.schedule import check_schedule, next_run
from tests.test_sessions import create_session, live_agent


def test_every_minutes():
    t0 = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    assert next_run("schedule", {"every_minutes": 10}, t0) == t0 + timedelta(minutes=10)
    assert check_schedule({"every_minutes": 4}) is not None and check_schedule({"every_minutes": 5}) is None


def test_cron_in_the_users_time_zone():
    t0 = datetime(2026, 11, 20, 3, 0, tzinfo=UTC)  # 08:30 in Kolkata
    nxt = next_run("schedule", {"cron": "0 9 * * *", "timezone": "Asia/Kolkata"}, t0)
    assert nxt == datetime(2026, 11, 20, 3, 30, tzinfo=UTC)
    assert check_schedule({"cron": "0 9 * * *", "timezone": "Asia/Kolkata"}) is None


@pytest.mark.parametrize(
    "trigger",
    [
        {"cron": "* * * * *", "timezone": "UTC"},
        {"cron": "*/2 * * * *", "timezone": "UTC"},
        {"cron": "0,3 * * * *", "timezone": "UTC"},
        {"cron": "0,3 9 * * *", "timezone": "UTC"},
        {"cron": "0,3 9 1 1 *", "timezone": "UTC"},
        {"cron": "@daily", "timezone": "UTC"},
        {"cron": "not cron", "timezone": "UTC"},
        {"cron": "0 9 * * *", "timezone": "Mars/Base"},
        {},
        {"every_minutes": "ten"},
    ],
)
def test_bad_schedules_are_explained(trigger):
    assert isinstance(check_schedule(trigger), str)


def test_watch_and_event():
    t0 = datetime(2026, 11, 20, tzinfo=UTC)
    assert next_run("watch", {}, t0) == t0 + timedelta(minutes=5) and next_run("event", {}, t0) is None


async def test_automation_conversations_are_not_listed_as_chats(client, user_a, db):
    from app.db.models import ChatSession

    agent = await live_agent(client, user_a)
    chat = await create_session(client, user_a, agent["id"])
    other = await create_session(client, user_a, agent["id"])
    (await db.get(ChatSession, uuid.UUID(other["id"]))).purpose = "automation"
    await db.commit()
    r = await client.get(f"/agents/{agent['id']}/sessions", headers=user_a)
    assert [s["id"] for s in r.json()] == [chat["id"]]
