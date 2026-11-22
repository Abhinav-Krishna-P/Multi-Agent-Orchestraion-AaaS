# Redis shared cache — design

Branch `redis-cache` (off `automations`, which is not merged yet). Owner chose approach A.

## Why

The owner wants the platform cheaper and faster: fewer repeated knowledge-base searches, fewer
paid LLM calls, faster Analytics, through one shared Redis cache — **without** ever showing a
stale or wrong answer or making the experience worse.

## Goals

1. One small cache module on Redis that every cache in the backend uses.
2. Knowledge-base searches: a repeated search on the same agent skips the embedding call, the
   Chroma query and the BM25 pass. Never served after that agent's documents change.
3. LLM (chat replies only): a model step whose *entire* input was seen before (same agent, same
   model, same tools, same full conversation) is answered from the cache instead of Gemini.
4. Analytics: results cached in Redis; on a miss, read from PostHog (the source of the numbers —
   not our database) as today.
5. The three existing per-process caches move to Redis, so they are shared and survive restarts:
   outside-service replies (`tools/http.py`), Composio action/trigger lists (they go through the
   same function), Analytics (`api/analytics.py`).

## Non-goals (looked at, skipped on purpose)

- **"Similar question" (semantic) caching** of LLM answers or searches: it hands one question's
  answer to a different question. Exact matches only.
- **Summarizer:** each chat's summary input is unique, so a cache would never hit.
- **Composio connection status:** it changes the moment the user finishes OAuth; caching it would
  show "pending" after a successful sign-in.
- **Sign-in check:** Supabase's keys are already cached in-process for an hour (`core/security.py`).
- **Scheduler lock:** the scheduler already claims each automation with a conditional database
  UPDATE, so two processes cannot run the same one.
- **Rate limiting, session/message lists:** not asked for; database reads there are fast.
- Serving old Analytics when PostHog is down (a "stale" view). Possible later.

## Anti-goals

