"""Composio's events: signed, matched to event automations, and the setup command."""
import base64
import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AgentIntegration, Automation, AutomationRun
from tests.fakes import scripted
from tests.test_analytics import events, named  # noqa: F401  (fixture and helper)
from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_approvals import switch_on
from tests.test_automation_run import fresh, make, runs, use_run_model  # noqa: F401  (fixture)
from tests.test_chat import live_chat  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)

SECRET = "whsec_test"
TRIGGER = {"composio_trigger_id": "ti_1", "app": "github"}


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setattr(get_settings(), "composio_webhook_secret", SECRET)


def signed(payload, *, secret=SECRET, msg_id="msg_1", raw: bytes | None = None) -> dict:
    body = raw if raw is not None else json.dumps(payload).encode()
    stamp = str(int(time.time()))
    sig = base64.b64encode(hmac.new(secret.encode(), f"{msg_id}.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"content": body, "headers": {"webhook-id": msg_id, "webhook-timestamp": stamp, "webhook-signature": f"v1,{sig}",
                                         "content-type": "application/json"}}


def trigger_event(trigger_id="ti_1", log_id="log_1"):
    return {"id": "evt_1", "type": "composio.trigger.message", "timestamp": "now",
            "metadata": {"log_id": log_id, "trigger_slug": "GITHUB_ISSUE_ADDED_EVENT", "trigger_id": trigger_id},
            "data": {"title": "Bug"}}


async def event_automation(db, agent, **change):
    return await make(db, agent, **{"trigger_kind": "event", "trigger": TRIGGER, "trigger_text": "new issue", **change})


async def test_a_signed_event_runs_the_matching_automation_once(client, live_chat, composio, db, use_run_model):  # noqa: F811
    from app.automations import run

    agent, _ = live_chat
    a = await event_automation(db, agent, tools=[], locked={})
    use_run_model(scripted(["Noted.", "Noted."]))
    for _ in range(2):  # delivered twice
        r = await client.post("/webhooks/composio", **signed(trigger_event()))
        assert r.status_code == 200 and r.json() == {"ok": True}
        await run.wait_for_runs()
    found = await runs(db)
    assert [(x.automation_id, x.source, x.event, x.event_key) for x in found] == [(a.id, "event", {"title": "Bug"}, "log_1")]


async def test_a_wrong_signature_is_refused_and_nothing_runs(client, live_chat, db):  # noqa: F811
    from app.automations import run

    agent, _ = live_chat
    await event_automation(db, agent)
    for request in (signed(trigger_event(), secret="other"), {"content": b"{}"}):
        assert (await client.post("/webhooks/composio", **request)).status_code == 401
    await run.wait_for_runs()
    assert await runs(db) == []


async def test_no_secret_configured_refuses_everything(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "composio_webhook_secret", "")
    assert (await client.post("/webhooks/composio", **signed(trigger_event(), secret=""))).status_code == 401


async def test_other_triggers_paused_automations_and_stopped_agents_do_not_run(client, user_a, live_chat, db, use_run_model):  # noqa: F811
    from app.automations import run

    agent, _ = live_chat
    await event_automation(db, agent, name="elsewhere", trigger={**TRIGGER, "composio_trigger_id": "ti_other"})
    await event_automation(db, agent, name="paused", status="paused")
    use_run_model(scripted(["x"]))
    assert (await client.post("/webhooks/composio", **signed(trigger_event()))).status_code == 200
    await run.wait_for_runs()
    assert await runs(db) == []
    await event_automation(db, agent, name="stopped agent")
    assert (await client.post(f"/agents/{agent['id']}/stop", headers=user_a)).status_code == 200
    assert (await client.post("/webhooks/composio", **signed(trigger_event(log_id="log_2"), msg_id="msg_2"))).status_code == 200
    await run.wait_for_runs()
    assert await runs(db) == []


async def test_bad_json_with_a_good_signature_is_ignored(client):
    assert (await client.post("/webhooks/composio", **signed(None, raw=b"not json"))).status_code == 200
    assert (await client.post("/webhooks/composio", **signed(None, raw=b"[1]"))).status_code == 200
    assert (await client.post("/webhooks/composio", **signed({"type": "something.else"}))).status_code == 200


async def test_an_expired_account_marks_the_connection_and_its_automations(client, user_a, live_chat, composio, db, events):  # noqa: F811
    agent, _ = live_chat
    await switch_on(client, user_a, agent["id"], "GMAIL_SEND_EMAIL")
    row = (await db.scalars(select(AgentIntegration).where(AgentIntegration.agent_id == uuid.UUID(agent["id"])))).one()
    by_tool = await make(db, agent, name="by tool")
    by_trigger = await event_automation(db, agent, name="by trigger", tools=[], locked={}, trigger={**TRIGGER, "app": "gmail"})
    unrelated = await event_automation(db, agent, name="unrelated", tools=[], locked={})
    body = {"id": "e", "type": "composio.connected_account.expired", "metadata": {"connected_account_id": row.connected_account_id}, "data": {}}
    assert (await client.post("/webhooks/composio", **signed(body))).status_code == 200
    assert (await fresh(db, AgentIntegration, row.id)).status == "expired"
    for automation in (by_tool, by_trigger):
        automation = await fresh(db, Automation, automation.id)
        assert (automation.status, automation.status_reason) == ("error", "Reconnect Gmail")
    assert (await fresh(db, Automation, unrelated.id)).status == "active"
    assert named(events, "connection_expired")


async def test_create_saves_both_lines_without_printing_the_secret(tmp_path, capsys, composio):  # noqa: F811
    from app.automations.webhook_setup import main

    env = tmp_path / ".env"
    env.write_bytes(b"A=1\r\nCOMPOSIO_WEBHOOK_SECRET=old\r\nB=2\r\n")
    await main(["create", "https://x.trycloudflare.com/"], env_path=env)
    out = capsys.readouterr().out
    assert out.strip() == "Saved the webhook secret to backend/.env." and "whsec_abc" not in out
    assert env.read_bytes() == b"A=1\r\nCOMPOSIO_WEBHOOK_SECRET=whsec_abc\r\nB=2\r\nCOMPOSIO_WEBHOOK_ID=ws_1\r\n"
    assert composio.made("POST", "/webhook_subscriptions")[0]["webhook_url"] == "https://x.trycloudflare.com/webhooks/composio"


async def test_update_changes_the_address_of_the_saved_subscription(tmp_path, capsys, composio):  # noqa: F811
    from app.automations.webhook_setup import main

    env = tmp_path / ".env"
    env.write_text("COMPOSIO_WEBHOOK_ID=ws_9\n")
    await main(["update", "https://y.trycloudflare.com"], env_path=env)
    assert composio.made("PATCH", "/webhook_subscriptions/ws_9")[0]["webhook_url"] == "https://y.trycloudflare.com/webhooks/composio"
    assert "whsec" not in capsys.readouterr().out
