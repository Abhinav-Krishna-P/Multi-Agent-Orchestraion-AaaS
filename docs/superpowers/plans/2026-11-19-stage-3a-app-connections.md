# Stage 3A App Connections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user connects their own apps (12 to start) to one agent through Composio, picks read actions, and the agent uses them in chat.

**Architecture:** Composio's REST API (`https://backend.composio.dev/api/v3`, header `x-api-key`) through the existing `fetch_json` helper. One table, `agent_integrations`, holds each agent's connection and its switched-on actions. Chat builds a LangChain tool per switched-on action; the connected-account ID is bound by the backend, never given to the model.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, httpx, LangChain `StructuredTool`; React, TanStack Query, shadcn/ui.

**Spec:** `docs/superpowers/specs/2026-11-19-stage-3a-app-connections-design.md`

## Global Constraints

- The Composio key never reaches the browser, the model, a log line or LangSmith (`secret` headers only; never in an error message).
- The model never sees or chooses a connected-account ID.
- Every endpoint goes through `get_owned_agent`; another user's agent is a 404.
- Only actions tagged `important` and `readOnlyHint`, not `destructiveHint`, not deprecated, slug of 64 characters or fewer, are offered or accepted.
- Text from an app is untrusted: wrapped with `wrap()` and cut to 12,000 characters.
- Existing backend tests keep passing. Never push. Commit trailer: `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- Backend tests: from `backend/`, `.venv/Scripts/python -m pytest`; never two runs at once.

Composio calls (confirmed against its OpenAPI description on 2026-11-19):
- `GET /auth_configs?toolkit_slug=<app>` → `items[].id`, `is_composio_managed`; `POST /auth_configs` body `{"toolkit": {"slug": app}, "auth_config": {"type": "use_composio_managed_auth"}}` → `auth_config.id`.
- `POST /connected_accounts/link` body `{"auth_config_id", "user_id", "callback_url"}` → `redirect_url`, `connected_account_id`.
- `GET /connected_accounts/{id}` → `status` (`ACTIVE` means usable; `INITIALIZING`/`INITIATED` mean still signing in; anything else means broken), `user_id`.
- `DELETE /connected_accounts/{id}`.
- `GET /tools?toolkit_slug=<app>&limit=200` (+ `cursor`) → `items[]` with `slug`, `name`, `description`, `tags`, `input_parameters`, `is_deprecated`.
- `POST /tools/execute/{slug}` body `{"connected_account_id", "user_id", "arguments"}` → `successful`, `data`, `error`.

## Review Focus

1. User B calling any integration endpoint with user A's agent ID: 404, and no Composio call is made. Pinned in Task 2.
2. A connected-account ID or action name supplied by the client or the model: never used. The backend reads both from its own row. Pinned in Tasks 2 and 3.
3. A write or delete action name sent to `PUT …/actions`: refused. Pinned in Task 2.
4. Composio down or slow during chat: the reply still finishes with a plain-words failure. Pinned in Task 3.
5. Sign-in window closed without finishing: the row stays `pending`, the card goes back to Connect, nothing is usable. Pinned in Task 2.

---

### Task 1: Table and Composio client

**Files:**
- Modify: `backend/app/db/models.py`, `backend/app/core/config.py` (`composio_api_key: str = ""`, `frontend_url: str = "http://localhost:5173"`), `backend/app/tools/http.py` (`fetch_json(..., cache: bool = True)`)
- Create: `backend/alembic/versions/0005_agent_integrations.py`, `backend/app/integrations/__init__.py`, `backend/app/integrations/composio.py`
- Test: `backend/tests/test_integrations.py`

**Interfaces — produces:**
- `AgentIntegration` model: `id`, `agent_id` (FK agents, cascade), `user_id` (FK users, cascade), `app` text, `connected_account_id` text, `status` text (`pending`/`active`/`expired`, check constraint), `actions` JSONB list of slugs (default `[]`), `created_at`, `updated_at`; unique (`agent_id`, `app`).
- `composio.APPS: dict[str, App]` with `App(slug, name, category)` for the 12 apps; `composio.enabled() -> bool`.
- `async composio.actions(app) -> list[dict]` — offered read actions `{slug, name, description, parameters}`; cached one hour.
- `async composio.start_connection(app, user_id, callback_url) -> tuple[str, str]` (redirect URL, connected-account ID); finds or creates the app's managed auth config (remembered per process).
- `async composio.connection_status(account_id, user_id) -> str` — `active`, `pending` or `expired`; `expired` too if the account's `user_id` is not ours.
- `async composio.disconnect(account_id) -> None`.
- `async composio.run_action(slug, account_id, user_id, arguments) -> dict` — the `data` on success; raises `ToolError(error text)` when `successful` is false.

- [ ] **Step 1: Failing tests** (stand-in web via the `web` fixture from `tests/test_api_tools.py`, host `backend.composio.dev`): `test_actions_offers_only_important_read_actions` (six canned tools: read+important kept; write, destructive, not important, deprecated, 70-character slug all dropped; `x-api-key` header sent; second call makes no request); `test_start_connection_creates_the_auth_config_once` (first call: GET auth_configs empty → POST create → POST link; second call for the same app: only POST link; returns the redirect and ID; body carries our user ID and callback); `test_connection_status_mapping` (ACTIVE→active, INITIATED→pending, EXPIRED→expired, ACTIVE with another `user_id`→expired); `test_run_action_success_and_failure` (success returns data and sends account, user and arguments; `successful: false` raises `ToolError`; two identical runs make two requests); `test_key_never_in_logs` (caplog at INFO has no key).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement; write the migration by hand (create table, constraints) and run `alembic upgrade head` on the dev database.
- [ ] **Step 4:** `pytest tests/test_integrations.py tests/test_api_tools.py -q`; expect pass.
- [ ] **Step 5:** Commit `feat: agent_integrations table and Composio client`.

### Task 2: Integration endpoints

**Files:**
- Create: `backend/app/api/integrations.py` (router picked up by `main.py` like the others)
- Modify: `backend/app/api/schemas.py`
- Test: `backend/tests/test_integrations.py`

**Interfaces — produces:**
- `GET /agents/{id}/integrations` → `{"enabled": bool, "apps": [{"app", "name", "category", "logo", "status": "none"|"pending"|"active"|"expired", "actions": [{"slug","name","description","on"}]}]}`; `actions` filled only for `active`; `logo` is `https://logos.composio.dev/api/<app>`.
- `POST /agents/{id}/integrations/{app}/connect` → `{"redirect_url"}`; upserts a `pending` row with the new account ID (an old account, if any, is disconnected first; its failure is ignored).
- `POST /agents/{id}/integrations/{app}/refresh` → the app entry; asks Composio and saves `active`/`expired`; a row still `pending` stays pending.
- `PUT /agents/{id}/integrations/{app}/actions` body `{"actions": [slug]}` → the app entry; 409 unless `active`; 422 if any slug is not in `composio.actions(app)`.
- `DELETE /agents/{id}/integrations/{app}` → 204; disconnects at Composio, then deletes the row (the row is deleted even if Composio is unreachable).
- Unknown app → 404. Composio not configured → `enabled: false` on GET and 503 `integrations_unavailable` on the others.

