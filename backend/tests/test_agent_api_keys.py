import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.api_keys import hash_key
from app.db.models import AgentApiKey, ApiCall
from tests.test_sessions import live_agent


async def make_key(client, headers, agent_id, name="Server"):
    r = await client.post(f"/agents/{agent_id}/api/keys", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_returns_the_key_once(client, user_a, db):
    agent = await live_agent(client, user_a)
    body = await make_key(client, user_a, agent["id"])
    assert body["key"].startswith("cap_") and len(body["key"]) > 40
    assert body["hint"] == body["key"][-4:]
    r = await client.get(f"/agents/{agent['id']}/api", headers=user_a)
    (row,) = r.json()["keys"]
    assert "key" not in row and row["id"] == body["id"]
    stored = await db.scalar(select(AgentApiKey.key_hash).where(AgentApiKey.id == uuid.UUID(body["id"])))
    assert stored == hash_key(body["key"]) and stored != body["key"]


async def test_revoke_hides_the_key_and_is_final(client, user_a):
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"])
    url = f"/agents/{agent['id']}/api/keys/{key['id']}"
    assert (await client.delete(url, headers=user_a)).status_code == 204
    assert (await client.get(f"/agents/{agent['id']}/api", headers=user_a)).json()["keys"] == []
    assert (await client.delete(url, headers=user_a)).status_code == 404


async def test_eleventh_active_key_is_refused(client, user_a):
    agent = await live_agent(client, user_a)
    keys = [await make_key(client, user_a, agent["id"], f"k{i}") for i in range(10)]
    r = await client.post(f"/agents/{agent['id']}/api/keys", json={"name": "x"}, headers=user_a)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_many_keys"
    await client.delete(f"/agents/{agent['id']}/api/keys/{keys[0]['id']}", headers=user_a)
    await make_key(client, user_a, agent["id"], "again")


async def test_settings_defaults_and_bounds(client, user_a):
    agent = await live_agent(client, user_a)
    url = f"/agents/{agent['id']}/api"
    assert (await client.get(url, headers=user_a)).json()["settings"] == {"actions": True, "calls_per_minute": 60}
    for bad in (0, 601):
        assert (await client.patch(url, json={"calls_per_minute": bad}, headers=user_a)).status_code == 422
    r = await client.patch(url, json={"actions": False, "calls_per_minute": 5}, headers=user_a)
    assert r.json()["settings"] == {"actions": False, "calls_per_minute": 5}
    assert (await client.get(url, headers=user_a)).json()["settings"] == {"actions": False, "calls_per_minute": 5}


async def test_another_user_cannot_see_or_change(client, user_a, user_b):
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"])
    url = f"/agents/{agent['id']}/api"
    assert (await client.get(url, headers=user_b)).status_code == 404
    assert (await client.post(f"{url}/keys", json={"name": "x"}, headers=user_b)).status_code == 404
    assert (await client.patch(url, json={"actions": False}, headers=user_b)).status_code == 404
    assert (await client.delete(f"{url}/keys/{key['id']}", headers=user_b)).status_code == 404
    assert (await client.get(f"{url}/calls", headers=user_b)).status_code == 404


async def test_deleting_the_agent_removes_keys_and_calls(client, user_a, db):
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"])
    aid = uuid.UUID(agent["id"])
    me = await db.scalar(select(AgentApiKey.user_id).where(AgentApiKey.id == uuid.UUID(key["id"])))
    db.add(ApiCall(agent_id=aid, user_id=me, message="m", reply="r", outcome="ok", duration_ms=1))
    await db.commit()
    assert (await client.delete(f"/agents/{agent['id']}", headers=user_a)).status_code == 204
    db.expire_all()
    for model in (AgentApiKey, ApiCall):
        assert await db.scalar(select(func.count()).select_from(model).where(model.agent_id == aid)) == 0


async def seed_calls(client, user_a, db, stamps):
    """Insert one call per (created_at, outcome) stamp for a fresh agent with a revoked key 'Prod'."""
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"], "Prod")
    aid, kid = uuid.UUID(agent["id"]), uuid.UUID(key["id"])
    me = await db.scalar(select(AgentApiKey.user_id).where(AgentApiKey.id == kid))
    for i, (at, outcome) in enumerate(stamps):
        db.add(ApiCall(agent_id=aid, user_id=me, key_id=kid, message=f"m{i}", reply="r", outcome=outcome,
                       duration_ms=i, created_at=at))
    await db.commit()
    await client.delete(f"/agents/{agent['id']}/api/keys/{key['id']}", headers=user_a)
    return agent


def at(day, hour=12, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


async def test_call_days_count_failed_and_order(client, user_a, db):
    stamps = [(at(19, 10, i), "ok") for i in range(3)] + [(at(20, 10, i), "ok") for i in range(4)]
    stamps.append((at(20, 11), "agent_failed"))
    agent = await seed_calls(client, user_a, db, stamps)
    r = await client.get(f"/agents/{agent['id']}/api/calls/days", headers=user_a)
    assert r.json() == {"days": [{"date": "2026-11-20", "calls": 5, "failed": 1},
                                 {"date": "2026-11-19", "calls": 3, "failed": 0}]}


async def test_call_days_use_the_given_zone(client, user_a, db):
    agent = await seed_calls(client, user_a, db, [(at(20, 20), "ok")])  # 01:30 on the 21st in Kolkata
    url = f"/agents/{agent['id']}/api/calls"
    days = (await client.get(f"{url}/days", params={"tz": "Asia/Kolkata"}, headers=user_a)).json()["days"]
    assert [d["date"] for d in days] == ["2026-11-21"]
    page = (await client.get(url, params={"day": "2026-11-21", "tz": "Asia/Kolkata"}, headers=user_a)).json()
    assert page["total"] == 1
    page = (await client.get(url, params={"day": "2026-11-21"}, headers=user_a)).json()
    assert page["total"] == 0


async def test_call_page_newest_first_and_counts(client, user_a, db):
    stamps = [(at(20, 8, i), "ok") for i in range(13)] + [(at(19), "ok")]
    agent = await seed_calls(client, user_a, db, stamps)
    url, day = f"/agents/{agent['id']}/api/calls", "2026-11-20"
    one = (await client.get(url, params={"day": day}, headers=user_a)).json()
    assert [c["message"] for c in one["calls"]] == [f"m{i}" for i in range(12, 2, -1)]
    assert (one["page"], one["pages"], one["total"]) == (1, 2, 13)
    assert one["calls"][0]["key_name"] == "Prod"
    two = (await client.get(url, params={"day": day, "page": 2}, headers=user_a)).json()
    assert [c["message"] for c in two["calls"]] == ["m2", "m1", "m0"]
    past = (await client.get(url, params={"day": day, "page": 9}, headers=user_a)).json()
    assert (past["calls"], past["pages"], past["total"]) == ([], 2, 13)


async def test_recent_calls_are_the_five_newest_across_days(client, user_a, db):
    stamps = [(at(19, 9, i), "ok") for i in range(3)] + [(at(20, 9, i), "ok") for i in range(3)]
    agent = await seed_calls(client, user_a, db, stamps)
    url = f"/agents/{agent['id']}/api/calls/recent"
    calls = (await client.get(url, headers=user_a)).json()["calls"]
    assert [c["message"] for c in calls] == ["m5", "m4", "m3", "m2", "m1"] and calls[0]["key_name"] == "Prod"
    small = await seed_calls(client, user_a, db, [(at(20), "ok")])
    assert len((await client.get(f"/agents/{small['id']}/api/calls/recent", headers=user_a)).json()["calls"]) == 1


async def test_call_log_rejects_bad_input_and_strangers(client, user_a, user_b, db):
    agent = await seed_calls(client, user_a, db, [(at(20), "ok")])
    url = f"/agents/{agent['id']}/api/calls"
    for params in ({"tz": "Nope/Zone"}, {"day": "2026-11-20", "tz": "Nope/Zone"}):
        assert (await client.get(f"{url}/days" if "day" not in params else url, params=params, headers=user_a)).status_code == 422
    assert (await client.get(url, headers=user_a)).status_code == 422
    assert (await client.get(url, params={"day": "soon"}, headers=user_a)).status_code == 422
    assert (await client.get(url, params={"day": "2026-11-20", "page": 0}, headers=user_a)).status_code == 422
    assert (await client.get(f"{url}/days", headers=user_b)).status_code == 404
    assert (await client.get(f"{url}/recent", headers=user_b)).status_code == 404
    assert (await client.get(url, params={"day": "2026-11-20"}, headers=user_b)).status_code == 404


async def test_no_key_in_logs(client, user_a, caplog):
    caplog.set_level(logging.DEBUG)
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"])
    await client.delete(f"/agents/{agent['id']}/api/keys/{key['id']}", headers=user_a)
    assert key["key"] not in caplog.text and hash_key(key["key"]) not in caplog.text
