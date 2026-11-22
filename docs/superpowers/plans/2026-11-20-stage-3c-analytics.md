# Stage 3C Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usage events go to PostHog from the backend, and the Analytics page shows each agent's numbers, read back from PostHog by the backend.

**Architecture:** `app/analytics/posthog.py` sends events in the background (capture API) and runs queries (query API, HogQL with placeholders). Events are captured where things happen; `GET /agents/{id}/analytics` runs three queries and shapes them. The page draws tiles, an SVG bar chart and a table.

**Tech Stack:** FastAPI, httpx via `fetch_json`, PostHog capture and query APIs; React.

**Spec:** `docs/superpowers/specs/2026-11-20-stage-3c-analytics-design.md`

## Global Constraints

- No user content in an event: allowed property names are exactly `user_id`, `agent_id`, `session_id`, `tool_name`, `tool_type`, `app`, `success`, `duration_ms`, `search_mode`, `results_count`, `decision`, `outcome`, `source_type`, `chunk_count`, `status`, plus `$process_person_profile`.
- Sending never blocks or breaks a request; failures are logged by type and dropped.
- Queries take the agent ID, user ID and days as placeholders, never pasted into the text.
- Tests never send a real event (`posthog.recorder`).
- Never push. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A PostHog outage during chat or upload: the user sees nothing different. Pinned in Task 1.
2. Another user's agent ID on the analytics endpoint: 404, no query run. Pinned in Task 2.
3. An event carrying message text, arguments or a document name: impossible by the allowed-name check. Pinned in Task 1.
4. A day with no activity: shown as zero, not missing. Pinned in Task 2.
5. Analytics not configured: the page says so, nothing errors. Pinned in Tasks 2 and 3.

---

### Task 1: Events

**Files:** Create `backend/app/analytics/__init__.py`, `backend/app/analytics/posthog.py`. Modify `core/config.py` (`posthog_api_key`, `posthog_host`, `posthog_project_id`, `posthog_personal_api_key`), `api/sessions.py`, `api/chat.py`, `agent/runner.py`, `integrations/composio.py`, `api/integrations.py`, `rag/ingest.py`, `tests/conftest.py` (PostHog keys blank). Test: `backend/tests/test_analytics.py`.

**Produces:** `posthog.capture(event: str, user_id, **properties) -> None` (drops `None` values, refuses property names outside the allowed set with `ValueError`); `posthog.recorder: list | None`; `run_turn(..., track: dict | None)` where `track = {"user_id", "agent_id", "session_id", "search_mode", "tool_kinds": {name: (type, app|None)}}`.

- [ ] **Step 1: Failing tests:** `capture` with a key posts `{api_key, event, distinct_id, properties}` to `{host}/i/v0/e/` in the background; a PostHog failure raises nothing; no key and no recorder → no request; an unknown property name → `ValueError`. Events with exact properties: `session_started`; `message_sent`; `tool_called` for the calculator (`builtin`, success, a duration ≥ 0), a Gmail read (`composio`, app `gmail`) and a failing call (`success: false`); `knowledge_base_searched` (`search_mode`, `results_count`); `write_action_decision` approved/done and rejected (no outcome); `connection_expired` (app) from a sign-in error and from the check; `document_ingested` ready and failed. The details form tool sends no `tool_called`.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest tests/test_analytics.py tests/test_chat.py tests/test_tool_loop.py tests/test_documents.py tests/test_approval_decisions.py tests/test_reconnect.py -q`; pass.
- [ ] **Step 5:** Commit `feat: usage events to PostHog`.

### Task 2: Analytics endpoint

**Files:** Create `backend/app/api/analytics.py`. Modify `main.py`, `analytics/posthog.py` (`query(sql, values) -> list[list]`, `enabled_queries() -> bool`). Test: `backend/tests/test_analytics.py`.

**Produces:** `GET /agents/{id}/analytics?range=7d|30d|90d` → `{"enabled": true, "range", "totals": {"sessions","messages","tool_calls","tool_failures","success_rate","avg_tool_ms","kb_searches","approved","rejected","connection_problems","documents"}, "days": [{"date","messages","tool_calls"}], "tools": [{"name","type","app","calls","failures","avg_ms"}]}` or `{"enabled": false}`; 503 `analytics_unavailable` when a query fails; cached 60 s per agent and range.

- [ ] **Step 1: Failing tests** (`posthog.query` replaced by a stand-in): shape from canned rows; a missing day is zero and the list has one entry per day of the range; the values passed are the agent ID, user ID and days, and the query text holds none of them; user B → 404 with no query; bad range → 422; second call within 60 s runs no query; no keys → `{"enabled": false}`; query failure → 503. One live check of the three queries' syntax against the owner's PostHog by hand.
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** `pytest tests/test_analytics.py -q`; pass.
- [ ] **Step 5:** Commit `feat: analytics endpoint`.

### Task 3: Analytics page

**Files:** Replace `frontend/src/pages/Analytics.jsx`; modify `frontend/src/lib/queries.js` (`useAnalytics(agentId, range)`).

- [ ] **Step 1:** Load the `dataviz` skill before the chart.
- [ ] **Step 2:** Page: agent picker (`AgentSelect`, navigates to `/app/analytics/:agentId`), period buttons, tiles, per-day bar chart (SVG, messages and tool calls), tools table; empty, loading, error and not-set-up states; note that new activity can take a minute to appear.
- [ ] **Step 3:** `npm run build`, `npm run lint`; clean.
- [ ] **Step 4:** Commit `feat: Analytics page`.

### Task 4: Verify

- [ ] Full backend suite; restart the backend; a few chats in the owner's browser; open Analytics and check the numbers. Fresh reviewer over the branch; fix Critical/Important; ledger minors.
