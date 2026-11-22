# Redis Shared Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One shared Redis cache for the backend: outside-service and Composio replies, Analytics, knowledge-base searches and query embeddings, and chat-reply model steps — falling back to today's behaviour when Redis is down or not configured.

**Architecture:** A small `app/core/cache.py` (JSON get/set with expiry) over `redis.asyncio`, with an in-process store when `REDIS_URL` is empty (tests) and fail-open when Redis errors. Each cache site calls it directly. KB results are keyed by a fingerprint of the agent's ready documents read from Postgres; chat model steps are keyed by the full input with ids stripped, scoped by agent + model.

**Tech Stack:** FastAPI, SQLAlchemy async, LangGraph/LangChain, `redis` (redis-py, new), pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-redis-cache-design.md`

## Global Constraints

- One new dependency only: `redis` (official redis-py). No `fakeredis`, `langchain-redis`, `fastapi-cache2`, `redisvl`.
- Every key starts with `cap:`; every value is JSON; every key has an expiry.
- Fail-open: a Redis error or timeout = a miss on read, ignored on write. Socket timeout 0.3 s. After a failure, skip Redis for 30 s; one warning per outage; never log a value or key material.
- With `REDIS_URL` empty: in-process store, per process, exactly as today.
- No secret (API key, token, secret params, headers) and no raw query text in any key; keys built from hashes.
- Expiries: outside services 600 s (default); Composio action and trigger lists 21600 s (6 h); Analytics 60 s; KB search results 3600 s; query embeddings 604800 s (7 days); chat model steps 86400 s (24 h).
- LLM cache is for normal chat replies only (`session.purpose == "chat"`). Automation runs and the describe chat never use it.
- Tests never touch a real Redis unless `TEST_REDIS_URL` is set; `tests/conftest.py` forces `REDIS_URL=""`.
- Backend: `backend/.venv/Scripts/python`; from `backend/` run only the focused test files you touch; never run the full suite, and never two pytest runs at once (check for a running pytest first).
- Git Bash on Windows: use file edit tools, not heredocs. Commit on `redis-cache`, messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push. Never print `backend/.env`.

## Review Focus

1. Redis goes down mid-session → chats, searches and Analytics keep working, with at most one 0.3 s delay per 30 s (Task 1 test).
2. A caller mutates a value it got from the cache → the cached copy is unchanged (in-process store returns copies) (Task 1 test).
3. A document still processing, or one that failed → never changes or leaks into cached search results; once it becomes ready the next search misses (Task 3 test).
4. Gemini returns content as a list of parts → a cached reply round-trips and still shows its text (Task 4 test).
5. A cached step whose tool calls are replayed → fresh tool-call ids each time, never the cached ones (Task 4 test).

---

### Task 1: Cache module, setting, dependency

**Files:**
- Create: `backend/app/core/cache.py`
- Modify: `backend/app/core/config.py` (add `redis_url: str = ""`), `backend/requirements.txt`, `backend/.env.example`, `backend/app/main.py` (lifespan), `backend/tests/conftest.py`
- Test: `backend/tests/test_cache.py`

**Interfaces:**
- Produces (in `app.core.cache`):
  - `def digest(*parts) -> str` — sha256 hex of `json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)`.
  - `async def get_json(key: str) -> Any | None` — `key` without the `cap:` prefix (added inside).
  - `async def set_json(key: str, value: Any, seconds: int) -> None`
  - `def backend_name() -> str` — `"redis"` or `"memory"`.
  - `async def close() -> None` — closes the Redis client if one was made.
  - `def reset() -> None` — empties the in-process store and clears the skip window (tests).
  - Module global `client` (a `redis.asyncio.Redis` or `None`), built lazily from `settings.redis_url` with `socket_timeout=0.3, socket_connect_timeout=0.3, decode_responses=True`; tests may assign a stub to it.
  - `SKIP_SECONDS = 30`, `MEMORY_MAX = 2000` (in-process store cleared when full, like today's caches).

- [ ] **Step 1: Add the dependency.** `backend/.venv/Scripts/python -m pip install redis`, then add `redis>=<installed major.minor>` to `backend/requirements.txt`. Add `REDIS_URL=` with a one-line comment (`# e.g. redis://localhost:6379/0; empty = in-process cache`) to `backend/.env.example`. In `tests/conftest.py` add `os.environ["REDIS_URL"] = ""` next to the other env lines, and an autouse fixture that calls `cache.reset()` before each test.