- [ ] **Step 1: Failing tests:** list when nothing is connected (12 apps, all `none`); connect saves `pending` and returns the redirect; refresh turns it `active` and the list then carries actions, all off; refresh while Composio says INITIATED keeps `pending`; actions PUT saves and is returned as `on`; PUT with a write slug or unknown slug → 422; PUT before active → 409; delete removes the row and calls Composio's DELETE; user B gets 404 on all five routes and the stand-in records zero requests; unknown app 404; no key → GET says `enabled: false`, connect 503; deleting the agent deletes its integration rows.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest tests/test_integrations.py tests/test_agents.py -q`; expect pass.
- [ ] **Step 5:** Commit `feat: connect, refresh, choose actions and disconnect apps`.

### Task 3: App actions as chat tools

**Files:**
- Modify: `backend/app/integrations/composio.py`, `backend/app/api/chat.py`
- Test: `backend/tests/test_integrations.py`

**Interfaces — produces:** `async composio.build_tools(integrations: list[AgentIntegration], user_id) -> tuple[list[BaseTool], dict[str, str]]` (tools and their activity labels, `"Using <App name>…"`), one `StructuredTool` per switched-on action of each `active` integration, named by the action's slug in lower case, described by Composio's description, with `args_schema` set to the action's JSON parameter schema. The tool returns `wrap(<App name>, data)` cut to 12,000 characters. On failure it asks Composio for the connection's status; if that is `expired` it saves the row as `expired` and raises `ToolError("The <App name> connection has stopped working. Ask the user to reconnect <App name> in the agent's Apps step.")`; otherwise it raises the plain failure.

