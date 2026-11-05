"""App connections through Composio, tested against a stand-in for its API (no real call is made)."""
import json
import logging

import httpx
import pytest

from tests.conftest import USER_A_ID
from tests.test_api_tools import web  # noqa: F401  (fixture)

HOST = "backend.composio.dev"


def _tool(slug, *tags, deprecated=False):
    return {"slug": slug, "name": slug.replace("_", " ").title(), "description": f"Does {slug}.", "tags": list(tags),
            "is_deprecated": deprecated, "input_parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}


GMAIL_TOOLS = [
    _tool("GMAIL_FETCH_EMAILS", "important", "readOnlyHint"),
    {**_tool("GMAIL_SEND_EMAIL", "important"), "input_parameters": {"type": "object", "required": ["recipient_email", "body"], "properties": {
        "recipient_email": {"type": "string", "title": "Recipient Email"}, "subject": {"type": "string", "title": "Subject"},
        "body": {"type": "string"}}}},
    _tool("GMAIL_DELETE_MESSAGE", "important", "destructiveHint"),
    _tool("GMAIL_LIST_LABELS", "readOnlyHint"),
    _tool("GMAIL_OLD_SEARCH", "important", "readOnlyHint", deprecated=True),
    _tool("GMAIL_" + "X" * 64, "important", "readOnlyHint"),
]


class FakeComposio:
    """Answers the handful of Composio calls the platform makes, and remembers each one."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.links = 0
        self.auth_configs: list[dict] = []
        self.status = "ACTIVE"
        self.account_user = USER_A_ID
        self.result = {"successful": True, "data": {"messages": [{"subject": "Hello"}]}, "error": None}

    def __call__(self, request: httpx.Request):
        path = request.url.path.removeprefix("/api/v3")
        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, path, body))
        self.last_request = request
        if path == "/tools":
            return {"items": GMAIL_TOOLS, "next_cursor": None}
        if path == "/auth_configs" and request.method == "GET":
            return {"items": self.auth_configs}
        if path == "/auth_configs":
            return {"toolkit": body["toolkit"], "auth_config": {"id": "ac_new"}}
        if path == "/connected_accounts/link":
            self.links += 1
            return {"redirect_url": "https://connect.composio.dev/link/abc", "connected_account_id": f"ca_{self.links}"}
        if path.startswith("/connected_accounts/") and request.method == "DELETE":
            return {"success": True}
        if path.startswith("/connected_accounts/"):
            return {"id": path.rsplit("/", 1)[-1], "status": self.status, "user_id": self.account_user}
        if path.startswith("/tools/execute/"):
            return self.result
        raise AssertionError(f"unexpected Composio call: {request.method} {path}")

    def made(self, method: str, path: str) -> list[dict]:
        return [body for m, p, body in self.calls if m == method and p == path]


@pytest.fixture
def composio(web):  # noqa: F811
    from app.integrations import composio as module

    fake = FakeComposio()
    web.replies[HOST] = fake
    module._auth_configs.clear()
    return fake


# --- the Composio client --------------------------------------------------------------------


async def test_actions_offers_only_important_read_actions(composio):
    from app.integrations.composio import actions

    offered = await actions("gmail")
    # Reads, and actions that change things (offered as "write"); never destructive ones.
    assert [(action["slug"], action["kind"]) for action in offered] == [("GMAIL_FETCH_EMAILS", "read"), ("GMAIL_SEND_EMAIL", "write")]
    assert offered[0]["name"] == "Gmail Fetch Emails" and offered[0]["description"] == "Does GMAIL_FETCH_EMAILS."
    assert offered[0]["parameters"]["properties"] == {"query": {"type": "string"}}
    assert composio.last_request.headers["x-api-key"] == "test-composio-key"
    assert dict(composio.last_request.url.params)["toolkit_slug"] == "gmail"
    await actions("gmail")
    assert len(composio.calls) == 1  # remembered: the wizard asks often


async def test_start_connection_creates_the_auth_config_once(composio):
    from app.integrations.composio import start_connection

    assert await start_connection("gmail", USER_A_ID, "http://localhost:5173/app/connected") == (
        "https://connect.composio.dev/link/abc", "ca_1",
    )
    assert [(m, p) for m, p, _ in composio.calls] == [("GET", "/auth_configs"), ("POST", "/auth_configs"), ("POST", "/connected_accounts/link")]
    assert composio.made("POST", "/auth_configs") == [{"toolkit": {"slug": "gmail"}, "auth_config": {"type": "use_composio_managed_auth"}}]
    assert composio.made("POST", "/connected_accounts/link") == [
        {"auth_config_id": "ac_new", "user_id": USER_A_ID, "callback_url": "http://localhost:5173/app/connected"}
    ]
    assert (await start_connection("gmail", USER_A_ID, "http://localhost:5173/app/connected"))[1] == "ca_2"
    assert len(composio.made("POST", "/auth_configs")) == 1 and len(composio.made("POST", "/connected_accounts/link")) == 2


async def test_start_connection_reuses_an_existing_managed_auth_config(composio):
    from app.integrations.composio import start_connection

    composio.auth_configs = [
        {"id": "ac_custom", "is_composio_managed": False, "toolkit": {"slug": "gmail"}},
        {"id": "ac_have", "is_composio_managed": True, "toolkit": {"slug": "gmail"}},
    ]
    await start_connection("gmail", USER_A_ID, "http://x/app/connected")
    assert composio.made("POST", "/auth_configs") == []
    assert composio.made("POST", "/connected_accounts/link")[0]["auth_config_id"] == "ac_have"


@pytest.mark.parametrize(
    "status, owner, expected",
    [("ACTIVE", USER_A_ID, "active"), ("INITIATED", USER_A_ID, "pending"), ("INITIALIZING", USER_A_ID, "pending"),
     ("EXPIRED", USER_A_ID, "expired"), ("FAILED", USER_A_ID, "expired"), ("ACTIVE", "someone-else", "expired")],
)
async def test_connection_status_mapping(composio, status, owner, expected):
    from app.integrations.composio import connection_status

    composio.status, composio.account_user = status, owner
    assert await connection_status("ca_1", USER_A_ID) == expected


async def test_run_action_success_and_failure(composio):
    from app.integrations.composio import run_action
    from app.tools.http import ToolError

    assert await run_action("GMAIL_FETCH_EMAILS", "ca_1", USER_A_ID, {"query": "is:unread"}) == {"messages": [{"subject": "Hello"}]}
    assert composio.made("POST", "/tools/execute/GMAIL_FETCH_EMAILS") == [
        {"connected_account_id": "ca_1", "user_id": USER_A_ID, "arguments": {"query": "is:unread"}}
    ]
    await run_action("GMAIL_FETCH_EMAILS", "ca_1", USER_A_ID, {"query": "is:unread"})
    assert len(composio.made("POST", "/tools/execute/GMAIL_FETCH_EMAILS")) == 2  # an action is never answered from memory
    composio.result = {"successful": False, "data": {}, "error": "Mailbox not found"}
    with pytest.raises(ToolError, match="Mailbox not found"):
        await run_action("GMAIL_FETCH_EMAILS", "ca_1", USER_A_ID, {})


async def test_key_never_in_logs(composio, web, caplog):  # noqa: F811
    from app.integrations.composio import actions, run_action

    from app.tools.http import ToolError

    with caplog.at_level(logging.INFO):
        await actions("gmail")
        await run_action("GMAIL_FETCH_EMAILS", "ca_1", USER_A_ID, {})
        for failure in (httpx.Response(500, text="boom test-composio-key"), httpx.ConnectError("down")):
            web.replies[HOST] = failure  # failures are what get logged
            with pytest.raises(ToolError) as raised:
                await run_action("GMAIL_FETCH_EMAILS", "ca_1", USER_A_ID, {})
            assert "test-composio-key" not in str(raised.value)
    assert "Composio call failed" in caplog.text and "test-composio-key" not in caplog.text