- [ ] **Step 2: Write the failing tests** in `tests/test_cache.py`:

```python
async def test_round_trip_and_expiry(monkeypatch):
    await cache.set_json("t:a", {"x": [1, 2]}, 10)
    assert await cache.get_json("t:a") == {"x": [1, 2]}
    monkeypatch.setattr(cache.time, "monotonic", lambda: real_now() + 11)
    assert await cache.get_json("t:a") is None

async def test_values_are_copies():
    await cache.set_json("t:b", {"x": 1}, 10)
    (await cache.get_json("t:b"))["x"] = 99
    assert await cache.get_json("t:b") == {"x": 1}

async def test_digest_is_stable_and_order_free():
    assert cache.digest({"b": 1, "a": 2}) == cache.digest({"a": 2, "b": 1})

async def test_redis_errors_are_misses_then_skipped_for_30s(monkeypatch, caplog):
    stub = RaisingRedis()  # get/set raise redis.exceptions.ConnectionError and count calls
    monkeypatch.setattr(cache, "client", stub)
    assert await cache.get_json("t:c") is None
    await cache.set_json("t:c", 1, 10)          # no raise
    assert stub.calls == 1                       # second call skipped: inside the 30 s window
    assert caplog.text.count("Redis") == 1       # one warning per outage
    monkeypatch.setattr(cache.time, "monotonic", lambda: real_now() + 31)
    await cache.get_json("t:c")
    assert stub.calls == 2

async def test_redis_values_get_prefix_and_expiry(monkeypatch):
    stub = RecordingRedis()  # records set(key, value, ex=...) and serves get
    monkeypatch.setattr(cache, "client", stub)
    await cache.set_json("t:d", {"y": 1}, 60)
    assert stub.sets == [("cap:t:d", '{"y": 1}', 60)]
    assert await cache.get_json("t:d") == {"y": 1}

@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="needs a real Redis")
async def test_real_redis_round_trip(monkeypatch): ...  # client from TEST_REDIS_URL, round trip, then delete the key
```

- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_cache.py -v` → FAIL (module missing).

- [ ] **Step 4: Implement `app/core/cache.py`.** The in-process store keeps JSON strings with an expiry (so reads return copies). Catch `redis.exceptions.RedisError` and `OSError`/`asyncio.TimeoutError` as "Redis failed". The warning text names Redis and the error type only.

- [ ] **Step 5: Lifespan.** In `app/main.py` `_lifespan`: log `"Cache: %s"` with `backend_name()` at startup; `await cache.close()` after `yield`.

- [ ] **Step 6: Run** `tests/test_cache.py` → PASS. Run `tests/test_api_tools.py tests/test_analytics_api.py` → still PASS (nothing uses the module yet).

- [ ] **Step 7: Commit** `feat: shared cache module (Redis with in-process fallback)`.

---

### Task 2: Outside services, Composio lists and Analytics on the cache

**Files:**
- Modify: `backend/app/tools/http.py`, `backend/app/integrations/composio.py:63-103`, `backend/app/api/analytics.py:24-26,205-249`
- Test: `backend/tests/test_api_tools.py`, `backend/tests/test_composio_triggers.py`, `backend/tests/test_analytics_api.py`, `backend/tests/test_integration_api.py` (replace `http._cache.clear()` / `analytics._cache.clear()` with nothing — the autouse reset covers it — or `cache.reset()` where a mid-test reset is needed)

**Interfaces:**
- Consumes: `cache.get_json`, `cache.set_json`, `cache.digest`, `cache.reset` (Task 1).
- Produces: `fetch_json(..., cache: bool = True, cache_seconds: int = CACHE_SECONDS)`; `composio.LIST_CACHE_SECONDS = 21600`, passed by `actions()` and `trigger_types()` through `_call(..., cache_seconds=...)`.

- [ ] **Step 1: Failing tests.**
  - `test_api_tools.py::test_secrets_are_not_in_the_cache_key` rewritten to inspect the in-process store's keys (secret values absent) — keep its intent.
  - `test_composio_triggers.py::test_lists_are_kept_six_hours`: spy on `cache.set_json`; call `composio.actions("gmail")` and `composio.trigger_types("gmail")`; assert each `set_json` call had `seconds == 21600`.
  - `test_api_tools.py::test_action_calls_are_never_cached`: two identical `fetch_json(..., cache=False)` calls both reach the transport, and `cache.set_json` is never called.
  - `test_analytics_api.py::test_a_failed_read_is_not_cached`: PostHog stand-in fails once then succeeds; first request 503, second request 200 with numbers.
- [ ] **Step 2: Run** those files → the new tests FAIL.
- [ ] **Step 3: Implement.**
  - `fetch_json`: key `"http:" + digest(service, method, url, params, json)`; drop `_cache`, `CACHE_MAX` and the module-level shortcut comment.
  - `analytics.py`: drop `_cache`/`_remember`; key `f"analytics:{agent.id}:{tab}:{range_}:{tz}"` with `tab` in `{"chat","automations"}`, `CACHE_SECONDS = 60`. Errors raise before `set_json`, so they're never stored.
- [ ] **Step 4: Run** the four test files → PASS.
- [ ] **Step 5: Commit** `feat: outside-service, Composio and Analytics caches use the shared cache`.

---

### Task 3: Knowledge-base search and query-embedding cache

**Files:**
- Modify: `backend/app/rag/retrieve.py:77-193`, `backend/tests/rag_fakes.py` (counters)
- Test: `backend/tests/test_retrieve.py`

**Interfaces:**
- Consumes: Task 1 functions.
- Produces (in `retrieve.py`): `SEARCH_CACHE_SECONDS = 3600`, `EMBED_CACHE_SECONDS = 604800`; `async def _fingerprint(db, agent_id) -> str` = `digest(sorted ready document ids as str)`. `search()` signature unchanged.
- `rag_fakes.py`: `FakeEmbedder.query_calls: list[str]` (appended in `embed_query`), `FakeVectorStore.queries: int` (incremented in `query`).

- [ ] **Step 1: Failing tests** in `test_retrieve.py`, using the existing `kb` fixture and `run_search`:

```python
async def test_repeated_search_is_served_from_cache(kb):
    agent, rag_ = kb
    first = await run_search(agent, rag_, "how many days does standard shipping take", min_similarity=0.05)
    queries = rag_.store.queries
    second = await run_search(agent, rag_, "how many days does standard shipping take", min_similarity=0.05)
    assert second == first and rag_.store.queries == queries and len(rag_.embedder.query_calls) == 1