- [ ] **Step 1: Failing tests:** a chat turn where the scripted model calls `gmail_fetch_emails` → the stand-in receives the row's account ID and the caller's user ID, `tool_start` label is "Using Gmail…", the model receives the wrapped data; arguments named `connected_account_id` or `user_id` sent by the model do not change what is sent; an action switched off, or an integration not `active`, is not offered to the model; a failed run with status EXPIRED marks the row `expired` and the model is told to ask for a reconnect; Composio unreachable → `tool_end` not ok and the reply still finishes; 20,000 characters of data are cut.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement; in `chat.py` load the agent's integrations with the other turn data and add the tools and labels (the cards instruction is already added whenever the agent has tools; add it too when the only tools are app actions).
- [ ] **Step 4:** `pytest tests/test_integrations.py tests/test_chat.py tests/test_tool_loop.py -q`; expect pass.
- [ ] **Step 5:** Commit `feat: the agent can use connected apps' read actions`.

### Task 4: Apps step in the wizard

**Files:**
- Create: `frontend/src/pages/AgentWizard/Apps.jsx`, `frontend/src/pages/Connected.jsx`
- Modify: `frontend/src/pages/AgentWizard/index.jsx` (step `apps` between `tools` and `deploy`), `frontend/src/lib/queries.js` (hooks for the five endpoints), `frontend/src/App.jsx` (route `/app/connected`, outside the shell layout if possible), `frontend/src/pages/AgentWizard/Deploy.jsx` (count of connected apps)

- [ ] **Step 1:** Queries: `useIntegrations(agentId)`, `useConnectApp`, `useRefreshApp`, `useSetAppActions`, `useDisconnectApp`; each mutation refreshes the integrations query.
- [ ] **Step 2:** `Apps.jsx`: heading "Connect your apps", search, the same card grid as the Tools step. Per card: logo (`CardImage` from the chat cards, with an icon fallback), name, status line, and by status: `none` → Connect; `pending` → "Finish signing in…" with Check again and Cancel; `active` → "Connected · n of m actions on", Manage (popover of checkboxes, saved on change) and Disconnect (confirm dialog); `expired` → "Reconnect needed" and Reconnect. Connect opens the redirect in a new window (opened synchronously on click, then pointed at the address, so the popup is not blocked), and refreshes the app when that window posts a message, closes, or the user presses Check again. Not configured → one notice instead of the grid. Loading, error and empty-search states like the Tools step.
- [ ] **Step 3:** `Connected.jsx`: "You're connected. You can close this window." It posts `{type: "app-connected"}` to `window.opener` on the same origin and closes itself.
- [ ] **Step 4:** `npm run build` and `npm run lint`; expect both clean.
- [ ] **Step 5:** Commit `feat: Apps step in the agent wizard`.

### Task 5: Verify

- [ ] **Step 1:** Full backend suite; expect all pass.
- [ ] **Step 2:** Restart the backend. In Chrome: open the Apps step, check the 12 cards and logos render and no console errors. Then, with the owner signing in to their own Gmail: connect, switch on an action, ask the agent about recent mail, disconnect.
- [ ] **Step 3:** One fresh reviewer over the branch diff against the spec; fix confirmed Critical/Important findings; record minors in the ledger.
