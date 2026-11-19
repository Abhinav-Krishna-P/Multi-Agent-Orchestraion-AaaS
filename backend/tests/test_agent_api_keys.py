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


async def test_call_log_pages_newest_first(client, user_a, db):
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"], "Prod")
    aid, kid = uuid.UUID(agent["id"]), uuid.UUID(key["id"])
    me = await db.scalar(select(AgentApiKey.user_id).where(AgentApiKey.id == kid))
    start = datetime.now(UTC) - timedelta(hours=1)
    for i in range(25):
        db.add(ApiCall(agent_id=aid, user_id=me, key_id=kid, message=f"m{i}", reply="r", outcome="ok",
                       duration_ms=i, created_at=start + timedelta(seconds=i)))
    await db.commit()
    await client.delete(f"/agents/{agent['id']}/api/keys/{key['id']}", headers=user_a)
    url = f"/agents/{agent['id']}/api/calls"
    page = (await client.get(url, headers=user_a)).json()
    assert [c["message"] for c in page["calls"]] == [f"m{i}" for i in range(24, 4, -1)] and page["more"] is True
    assert page["calls"][0]["key_name"] == "Prod"
    rest = (await client.get(url, params={"before": page["calls"][-1]["created_at"]}, headers=user_a)).json()
    assert [c["message"] for c in rest["calls"]] == [f"m{i}" for i in range(4, -1, -1)] and rest["more"] is False


async def test_no_key_in_logs(client, user_a, caplog):
    caplog.set_level(logging.DEBUG)
    agent = await live_agent(client, user_a)
    key = await make_key(client, user_a, agent["id"])
    await client.delete(f"/agents/{agent['id']}/api/keys/{key['id']}", headers=user_a)
    assert key["key"] not in caplog.text and hash_key(key["key"]) not in caplog.text
