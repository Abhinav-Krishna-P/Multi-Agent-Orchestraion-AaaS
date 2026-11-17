"""The Analytics page's endpoint, against a stand-in for PostHog's query API."""
import datetime as dt

import pytest

from tests.conftest import USER_A_ID
from tests.test_agents import create_agent


@pytest.fixture
def queries(monkeypatch):
    """PostHog's query API: answers each query by which table it groups, and records what was asked."""
    from app.analytics import posthog
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "posthog_personal_api_key", "phx_test")
    monkeypatch.setattr(settings, "posthog_project_id", "123")
    today = dt.datetime.now(dt.UTC).date()
    asked: list[tuple[str, dict]] = []
    answers = {
        "totals": [[3, 12, 10, 2, 412.6, 4, 2, 1, 1, 2]],
        "days": [[today.isoformat(), 5, 4], [(today - dt.timedelta(days=2)).isoformat(), 7, 6]],
        "tools": [
            ["calculator", "builtin", None, 6, 0, 3.2], ["gmail_fetch_emails", "composio", "gmail", 4, 2, 1200.4],
            ["convert_currency", "builtin", None, 3, 1, 250.0], ["gmail_send_email", "composio", "gmail", 2, 0, 300.0],
            ["search_knowledge_base", "knowledge_base", None, 2, 0, 80.0], ["read_document", "knowledge_base", None, 1, 0, 20.0],
            ["my_crm_lookup", "api", None, 1, 1, 10.0],
        ],
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
    # Display names, never raw tool names; one row per app or tool, with calls-weighted average times.
    assert body["tools"] == [
        {"name": "Calculator", "type": "builtin", "app": None, "calls": 6, "failures": 0, "avg_ms": 3},
        {"name": "Gmail", "type": "composio", "app": "gmail", "calls": 6, "failures": 2, "avg_ms": 900},  # (1200.4*4 + 300*2) / 6
        {"name": "Currency conversion", "type": "builtin", "app": None, "calls": 3, "failures": 1, "avg_ms": 250},
        {"name": "Knowledge base", "type": "knowledge_base", "app": None, "calls": 3, "failures": 0, "avg_ms": 60},
        {"name": "my_crm_lookup", "type": "api", "app": None, "calls": 1, "failures": 1, "avg_ms": 10},  # unknown: as named
    ]


async def test_values_are_placeholders_never_pasted_in(client, user_a, queries):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics?range=30d", headers=user_a)
    assert len(queries) == 3
    for sql, values in queries:
        assert set(values) == {"agent_id", "user_id", "tz", "start"}
        assert values["agent_id"] == agent["id"] and values["user_id"] == USER_A_ID and values["tz"] == "UTC"
        assert agent["id"] not in sql and USER_A_ID not in sql and "{agent_id}" in sql and "{user_id}" in sql


async def test_the_chat_tab_leaves_out_automation_tool_calls(client, user_a, queries):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)
    chat_only = "ifNull(toString(properties.source), '') != 'automation'"
    for sql, _ in queries:
        # Every tool_called count, average and the tools table, never a bare != (a missing source is chat).
        assert sql.count("event = 'tool_called'") == sql.count(f"event = 'tool_called' and {chat_only}") > 0, sql


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


async def test_a_failed_read_is_not_cached(client, user_a, queries, monkeypatch):
    from app.analytics import posthog
    from app.tools.http import unavailable

    working = posthog.query

    async def down(sql, values):
        raise unavailable("PostHog")

    agent = await create_agent(client, user_a)
    monkeypatch.setattr(posthog, "query", down)
    assert (await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)).status_code == 503
    monkeypatch.setattr(posthog, "query", working)
    r = await client.get(f"/agents/{agent['id']}/analytics", headers=user_a)
    assert r.status_code == 200 and r.json()["totals"]["messages"] == 12


@pytest.fixture
def stored(monkeypatch):
    """What the endpoints put in the shared cache: (key, seconds)."""
    from app.core import cache

    seen = []
    real_set = cache.set_json

    async def spy(key, value, seconds):
        seen.append((key, seconds))
        await real_set(key, value, seconds)

    monkeypatch.setattr(cache, "set_json", spy)
    return seen


async def test_chat_numbers_are_kept_in_the_shared_cache_for_60s(client, user_a, queries, stored):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics?range=7d", headers=user_a)
    assert stored == [(f"analytics:{agent['id']}:chat:7d:UTC", 60)]


async def test_automation_numbers_are_kept_in_the_shared_cache_for_60s(client, user_a, queries_auto, stored):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics/automations?range=30d", headers=user_a)
    assert stored == [(f"analytics:{agent['id']}:automations:30d:UTC", 60)]


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


GONE_ID = "00000000-0000-0000-0000-00000000dead"


@pytest.fixture
def queries_auto(monkeypatch, queries):
    """The automation queries, answered by what each one groups; `queries` records what was asked."""
    from app.analytics import posthog

    today = dt.datetime.now(dt.UTC).date().isoformat()
    state = {"table": []}

    async def query(sql, values):
        queries.append((sql, values))
        if "group by day" in sql:
            return [[today, 4, 1]]
        if "group by properties.automation_id" in sql:
            return state["table"]
        return [[10, 8, 2, 1500.4, 3, 14]]

    monkeypatch.setattr(posthog, "query", query)
    return state


