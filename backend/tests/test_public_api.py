"""POST /v1/run: calling an agent with its API key."""
import asyncio
import logging

import pytest
from sqlalchemy import delete, select

from app.core import cache
from app.core.api_keys import hash_key
from app.db.models import AgentApiKey, ApiCall, LlmKey
from tests.fakes import scripted
from tests.test_agent_api_keys import make_key
from tests.test_analytics import events, named  # noqa: F401  (fixture and helper)
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approvals import executed, switch_on
from tests.test_cache import RaisingRedis
from tests.test_chat import live_chat  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)
from tests.test_tool_loop import call


@pytest.fixture
def use_api_model(monkeypatch):
    from app.api import public

    def _use(model):
        monkeypatch.setattr(public, "model_factory", lambda provider, model_id, key: model)
        return model

    return _use


async def run(client, key, message="Hi"):
    headers = {"Authorization": f"Bearer {key}"} if key is not None else {}
    return await client.post("/v1/run", json={"message": message}, headers=headers)


async def calls(db) -> list[ApiCall]:
    return (await db.scalars(select(ApiCall).order_by(ApiCall.created_at).execution_options(populate_existing=True))).all()


async def test_a_call_returns_the_reply_as_json(client, user_a, live_chat, use_api_model, events, db):  # noqa: F811
    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    use_api_model(scripted(["Hello from the agent"]))
    r = await run(client, key, "Say hello")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reply"] == "Hello from the agent" and body["agent_id"] == agent["id"]
    assert body["tools_used"] == [] and body["sources"] == [] and body["duration_ms"] >= 0 and body["id"]
    (row,) = await calls(db)
    assert row.outcome == "ok" and row.message == "Say hello" and row.reply == "Hello from the agent"
    assert str(row.id) == body["id"]
    (event,) = named(events, "api_call")
    assert event["success"] is True and event["agent_id"] == agent["id"]
    used = await db.scalar(select(AgentApiKey.last_used_at).execution_options(populate_existing=True))
    assert used is not None


async def test_bad_keys_are_401(client, user_a, live_chat, db):  # noqa: F811
    agent, _ = live_chat
    revoked = await make_key(client, user_a, agent["id"])
    await client.delete(f"/agents/{agent['id']}/api/keys/{revoked['id']}", headers=user_a)
    results = [await run(client, None), await run(client, "nope"), await run(client, revoked["key"])]
    for r in results:
        assert r.status_code == 401 and r.json()["detail"]["code"] == "invalid_api_key"
    assert len({r.json()["detail"]["message"] for r in results}) == 1
    assert await calls(db) == []


