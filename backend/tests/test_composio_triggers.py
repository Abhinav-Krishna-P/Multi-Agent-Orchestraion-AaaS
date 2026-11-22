"""Composio triggers and the signed webhook, against the stand-in for its API."""
import base64
import hashlib
import hmac

from tests.test_api_tools import web  # noqa: F401  (fixture)
from tests.test_integrations import composio  # noqa: F401  (fixture)

SECRET = "whsec_test"
NOW = 1_800_000_000


def _signed(body: bytes, secret=SECRET, ts=NOW, id_="msg_1", prefix="v1,"):
    sig = base64.b64encode(hmac.new(secret.encode(), f"{id_}.{ts}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"webhook-id": id_, "webhook-timestamp": str(ts), "webhook-signature": prefix + sig}


async def test_trigger_types_lists_and_caches(composio):
    from app.integrations.composio import trigger_types

    found = await trigger_types("gmail")
    assert found == [{"slug": "GMAIL_NEW_GMAIL_MESSAGE", "name": "New Gmail Message", "description": "Fires on new mail.",
                      "config": {"type": "object", "properties": {"labelIds": {"type": "string"}}}}]
    assert dict(composio.last_request.url.params)["toolkit_slugs"] == "gmail"
    await trigger_types("gmail")
    assert len(composio.calls) == 1


async def test_lists_are_kept_six_hours(composio, monkeypatch):
    from app.core import cache
    from app.integrations.composio import actions, trigger_types

    seconds = []
    real_set = cache.set_json

    async def spy(key, value, ttl):
        seconds.append(ttl)
        await real_set(key, value, ttl)

    monkeypatch.setattr(cache, "set_json", spy)
    await actions("gmail")
    await trigger_types("gmail")
    assert seconds and all(ttl == 21600 for ttl in seconds)


async def test_trigger_calls_hit_the_right_paths(composio):
    from app.integrations.composio import delete_trigger, set_trigger_enabled, upsert_trigger

    assert await upsert_trigger("GMAIL_NEW_GMAIL_MESSAGE", "u1", "ca_1", {"labelIds": "INBOX"}) == "ti_1"
    assert composio.made("POST", "/trigger_instances/GMAIL_NEW_GMAIL_MESSAGE/upsert") == [
        {"user_id": "u1", "connected_account_id": "ca_1", "trigger_config": {"labelIds": "INBOX"}}]
    await set_trigger_enabled("ti_1", True)
    await set_trigger_enabled("ti_1", False)
    assert composio.made("PATCH", "/trigger_instances/manage/ti_1") == [{"status": "enable"}, {"status": "disable"}]
    await delete_trigger("ti_1")
    assert len(composio.made("DELETE", "/trigger_instances/manage/ti_1")) == 1


async def test_webhook_subscription_uses_v31(composio):
    from app.integrations.composio import create_webhook, update_webhook

    assert await create_webhook("https://x.test/hook") == ("ws_1", "whsec_abc")
    assert composio.made("POST", "/webhook_subscriptions") == [{
        "webhook_url": "https://x.test/hook", "version": "V3",
        "enabled_events": ["composio.trigger.message", "composio.connected_account.expired"]}]
    assert composio.last_request.url.path == "/api/v3.1/webhook_subscriptions"
    await update_webhook("ws_1", "https://y.test/hook")
    assert composio.made("PATCH", "/webhook_subscriptions/ws_1") == [{"webhook_url": "https://y.test/hook"}]


def test_verify_webhook():
    from app.integrations.composio import verify_webhook

    body = b'{"type":"composio.trigger.message"}'
    assert verify_webhook(_signed(body), body, SECRET, NOW)
    assert verify_webhook(_signed(body), body, SECRET, NOW + 300)
    other = _signed(body, secret="nope")["webhook-signature"]
    both = {**_signed(body), "webhook-signature": other + " " + _signed(body)["webhook-signature"]}
    assert verify_webhook(both, body, SECRET, NOW)  # any one of several entries
    assert not verify_webhook(_signed(body, secret="nope"), body, SECRET, NOW)
    assert not verify_webhook(_signed(body), body + b" ", SECRET, NOW)
    assert not verify_webhook(_signed(body), body, SECRET, NOW + 301)
    assert not verify_webhook(_signed(body), body, "", NOW)
    for missing in ("webhook-id", "webhook-timestamp", "webhook-signature"):
        assert not verify_webhook({k: v for k, v in _signed(body).items() if k != missing}, body, SECRET, NOW)
    assert not verify_webhook({**_signed(body), "webhook-timestamp": "soon"}, body, SECRET, NOW)
    assert not verify_webhook({**_signed(body), "webhook-signature": "v1,é"}, body, SECRET, NOW)
