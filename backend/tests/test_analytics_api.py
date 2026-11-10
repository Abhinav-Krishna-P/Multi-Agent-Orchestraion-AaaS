"""The Analytics page's endpoint, against a stand-in for PostHog's query API."""
import datetime as dt

import pytest

from tests.conftest import USER_A_ID
from tests.test_agents import create_agent


@pytest.fixture
def queries(monkeypatch):
    """PostHog's query API: answers each query by which table it groups, and records what was asked."""
    from app.analytics import posthog
    from app.api import analytics
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "posthog_personal_api_key", "phx_test")
    monkeypatch.setattr(settings, "posthog_project_id", "123")
    analytics._cache.clear()
    today = dt.datetime.now(dt.UTC).date()
    asked: list[tuple[str, dict]] = []
    answers = {
        "totals": [[3, 12, 10, 2, 412.6, 4, 2, 1, 1, 2]],
        "days": [[today.isoformat(), 5, 4], [(today - dt.timedelta(days=2)).isoformat(), 7, 6]],
        "tools": [["calculator", "builtin", None, 6, 0, 3.2], ["gmail_fetch_emails", "composio", "gmail", 4, 2, 1200.4]],
    }

    async def query(sql, values):
        asked.append((sql, values))
        if "group by day" in sql:
            return answers["days"]
        if "group by name" in sql:
            return answers["tools"]
        return answers["totals"]

    monkeypatch.setattr(posthog, "query", query)
    return asked


async def test_the_numbers_for_one_agent(client, user_a, queries):
    agent = await create_agent(client, user_a)
    body = (await client.get(f"/agents/{agent['id']}/analytics?range=7d", headers=user_a)).json()
    assert body["enabled"] is True and body["range"] == "7d"
    assert body["totals"] == {
        "sessions": 3, "messages": 12, "tool_calls": 10, "tool_failures": 2, "success_rate": 0.8, "avg_tool_ms": 413,
        "kb_searches": 4, "approved": 2, "rejected": 1, "connection_problems": 1, "documents": 2,
    }
    assert len(body["days"]) == 7 and body["days"][-1]["date"] == dt.datetime.now(dt.UTC).date().isoformat()
    assert body["days"][-1] == {"date": body["days"][-1]["date"], "messages": 5, "tool_calls": 4}
    assert body["days"][-2]["messages"] == 0 and body["days"][-3]["messages"] == 7  # a quiet day is zero, not missing
    assert body["tools"][1] == {"name": "gmail_fetch_emails", "type": "composio", "app": "gmail", "calls": 4, "failures": 2, "avg_ms": 1200}


async def test_values_are_placeholders_never_pasted_in(client, user_a, queries):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics?range=30d", headers=user_a)
    assert len(queries) == 3
    for sql, values in queries:
        assert set(values) == {"agent_id", "user_id", "tz", "start"}
        assert values["agent_id"] == agent["id"] and values["user_id"] == USER_A_ID and values["tz"] == "UTC"
        assert agent["id"] not in sql and USER_A_ID not in sql and "{agent_id}" in sql and "{user_id}" in sql


async def test_another_users_agent(client, user_a, user_b, queries):
    agent = await create_agent(client, user_a)
    assert (await client.get(f"/agents/{agent['id']}/analytics", headers=user_b)).status_code == 404
    assert queries == []


async def test_bad_range(client, user_a, queries):
    agent = await create_agent(client, user_a)
    assert (await client.get(f"/agents/{agent['id']}/analytics?range=1y", headers=user_a)).status_code == 422


async def test_answers_are_remembered_for_a_minute(client, user_a, queries):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)
    await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)
    assert len(queries) == 3


async def test_no_activity_yet(client, user_a, queries, monkeypatch):
    from app.analytics import posthog

    async def nothing(sql, values):
        return [[0, 0, 0, 0, None, 0, 0, 0, 0, 0]] if "group by" not in sql else []

    monkeypatch.setattr(posthog, "query", nothing)
    agent = await create_agent(client, user_a)
    body = (await client.get(f"/agents/{agent['id']}/analytics?range=90d", headers=user_a)).json()
    assert body["totals"]["success_rate"] is None and body["totals"]["avg_tool_ms"] is None
    assert len(body["days"]) == 90 and all(day["messages"] == 0 for day in body["days"]) and body["tools"] == []


async def test_not_set_up(client, user_a):
    agent = await create_agent(client, user_a)
    assert (await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)).json() == {"enabled": False}


async def test_posthog_down(client, user_a, queries, monkeypatch):
    from app.analytics import posthog
    from app.tools.http import unavailable

    async def down(sql, values):
        raise unavailable("PostHog")

    monkeypatch.setattr(posthog, "query", down)
    agent = await create_agent(client, user_a)
    r = await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "analytics_unavailable"


async def test_days_follow_the_viewers_time_zone(client, user_a, queries):
    from zoneinfo import ZoneInfo

    agent = await create_agent(client, user_a)
    body = (await client.get(f"/agents/{agent['id']}/analytics?range=7d&tz=Asia/Kolkata", headers=user_a)).json()
    assert body["days"][-1]["date"] == dt.datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    day_query = next(sql for sql, _ in queries if "group by day" in sql)
    assert "{tz}" in day_query and all(values["tz"] == "Asia/Kolkata" for _, values in queries)
    r = await client.get(f"/agents/{agent['id']}/analytics?tz=Not/AZone", headers=user_a)
    assert r.status_code == 422


async def test_the_period_starts_at_midnight_of_the_first_day_shown(client, user_a, queries):
    """Totals, tools and bars cover the same days: the period starts at the viewer's local
    midnight of the first day on the chart, not at this hour some days ago."""
    from zoneinfo import ZoneInfo

    agent = await create_agent(client, user_a)
    body = (await client.get(f"/agents/{agent['id']}/analytics?range=7d&tz=Asia/Kolkata", headers=user_a)).json()
    first = dt.date.fromisoformat(body["days"][0]["date"])
    midnight = dt.datetime.combine(first, dt.time(), ZoneInfo("Asia/Kolkata")).astimezone(dt.UTC)
    assert all(values["start"] == midnight.strftime("%Y-%m-%d %H:%M:%S") for _, values in queries)
    assert all("{start}" in sql and "now()" not in sql for sql, _ in queries)


@pytest.mark.parametrize("zone", ["Asia", "America", "../etc/passwd", ""])
async def test_odd_time_zones_are_refused_cleanly(client, user_a, queries, zone):
    agent = await create_agent(client, user_a)
    r = await client.get(f"/agents/{agent['id']}/analytics", params={"tz": zone}, headers=user_a)
    assert r.status_code == 422
