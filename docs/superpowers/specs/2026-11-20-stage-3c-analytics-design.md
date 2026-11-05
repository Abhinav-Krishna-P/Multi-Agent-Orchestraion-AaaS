# Stage 3, Part C Design — Analytics

Date: 2026-11-20
Status: waiting for approval

The last part of the MVP: the Analytics page, fed by PostHog. Where this document disagrees with the original spec in `Project data/`, this document wins.

## 1. Intent

Show each user how their agents are used: how many chats and messages, which tools run and how often they fail, how long they take, knowledge-base use, approvals given and refused, and broken app connections, over time.

## 2. Goals

1. The backend sends usage events to PostHog as things happen. Sending never slows a reply or breaks anything if PostHog is down.
2. The Analytics page shows, for one chosen agent and a chosen period (7, 30 or 90 days):
   - totals: chats, messages, tool calls, tool success rate, average tool time, knowledge-base searches, approvals approved / rejected, connection problems;
   - activity over time: messages and tool calls per day;
   - a table of tools: name, type, calls, failures, average time.
3. The page's numbers come from the backend, which asks PostHog itself, filtered to that agent after checking it belongs to the user. The browser never talks to PostHog.

## 3. Non-goals

- Token or cost analytics (the spec defers this).
- Comparing agents, exporting, or custom date ranges.
- Developer tracing: LangSmith stays as it is.

## 4. Anti-goals

- **No user content in PostHog:** no message text, tool arguments, results, document text, email addresses or names. Only IDs, names of tools and apps, counts, outcomes and times.
- A user can only see analytics for their own agents.
- No PostHog key reaches the browser or a log line.
- Tests never send a real event. No pushing.

## 5. Approaches

- **A. Plain HTTP to PostHog's capture and query APIs, through the existing helper (chosen).** Two calls: send an event, run a query. Events go out in the background with a short time limit.
- B. The `posthog` Python package. Rejected: a dependency with its own background thread, for one call the platform can make in a few lines.

Queries use PostHog's query language with placeholders for the agent ID and period, so nothing is pasted into the query text (checked live on 2026-11-20).

## 6. Design

### Events (sent from the backend)

Every event carries `user_id` (also PostHog's person ID), `agent_id` and, where there is one, `session_id`.

| Event | Extra properties | Sent from |
|---|---|---|
| `session_started` | | creating a chat |
| `message_sent` | | saving a user message |
| `tool_called` | `tool_name`, `tool_type` (`builtin`, `api`, `knowledge_base`, `composio`), `app` (Composio only), `success`, `duration_ms` | the runner, when each tool finishes |
| `knowledge_base_searched` | `search_mode`, `results_count` | the runner, for knowledge-base searches |
| `write_action_decision` | `tool_name`, `app`, `decision` (`approved` / `rejected`), `outcome` (`done` / `failed` / none) | deciding an approval |
| `connection_expired` | `app` | when a connection is found broken |
| `document_ingested` | `source_type`, `chunk_count`, `status` (`ready` / `failed`) | the end of document processing |

`duration_ms` is the time from the model asking for the tool to its result (tools asked for together share one timing). The spec's `top_score` for knowledge-base searches is left out: the search result does not carry it today. The details form tool is not counted as a tool.

### Backend

- `app/analytics/posthog.py`: `capture(event, user_id, properties)` schedules the send in the background and returns at once; failures are logged by type and dropped. `query(sql, values)` runs one query with the personal key. With no PostHog key set, `capture` does nothing and the page says analytics are not set up.
- `GET /agents/{id}/analytics?range=7d|30d|90d` (owner only): three queries (totals, per day, per tool), answered together and remembered for 60 seconds.
- Tests replace `capture` with a recorder and check each event's name and properties, and that no event carries content.

### Frontend

- `pages/Analytics.jsx` replaces the placeholder: agent picker (the existing one), period buttons, a row of stat tiles, a bar chart of activity per day (drawn as SVG, no chart library), and the tools table. Empty, loading, error and "not set up" states. A line notes that new activity can take a minute to appear.
- The left menu's Analytics link opens it; the agents list links to each agent's analytics.

## 7. Testing

Backend, test-first: each event is sent with the right properties at the right moment, and never with content; a PostHog outage changes nothing for the user; the analytics endpoint checks ownership, passes the agent and period as placeholders, shapes the three results, and caches. Frontend: build, lint, and a live look after a few chats.

## 8. Left to the builder

Tile order and wording, chart styling, and which tools table columns show on a phone.