async def test_a_new_ready_document_makes_the_next_search_miss(client, user_a, kb): ...
    # search "warranty" → []; paste a "Warranty" document; search again → its hit is present

async def test_a_deleted_document_is_never_served_from_cache(client, user_a, kb): ...
    # search finds "Returns"; DELETE that document via the API; same search → no "Returns" hit

async def test_a_document_not_ready_does_not_change_cached_results(client, user_a, kb, db): ...
    # search; insert/mark a document "processing" with matching chunks (as test_documents_that_are_not_ready_are_ignored does);
    # same search → same hits and store.queries unchanged; mark it "ready" → next search misses and includes it

async def test_query_embedding_is_reused_after_a_document_change(client, user_a, kb): ...
    # search; paste a document; same search → embedder.query_calls still length 1, store.queries +1

async def test_search_cache_is_per_agent(client, user_a, kb, rag): ...
    # second agent with different documents, same query → its own results, not the first agent's

async def test_unknown_document_is_not_cached(kb): ...
    # UnknownDocument raised twice for the same filter (second time still raises)
```

- [ ] **Step 2: Run** `tests/test_retrieve.py` → new tests FAIL.
- [ ] **Step 3: Implement.**
  - In `search()`, after `_resolve_name`, compute the key `f"kb:{agent_id}:{await _fingerprint(db, agent_id)}:{digest(query, mode, name.lower() if name else None, page, min_similarity)}"`. On a hit, return `[Hit(**h) for h in cached]`. On a miss, run the existing body, then store `[dataclasses.asdict(h) for h in hits]` (empty lists included).
  - `_embed_query`: key `f"embed:{embedder.model}:{digest(query)}"`, served from the cache, or embedded and stored.
  - `read_document` unchanged.
- [ ] **Step 4: Run** `tests/test_retrieve.py tests/test_documents.py` → PASS.
- [ ] **Step 5: Commit** `feat: knowledge-base searches and query embeddings are cached per agent`.

---

### Task 4: Chat-reply model-step cache

**Files:**
- Modify: `backend/app/agent/graph.py`, `backend/app/agent/runner.py:138-243`, `backend/app/api/chat.py:237-257`
- Test: `backend/tests/test_llm_cache.py` (new; reuse `use_model`, `live_chat`, `send`, `scripted` from `test_chat.py` / `fakes.py`)

**Interfaces:**
- Consumes: Task 1 functions.
- Produces:
  - `build_graph(model, tools=(), *, cache_scope: str | None = None)`; `LLM_CACHE_SECONDS = 86400` in `graph.py`.
  - `def step_key(scope: str, tools, messages) -> str` in `graph.py` = `"llm:" + scope + ":" + digest(tool schemas via langchain_core.utils.function_calling.convert_to_openai_tool, [message identity])`. Message identity = `(message.type, message.content, [(c["name"], c["args"]) for c in tool_calls], message.name)`. Ids and `tool_call_id` are excluded.
  - `run_turn(..., cache_scope: str | None = None)`, passed through to `build_graph`.
  - `chat.py` passes `cache_scope=f"{agent.id}:{provider}:{model_id}"` only when `session.purpose == "chat"`. `automations/run.py` is unchanged: no scope.

- [ ] **Step 1: Failing tests** in `tests/test_llm_cache.py`:

```python
async def test_same_first_message_in_a_new_chat_comes_from_cache(client, user_a, live_chat, use_model):
    model = scripted(["Hello there"]); use_model(model)
    # chat 1: send "hi" → reply "Hello there"; create a second chat on the same agent; send "hi"
    # → 200, reply text "Hello there" saved and streamed as a token event; len(model.received) == 1