@pytest.mark.parametrize("body", [{"message": "   "}, {}, {"message": "x" * 8001}])
async def test_blank_or_long_message_is_422(client, user_a, live_chat, db, body):  # noqa: F811
    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    r = await client.post("/v1/run", json=body, headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_request"
    assert isinstance(r.json()["detail"]["message"], str)
    assert await calls(db) == []


async def test_stopped_agent_or_missing_llm_key_is_409(client, user_a, live_chat, use_api_model, db):  # noqa: F811
    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    use_api_model(scripted(["x"]))
    await db.execute(delete(LlmKey))
    await db.commit()
    r = await run(client, key)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_llm_key"
    r = await client.post(f"/agents/{agent['id']}/stop", headers=user_a)
    assert r.status_code == 200, r.text
    r = await run(client, key)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "agent_not_live"


async def test_rate_limit(client, user_a, live_chat, use_api_model, db):  # noqa: F811
    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    await client.patch(f"/agents/{agent['id']}/api", json={"calls_per_minute": 2}, headers=user_a)
    use_api_model(scripted(["a"], ["b"], ["c"]))
    assert [(await run(client, key)).status_code for _ in range(2)] == [200, 200]
    r = await run(client, key)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert len(await calls(db)) == 2


async def test_rate_limit_fails_open_when_redis_is_down(client, user_a, live_chat, use_api_model, monkeypatch):  # noqa: F811
    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    await client.patch(f"/agents/{agent['id']}/api", json={"calls_per_minute": 1}, headers=user_a)
    stub = RaisingRedis()
    monkeypatch.setattr(cache, "client", stub)
    use_api_model(scripted(["a"], ["b"]))
    assert [(await run(client, key)).status_code for _ in range(2)] == [200, 200]
    assert stub.calls == 1  # tried once, then Redis was left alone


async def test_actions_run_with_caller_named_recipient(client, user_a, live_chat, use_api_model, composio, events):  # noqa: F811
    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    key = (await make_key(client, user_a, agent["id"]))["key"]
    use_api_model(scripted(call("gmail_send_email", recipient_email="bob@x.com", subject="Hi", body="hi"), ["Sent."]))
    r = await run(client, key, "Email bob@x.com hi")
    assert r.status_code == 200, r.text
    assert executed(composio)[-1]["arguments"]["recipient_email"] == "bob@x.com"
    assert r.json()["tools_used"][0] == {"name": "gmail_send_email", "ok": True, "result": None}
    assert [e["source"] for e in named(events, "tool_called")] == ["api"]


async def test_actions_off_hides_writes(client, user_a, live_chat, use_api_model, composio):  # noqa: F811
    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    key = (await make_key(client, user_a, agent["id"]))["key"]
    await client.patch(f"/agents/{agent['id']}/api", json={"actions": False}, headers=user_a)
    model = use_api_model(scripted(["Done"]))
    r = await run(client, key, "Email bob@x.com hi")
    assert r.status_code == 200, r.text
    assert "gmail_send_email" not in (model.bound or [])


async def test_a_failed_run_is_502_and_logged(client, user_a, live_chat, use_api_model, monkeypatch, db, events):  # noqa: F811
    from app.api import public

    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    use_api_model(scripted(["x"], fail_after=0))
    r = await run(client, key)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "agent_failed"
    assert "sk-leaky" not in r.text and "exploded" not in r.text
    assert [c.outcome for c in await calls(db)] == ["agent_failed"]
    assert named(events, "api_call")[-1]["success"] is False

    async def slow(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(public.unattended, "play", slow)
    monkeypatch.setattr(public, "RUN_SECONDS", 0.01)
    r = await run(client, key)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "agent_failed"
    assert [c.outcome for c in await calls(db)] == ["agent_failed", "agent_failed"]


async def test_the_key_never_reaches_the_log(client, user_a, live_chat, use_api_model, caplog):  # noqa: F811
    agent, _ = live_chat
    good = (await make_key(client, user_a, agent["id"]))["key"]
    revoked = await make_key(client, user_a, agent["id"])
    await client.delete(f"/agents/{agent['id']}/api/keys/{revoked['id']}", headers=user_a)
    use_api_model(scripted(["ok"]))
    with caplog.at_level(logging.DEBUG):
        assert (await run(client, good)).status_code == 200
        assert (await run(client, revoked["key"])).status_code == 401
    for secret in (good, hash_key(good), revoked["key"], hash_key(revoked["key"])):
        assert secret not in caplog.text


async def test_no_transaction_is_open_while_the_agent_runs(client, user_a, live_chat, use_api_model, monkeypatch):  # noqa: F811
    from app.api import public

    agent, _ = live_chat
    key = (await make_key(client, user_a, agent["id"]))["key"]
    use_api_model(scripted(["ok"]))
    sessions, open_during_run = [], []
    real_build, real_play = public.build_toolset, public.unattended.play

    async def build(db, *args, **kwargs):
        sessions.append(db)
        return await real_build(db, *args, **kwargs)

    async def play(*args, **kwargs):
        open_during_run.append(sessions[0].in_transaction())
        return await real_play(*args, **kwargs)

    monkeypatch.setattr(public, "build_toolset", build)
    monkeypatch.setattr(public.unattended, "play", play)
    assert (await run(client, key)).status_code == 200
    assert open_during_run == [False]
