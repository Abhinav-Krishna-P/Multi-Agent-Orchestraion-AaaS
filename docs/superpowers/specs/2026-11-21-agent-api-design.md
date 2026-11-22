# Agent API — design

Date: 2026-11-21 · Status: approved by the owner (recipients: option C)

## Why

Today an agent can only be used in the website's "Chat with your agent" page. The owner wants a user
to be able to call one of their agents from their own project — Python, JavaScript or TypeScript —
with a secret API key: send text, get the agent's whole answer back as JSON, and use it however
their project needs. The platform only provides the agent's response.

## Goals

- A secret API key per agent; calling the API with it runs that agent on one message.
- A small Python package and a small TypeScript package (usable from plain JavaScript) so a call is
  one line.
- A new page in the app's sidebar, **API**, holding everything the API needs: keys, the agent's API
  settings, how to call it, and the log of calls.
- Every call is recorded: the text sent, the reply, the tools used, the outcome and the time; calls
  and tool calls also count in Analytics.

## Non-goals

- Memory between calls. Each call is a separate message: the agent sees only that call's text
  (owner's choice A).
- Streaming the reply word by word. A call waits and returns the whole JSON.
- Calling from browser JavaScript. The key is a secret like an LLM key; the API is for servers and
  scripts. No CORS is opened for it.
- Publishing the packages to PyPI / npm. That needs the owner's accounts; the packages are built and
  tested in this repo, and the owner publishes them.
- One key for the whole profile. Keys belong to one agent (owner's choice).

## Anti-goals (failure even if it technically works)

- A key that can be read back after creation, or is stored in a form that would let a database leak
  hand out working keys.
- A leaked key that can burn the owner's LLM tokens without limit.
- An agent whose actions (sending email, creating events…) run through the API without the user
  having been told, at key creation, that they will.
- API calls that slow down or break the website chat.

## Decided by the owner

1. **Actions run without asking.** Through an API key, the agent's actions are approved
   automatically. The create-key dialog says so plainly before the key is made, e.g.: "Calls with
   this key run the agent's actions automatically, without asking: it can send emails, create
   events…" — naming the actions this agent actually has.
2. **The key is a secret and the user's responsibility**, like their Gemini key. It is shown once,
   at creation, with a copy button; afterwards only a hint (`cap_…a1b2`).
3. **The response is the agent's whole answer**, plus what it used — not a one-line summary.
4. **Each call stands alone** (no conversation memory). Calls and tool calls are recorded.
5. **The text of each call is kept** (what was sent and the reply).
6. **One key per agent.**
7. **Approach A**: a separate API route that runs the agent the way automations run it (unattended),
   not the website chat code.
8. **A new page in the UI**, with the settings the API needs.

## Approaches considered

- **A. A separate API route that runs the agent unattended (chosen).** Automations already run an
  agent with nobody there: `build_toolset(..., locked=...)` makes app writes run directly and drops
  the "fill in these details" form, and `automations/run.py::_attempt` plays the graph without
  streaming and collects the reply and the tools used. An API call is the same with the caller's text
  as the message. Small, and it cannot disturb the website chat.
- **B. Push API calls through the website chat.** Each call would open a hidden chat session and
  drive `POST /sessions/{id}/chat`. It reuses message saving, but that code is built for a person —
  streaming, approval cards, details forms, one reply at a time per chat — all of which would have to
  be switched off, and hidden sessions would sit next to real ones. Rejected as fragile.
- **C. A separate API service.** Too much for this; rejected.

## The design

### The call

```
POST /v1/run
Authorization: Bearer cap_<secret>
Content-Type: application/json

{"message": "What is our refund policy for damaged items?"}
```

Success, `200`:

```json
{
  "id": "6f1c…",                     // this call's id, as shown in the call log
  "agent_id": "14eb…",
  "reply": "Damaged items can be returned within 30 days…",
  "sources": [{"document": "policy.pdf", "page": 3, "text": "…"}],
  "tools_used": [{"name": "get_current_weather", "ok": true, "result": {"temp": 28}}],
  "duration_ms": 2140
}
```

- `sources`: knowledge-base passages the reply drew on (empty when none), in the same shape the
  website chat already shows under a reply.
- `tools_used`: each tool the agent called, in order, with whether it worked and its result card
  (the structured result the chat already renders), when there is one.
- `message`: required, non-empty after trimming, at most 8,000 characters.

Errors share one shape, the one the app's API already uses (`core/errors.py`):
`{"detail": {"code": "...", "message": "..."}}`. For `/v1`, FastAPI's own validation error (whose
`detail` is a list) is turned into the same shape with code `invalid_request`, so the packages parse
one shape. *(Builder's call, settled in review.)*

| Status | When |
|---|---|
| 401 `invalid_api_key` | no key, unknown key, or a revoked key (one message for all three) |
| 409 `agent_not_live` | the agent is a draft or stopped |
| 409 `no_llm_key` | the owner has no key saved for the agent's LLM provider |
| 422 `invalid_request` | the message is missing, blank or too long |
| 429 `rate_limited` | over the agent's calls-per-minute limit; `Retry-After` header in seconds |
| 502 `agent_failed` | the model or the run failed or took longer than the run limit; the call is still logged |

### How a call runs

1. Hash the key and look it up; reject if unknown or revoked. Update the key's `last_used_at`.
2. Check the agent is live and the owner has an LLM key for its provider.
3. Rate limit: count the call in Redis under the agent for the current minute; over the limit →
   429. If Redis is down, the call is allowed (the cache's fail-open rule).
4. Run the agent the way automations do: its own model, persona, knowledge base and tools; app
   writes run directly. If the agent's "Actions through the API" setting is off, app writes are left
   out of the toolset. The system prompt gets the unattended note ("nobody is there to answer…"),
   worded for an API caller.
   **Recipients (owner's choice C):** an action's destination arguments — the ones automations
   guard with `DESTINATION_ARG` (to, cc, channel, calendar_id, attendees…) — keep a value the model
   chose only if that value appears in the caller's own message (case-insensitive; for a list, each
   item is checked on its own). Any other destination value is removed before the action runs,
   exactly as automations remove unlocked ones, and the tool's entry in `tools_used` lists it as
   `overridden`. So "send the report to bob@x.com" works, while an address that came from a
   document, an email or a tool result never receives anything. This is a third mode next to chat
   (asks for approval) and automations (locked values): the destination guard is shared, only the
   source of allowed values differs.
5. The run limit is the automations' `RUN_SECONDS` (180 s).
6. The LLM step cache from the Redis work applies (scope `agent:provider:model`); identical text to
   the same agent with the same tools within 24 h reuses the model's step, while tools still run.
7. Save the call to the log, send the Analytics events, return the JSON.

The run code shared with automations is moved into one place both use, rather than copied.

### Keys

- Format `cap_` + 32 random URL-safe bytes from `secrets`.
- Stored only as a SHA-256 hash (unique index) plus the hint (last 4 characters); the full key is in
  the create response and nowhere else. SHA-256 rather than a slow password hash: the key is long and
  random, and every call must check it quickly.
- Each key has a name the user types ("Production server"), created time, last used time, and
  revoked time. Revoking is immediate and can't be undone; the key's calls stay in the log.
- An agent can have several keys (e.g. one per environment), so a key can be replaced without
  downtime: create the new one, switch, revoke the old one. Limit: 10 active keys per agent.
- Deleting an agent deletes its keys and its call log.

### The agent's API settings

Stored on the agent, edited on the API page:

- **Actions through the API** — on by default (owner's decision 1). Off: the agent can still search
  its knowledge base and use read tools, but cannot send, create or change anything in connected
  apps.
- **Calls per minute** — default 60, from 1 to 600. Protects the owner's LLM bill if a key leaks.
  Without Redis the count is kept per process.

**Actions added later** *(builder's call, settled in review)*: when the agent gains a new action
after keys exist (e.g. Gmail is connected next week), existing keys can use it — the owner chose
"granted by default". The API page's settings always list the actions keys can run right now, under
the toggle, so the current list is visible in one place. No per-key acknowledgement is stored.

### Call log

Each call is one row: agent, key (kept if the key is later revoked), the message, the reply, the
tools used (as returned), the sources, the outcome (`ok` / the error code), the duration and the time.
A failed call is logged too, with its error. Rejected calls (401, 429, 422) are not logged as calls —
they never reached the agent.

### Analytics

- A new event `api_call` per logged call: `agent_id`, `success`, `duration_ms`. No message text goes
  to PostHog (its existing rule).
- Tool calls send the existing `tool_called` event with `source="api"`, and the Chat tab's numbers
  leave them out (as they already leave out `source="automation"`).
- The Analytics page gets an **API** tab next to Chat and Automations: calls, success rate, average
  time, tool calls, and calls per day — the same layout and the same 60 s Redis cache as the other
  tabs.

### The API page (new, in the sidebar after Analytics)

```
API                                               [ Tools Tester ▾ ]

 Keys                                              [ + Create key ]
 ┌───────────────────────────────────────────────────────────────┐
 │ Production server   cap_…a1b2   created 21 Nov   used 2 min ago   [Revoke] │
 │ Testing             cap_…9f0c   created 20 Nov   never used       [Revoke] │
 └───────────────────────────────────────────────────────────────┘

 Settings
   Actions through the API   [■ on ]  Calls with a key run actions without asking.
   Calls per minute          [ 60 ]

 Use it
   [ Python | TypeScript | curl ]
   from agentplatform import Agent
   agent = Agent(api_key=os.environ["AGENT_API_KEY"])
   result = agent.run("What is our refund policy?")
   print(result["reply"])

 Recent calls                                         (newest first)
   21 Nov 10:42  ✓ 2.1 s  "What is our refund policy…"  → "Damaged items can…"   [▸]
   21 Nov 10:40  ✗ 0.8 s  "Send the report to…"         agent_failed           [▸]
```

- Agent picker like the Automations and Analytics pages; the URL is `/app/api/:agentId?`.
- **Create key**: a dialog asks for a name and shows the actions notice (decision 1). After creating,
  it shows the full key once with a copy button and "You won't see this key again. Keep it secret,
  like a password."
- **Revoke** asks for confirmation (it can't be undone).
- A draft or stopped agent shows a note that calls are refused until it is live.
- **Recent calls**: newest first, 20 at a time with "Load more"; a row expands to the full message,
  reply, tools used and sources. The page only reads the log; it has no delete.
- **Use it** (owner's request): tabs with ready-to-copy code for **Python, JavaScript, TypeScript,
  Node.js, PHP, Java, Go, C# and cURL**. Python and TypeScript/JavaScript/Node.js show the package
  and, below it, the same call with plain HTTP (`requests` / `fetch`) for those who don't want the
  package; PHP (cURL extension), Java (`java.net.http`), Go (`net/http`), C# (`HttpClient`) and
  cURL use plain HTTP with no extra library. Each snippet reads the key from an environment variable
  (`AGENT_API_KEY`), sends one message, prints `reply`, and handles an error. Under the tabs, a line
  says: "Keep the key on your server. Never put it in browser or mobile-app code."
- The snippets fill in the backend's address and the agent; the key is never put in them.
- The same snippets go in `docs/agent-api.md`.

### Packages

In `sdk/python/` and `sdk/typescript/`, each with a README, tests and a version of 0.1.0.

- **Python**: no dependencies beyond the standard library; `Agent(api_key, base_url=...)`,
  `agent.run(message) -> dict`. Errors raise `AgentError` with `status`, `code`, `message` and, for
  429, `retry_after`. Python 3.9+.
- **TypeScript**: uses the built-in `fetch` (Node 18+, Deno, Bun); ships ES module and type
  definitions; `new Agent({ apiKey, baseUrl })`, `await agent.run(message)` returning the typed
  response; errors throw `AgentError` with the same fields.
- Both read `base_url` from the constructor, defaulting to `http://localhost:8000` for now — there is
  no deployed address yet.
- No retries built in: the caller decides; the error tells them when to retry (429).

### Documentation

`docs/agent-api.md`: creating a key, the call, the response, the errors, the limits, the packages,
and keeping the key secret.

## Constraints

- Backend: FastAPI + async SQLAlchemy + Alembic, as today. New tables and agent columns come in one
  Alembic migration.
- Frontend: React/Vite with the existing UI components (`components/ui/*`), the agent picker
  pattern of the Automations page, and the app's API helpers.
- Tests: pytest as the rest of the backend; the Redis-free test setup (`REDIS_URL=""`) applies.
- Secrets never printed or logged; key values never in logs, analytics, or error messages.

## Left to the builder

- Table and column names, and the shape of the shared unattended-run code.
- The exact wording of the unattended note for API callers.
- Exact UI layout details within the sketch above.
- How sources are collected in the unattended run (the chat runner already collects them).