async def test_a_follow_up_in_the_same_chat_asks_the_model(...):  # second message → model called again

async def test_another_agent_does_not_share_cached_steps(...):     # same message, other agent → model called

async def test_describe_chat_never_uses_the_cache(...):            # two automation-purpose sessions, same message → model called twice

async def test_graph_without_scope_never_caches():                 # build_graph(model) invoked twice → model.received == 2

async def test_replayed_tool_calls_get_fresh_ids(...):
    # script: [{"tool": "calculator", "args": {...}}], ["Done"] ; chat 1 then chat 2 same message
    # tool_start ids in chat 2 differ from chat 1's; the calculator still ran (tool_end ok); model.received == 2

async def test_list_content_round_trips():
    # an AIMessage with content=[{"type": "text", "text": "Hi"}] stored and read back via the cache → chunk_text == "Hi"

async def test_failed_or_empty_replies_are_not_cached(...):
    # model fails (fail_after=0) in chat 1 → chat 2, same message, scripted success → model called
```

- [ ] **Step 2: Run** `tests/test_llm_cache.py` → FAIL.
- [ ] **Step 3: Implement.**
  - `graph.py` agent node with a scope: `key = step_key(...)`; on a hit, `messages_from_dict` → `AIMessage`, with every `tool_calls[i]["id"]` replaced by `f"cached_{uuid4().hex}"`; on a miss, `ainvoke`, then store `messages_to_dict([reply])` when the reply has text or tool calls. Never store on an exception.
  - `runner.py` fallback: keep `streamed_step = False`; set it True when an agent-node `AIMessageChunk` gives text. On each agent-node update: if not `streamed_step` and `chunk_text(messages[-1])` is non-empty, append it to `parts` and `yield sse("token", ...)`. Then reset `streamed_step = False`.
- [ ] **Step 4: Run** `tests/test_llm_cache.py tests/test_chat.py tests/test_automation_run.py tests/test_automation_describe.py` → PASS.
- [ ] **Step 5: Commit** `feat: chat replies reuse a model step whose whole input was seen before`.

---

### Task 5: Docs, owner's .env, live check (controller)

- [ ] **Step 1:** Controller appends `REDIS_URL=redis://localhost:6379/0` to `backend/.env` with one append command, without reading or printing the file.
- [ ] **Step 2:** Add a short "Cache (Redis)" section to `docs/automations-local-setup.md` or the backend README: what is cached, the expiries, how to turn it off (empty `REDIS_URL`), the privacy note (cached chat text and excerpts; deployment needs a password and `rediss://`), and `redis-cli INFO stats` / `redis-cli --scan --pattern 'cap:*'` to look. Commit `docs: Redis cache setup`.
- [ ] **Step 3:** Full backend suite once (controller), then — only with the owner's go-ahead to start the servers — check live in Chrome:
  - a KB question asked twice in new chats;
  - the same first chat message in two new chats;
  - Analytics opened twice;
  - `keyspace_hits` rising in `redis-cli INFO stats`, and the startup log line `Cache: redis`.