async def test_automation_numbers(client, user_a, queries_auto, db):
    from tests.test_automation_run import make

    agent = await create_agent(client, user_a)
    rate = await make(db, agent, name="Rate mail")
    await make(db, agent, name="Paused one", status="paused")
    queries_auto["table"] = [
        [str(rate.id), 9, 1, 2, 1400.2, "2026-11-20 10:00:00"],
        [GONE_ID, 1, 0, 0, None, "2026-11-19 09:00:00"],
    ]
    body = (await client.get(f"/agents/{agent['id']}/analytics/automations?range=7d", headers=user_a)).json()
    today = dt.datetime.now(dt.UTC).date().isoformat()
    assert body["enabled"] is True and body["range"] == "7d"
    assert body["totals"] == {"runs": 10, "succeeded": 8, "success_rate": 0.8, "test_runs": 2, "avg_run_ms": 1500,
                              "created": 3, "tool_calls": 14}
    assert len(body["days"]) == 7 and body["days"][-1] == {"date": today, "succeeded": 4, "failed": 1}
    assert body["days"][-2] == {"date": body["days"][-2]["date"], "succeeded": 0, "failed": 0}
    first, second = body["automations"]
    assert first == {"id": str(rate.id), "name": "Rate mail", "trigger_text": "every 10 minutes", "status": "active",
                     "runs": 9, "failures": 1, "test_runs": 2, "avg_ms": 1400, "last_run_at": "2026-11-20 10:00:00"}
    assert second["name"] == "Deleted automation" and second["status"] == "deleted" and second["trigger_text"] is None
    assert body["active_now"] == 1


async def test_automation_average_over_no_rows_is_zero(client, user_a, queries_auto, db):
    from tests.test_automation_run import make

    agent = await create_agent(client, user_a)
    only_tests = await make(db, agent, name="Only tests")
    queries_auto["table"] = [[str(only_tests.id), 0, 0, 3, float("nan"), "2026-11-20 10:00:00"],
                             [GONE_ID, 0, 0, 1, None, "2026-11-19 09:00:00"]]
    r = await client.get(f"/agents/{agent['id']}/analytics/automations", headers=user_a)
    assert r.status_code == 200 and [a["avg_ms"] for a in r.json()["automations"]] == [0, 0]


async def test_automation_values_are_placeholders(client, user_a, queries_auto, queries):
    agent = await create_agent(client, user_a)
    await client.get(f"/agents/{agent['id']}/analytics/automations?range=30d", headers=user_a)
    assert len(queries) == 3
    for sql, values in queries:
        assert set(values) == {"agent_id", "user_id", "tz", "start"}
        assert values["agent_id"] == agent["id"] and values["user_id"] == USER_A_ID
        assert agent["id"] not in sql and USER_A_ID not in sql and "{agent_id}" in sql and "{user_id}" in sql


async def test_automation_analytics_private_and_cached(client, user_a, user_b, queries_auto, queries):
    agent = await create_agent(client, user_a)
    url = f"/agents/{agent['id']}/analytics/automations"
    assert (await client.get(url, headers=user_b)).status_code == 404
    assert queries == []
    await client.get(url, headers=user_a)
    await client.get(url, headers=user_a)
    assert len(queries) == 3
    assert (await client.get(url, params={"tz": "Not/AZone"}, headers=user_a)).status_code == 422


async def test_no_automation_runs(client, user_a, queries, monkeypatch):
    from app.analytics import posthog

    async def nothing(sql, values):
        return [[0, 0, 0, None, 0, 0]] if "group by" not in sql else []

    monkeypatch.setattr(posthog, "query", nothing)
    agent = await create_agent(client, user_a)
    body = (await client.get(f"/agents/{agent['id']}/analytics/automations?range=90d", headers=user_a)).json()
    assert body["totals"]["success_rate"] is None and body["totals"]["avg_run_ms"] is None
    assert len(body["days"]) == 90 and all(d["succeeded"] == 0 and d["failed"] == 0 for d in body["days"])
    assert body["automations"] == [] and body["active_now"] == 0


async def test_automation_posthog_down(client, user_a, queries, monkeypatch):
    from app.analytics import posthog
    from app.tools.http import unavailable

    agent = await create_agent(client, user_a)
    async def down(sql, values):
        raise unavailable("PostHog")

    monkeypatch.setattr(posthog, "query", down)
    r = await client.get(f"/agents/{agent['id']}/analytics/automations", headers=user_a)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "analytics_unavailable"


@pytest.mark.parametrize("zone", ["Asia", "America", "../etc/passwd", ""])
async def test_odd_time_zones_are_refused_cleanly(client, user_a, queries, zone):
    agent = await create_agent(client, user_a)
    r = await client.get(f"/agents/{agent['id']}/analytics", params={"tz": zone}, headers=user_a)
    assert r.status_code == 422