- A cached reply that is wrong for *this* moment (an old exchange rate, an answer that ignores the
  chat's earlier messages, results from a deleted document).
- One user's or agent's cached data reaching another.
- The app slowing down or failing because Redis is slow, down or missing.
- A secret (API key, token) in a cache key or value.

## Approaches considered

- **A. Our own small cache module on `redis` (chosen).** One dependency, every key and expiry
  explicit and testable, scoping and clearing done the way this app needs.
- B. Ready-made libraries (`langchain-redis`, `fastapi-cache2`, `redisvl`): 3–4 new packages; keys
  not scoped per user/agent; clearing one agent's search results is awkward; `redisvl` mostly adds
  semantic caching, which is a non-goal.
- C. HTTP response cache middleware: least code, but cannot cache inside a chat (searches, model
  steps), where the cost is, and risks serving a page after a change.

## Design

### Settings and dependency

- New dependency: `redis` (redis-py, async client built in), added to `backend/requirements.txt`.
- `Settings.redis_url: str = ""`; the owner's `.env` gets `REDIS_URL=redis://localhost:6379/0`
  (local Redis, no password). `.env.example` documents it.

### `app/core/cache.py`

- `async get_json(key) -> Any | None`, `async set_json(key, value, seconds)`,
  `async bump(key) -> int` (atomic counter, used for "version" keys), and a test reset helper.
- Every key is prefixed `cap:`; values are JSON.
- **Two backends, one interface:** Redis when `redis_url` is set; otherwise an in-process dict with
  expiry and a size cap (today's behaviour). Tests run on the in-process backend.
- **Fail-open:** any Redis error or timeout counts as a miss on read and is ignored on write. The
  socket timeout is short (about 0.3 s). After a failure, Redis is skipped for 30 s so a down Redis
  doesn't add the timeout to every call; one warning is logged per outage, never the value.
- Every key gets an expiry; nothing is stored forever.
- With no `redis_url`, each process has its own cache, exactly as today; startup logs one line
  saying which backend is in use (builder-check call).

### Outside services and Composio (`tools/http.py`)

- `fetch_json` reads and writes through `cache` instead of its dict. Key stays as today
  (service, method, URL, params, body; secret params and headers are never in the key), hashed.
- New `cache_seconds` argument (default 600, today's value). Composio's action and trigger lists
  use 6 hours: they rarely change, and a cold list once took 8.4 s and dropped every app's tools.
- `cache=False` calls (anything that does something) are unchanged: never cached.

### Analytics (`api/analytics.py`)

- Both endpoints read and write through `cache`, 60 s as today, key
  `analytics:{agent_id}:{tab}:{range}:{tz}`. On a miss, PostHog is asked; errors are not cached.
- The automations tab keeps reading automation names and status fresh from the database on a miss
  (as today). Within the 60 s a turned-off or deleted automation can show its old status for at
  most that long — same as today, so no invalidation (builder-check call).

### Knowledge base (`rag/retrieve.py`, `rag/ingest.py`, `api/documents.py`)

- **Search results:** `search()` checks
  `kb:{agent_id}:{fingerprint}:{sha256(query, mode, document_name lowercased, page, min_similarity)}`
  before the embedding, Chroma and BM25 work; stores the hits (list of `Hit` as JSON) for 1 hour.
  An empty result is cached too (it's a correct answer until the documents change).
  `UnknownDocument` is not cached.
- **Fingerprint from the database, not a Redis counter (builder-check call):** a hash of the
  sorted ids of the agent's *ready* documents, read with one small query on every search. Documents
  can only be uploaded or deleted — there is no rename and no re-ingest (`api/documents.py` has
  POST, GET, DELETE only), and a ready document's chunks never change — so the set of ready ids
  fully decides what a search can return. Any upload finishing, delete or failure changes the set,
  so the next search misses. No invalidation code anywhere, and a Redis outage can't leave a stale
  version behind. Old entries expire on their own.
- **Query embeddings:** `embed:{model}:{sha256(text)}` → vector, 7 days. Shared across agents on
  purpose: the key is the exact text, the value is only a vector, so it reveals nothing to anyone
  who doesn't already have the text. It saves the embedding call after a document change.
- `read_document` is not cached (no paid call; plain database read).
- The `knowledge_base_searched` analytics event still fires on a cache hit (it is recorded where
  the tool runs, not inside `search()`).

### LLM steps (`agent/graph.py`)

- `build_graph(model, tools, *, cache_scope: str | None = None)`. With a scope, the agent node:
  1. builds the key `llm:{scope}:{sha256(model provider+name+settings, tool schemas, all input messages)}`;
  2. on a hit, returns the cached `AIMessage` (LangChain's own message serialization);
  3. on a miss, calls the model and stores the reply for 24 hours.
- Scope is the agent id. **Set for chat replies only (owner's choice, option A).** Automation runs
  and the "describe your automation" chat never pass a scope, so they always ask Gemini: an
  automation sends the same input every run, and a cache would repeat its content (the same "fun
  fact" all day). Savings are modest — mainly a new chat opening with the same message to the same
  agent — and Gemini's own automatic discount on repeated prompt beginnings needs no code from us.
- Why this is safe: tools still run live. "USD to INR now" gives the same first step (call the
  currency tool), the tool returns today's rate, and the next step's input now differs, so it goes
  to Gemini. A follow-up in a chat changes the conversation, so it misses too.
- Not cached: replies that failed, and empty replies.
- Chosen over LangChain's global `set_llm_cache` hook (mentioned earlier): the node wrapper scopes
  keys per agent explicitly and is one place to test.
- **Showing a cached reply (builder-check call):** the runner only shows text from streamed
  `AIMessageChunk`s, so a cached full `AIMessage` would be dropped. The runner gets a fallback: if a
  model step produced no streamed text, it shows the step's final text from the `updates` stream.
  The cached reply appears at once instead of word by word. Test: a cache hit's text is saved and
  sent to the browser.
- **Tool-call ids (builder-check call):** on a hit, every tool call in the cached reply gets a fresh
  id, so ids are never reused across chats (tool activity, approvals and analytics key on them).
- The user's API key is never part of the key or value.

## Privacy

Cached values include chat text and document excerpts, in the local Redis without a password.
Fine for local testing; for deployment Redis needs a password and TLS (`rediss://`). Keys hold no
secrets and no raw query text (hashed).

## Verification

- Unit tests for the cache module (hit, miss, expiry, Redis-down fallback with a stub that raises).
- Tests per spot: second identical call does not reach the service / Gemini / Chroma; a document
  change makes the next search miss; different agents never share LLM or search entries; a
  `cache=False` call is never cached.
- One optional test against the real Redis, skipped unless `REDIS_URL` is set.
- Live in Chrome with the owner's Redis: ask the same knowledge-base question twice in new chats,
  start two new chats with the same first message, open Analytics twice; check `redis-cli INFO stats`
  (`keyspace_hits`) and the backend log.

## Left to the builder

Exact function names inside the module, the in-process size cap, how the hash input is serialized
(must be stable: sorted keys), test fixture shape.
