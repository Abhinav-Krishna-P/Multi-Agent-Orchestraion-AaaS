# Stage 1 (Sign-in, Agents, Chat) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person signs in with Google, saves their own Gemini or OpenAI key, creates and deploys an agent, and chats with it with streaming replies, all on the local machine.

**Architecture:** A FastAPI backend (REST + server-sent events) with async SQLAlchemy on local PostgreSQL, a one-node LangGraph agent that later stages extend with tools, and a Vite + React single-page app using shadcn/ui. Supabase is used only to sign in with Google; the backend verifies its token and owns all data. The `messages` table is the source of truth for chat history; no LangGraph checkpointer in this stage.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, LangGraph, LangChain (`init_chat_model`), PyJWT, cryptography (Fernet), pytest. Node.js 26, Vite, React (JavaScript), Tailwind, shadcn/ui, react-router-dom, @tanstack/react-query, @supabase/supabase-js, @microsoft/fetch-event-source, react-markdown, react-hook-form, zod, sonner.

**Spec:** `docs/superpowers/specs/2026-11-16-stage-1-design.md` (the design). It defers to `Project data/custom-agent-platform-project- complete architecture.md` (the spec) and `Project data/custom-agent-platform-design.md` (the frontend doc). Executors read all three.

## Global Constraints

- Python is run as `py -3.13`; the project uses only `backend/.venv`. Never touch the machine's Python 3.10.
- Backend on `http://localhost:8000`, frontend on `http://localhost:5173`.
- No secret is committed, logged, returned by the API, or sent to tracing. Secrets live only in `backend/.env` and `frontend/.env`, both git-ignored. The Postgres password is written only into `backend/.env`.
- Never `git push`. Commits are local. Every commit message ends with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- Every database query is filtered by the user ID taken from the verified token. Another user's agent, chat, or key returns HTTP 404.
- Error responses use the body `{"detail": {"code": "<snake_case>", "message": "<sentence a user can read>"}}`. No raw exception text or stack traces reach the client.
- UI copy follows frontend doc §9.2: sentence case; buttons say what happens; user words ("apps", "documents", "chat"), not system words.
- Every screen handles loading, empty, error, and normal states (frontend doc §9.1).
- Use shadcn/ui components as they are; no custom design-system components. Light mode only, system font.
- The agent graph, migrations, and wizard must accept tools, documents, and apps in later stages without a rewrite.
- **Stop points for the project owner:** (1) creating the databases — approved on 2026-11-16 when the owner supplied the Postgres password; (2) before the first real sign-in, the owner fills in the `.env` files; (3) the final walkthrough.

## Review Focus

Conditions the design implies but does not spell out. Each has a test in the task that owns the code.

1. **Empty or oversized message.** A blank or whitespace-only message, or one over 20,000 characters, is refused with 422 and nothing is saved. (Task 7)
2. **The model fails partway through a reply.** The stream sends `error` then `done`, the half reply is not saved, the user's message stays, and Retry works. (Task 7)
3. **Two sends on one chat at once** (double click, two tabs). The second gets 409 `reply_in_progress` instead of interleaving messages. (Task 7)
4. **Expired, malformed, or wrongly signed token.** Every endpoint returns 401; the frontend signs the user out with "Your session expired. Sign in again." (Tasks 3 and 9)
5. **The agent changes under an open chat.** Stopped, deleted, or switched to a provider with no saved key: the next message gets a clear 409 or 404, and deleting an agent removes its chats and messages. (Tasks 5 and 7)

---

## File Structure

```
.gitignore
backend/
  requirements.txt  requirements-dev.txt  .env.example  alembic.ini  pytest.ini
  alembic/env.py  alembic/versions/0001_stage1_tables.py
  app/
    main.py              # create_app(): CORS, routers, error handlers
    core/config.py       # Settings, get_settings()
    core/errors.py       # ApiError and its handler
    core/security.py     # verify_token()
    core/encryption.py   # encrypt_key(), decrypt_key(), key_hint()
    core/llm_catalog.py  # fixed provider and model list
    db/base.py           # engine, session factory, get_db()
    db/models.py         # User, LlmKey, Agent, ChatSession, Message
    api/deps.py          # get_current_user, get_owned_agent, get_owned_session
    api/schemas.py       # request and response models
    api/me.py  personas.py  llm_keys.py  agents.py  sessions.py  chat.py
    agent/personas.py    # the twelve personas
    agent/llm.py         # build_chat_model(), validate_key()
    agent/context.py     # build_messages()
    agent/graph.py       # build_graph()
    agent/runner.py      # run_turn(): streams one reply as SSE
    agent/summarizer.py  # maybe_update_summary()
  tests/conftest.py  test_health.py  test_auth.py  test_llm_keys.py  test_agents.py
        test_sessions.py  test_context.py  test_chat.py  test_summarizer.py
frontend/
  .env.example  index.html  vite.config.js  jsconfig.json  components.json
  src/
    main.jsx  App.jsx  index.css
    lib/supabase.js  api.js  sse.js  auth.jsx  queryClient.js
    layouts/AppShell.jsx
    pages/Landing.jsx  AgentsList.jsx  Chat.jsx  Analytics.jsx
    pages/AgentWizard/index.jsx  Basics.jsx  Behavior.jsx  Model.jsx  Deploy.jsx
    components/ApiKeysDialog.jsx  AgentSelect.jsx  StatusBadge.jsx
    components/chat/MessageList.jsx  Message.jsx  Composer.jsx  SessionList.jsx
    components/ui/        # generated by shadcn
```

## API contract (shared by backend and frontend tasks)

| Shape | Fields |
|---|---|
| `User` | `id, email, name, avatar_url` |
| `Persona` | `key, name, description, prompt` |
| `ModelCatalog` | `{providers: [{key, name, models: [{id, name}]}]}` with provider keys `gemini`, `openai` |
| `LlmKey` | `provider, key_hint, updated_at` |
| `Agent` | `id, name, description, persona_key, custom_prompt, system_prompt, llm_provider, llm_model, status, created_at, updated_at`; `status` is `draft`, `live`, or `stopped`; `llm_provider` and `llm_model` may be null |
| `Session` | `id, agent_id, title, summary, created_at, last_message_at` |
| `SessionDetail` | `Session` plus `agent: {id, name, status, llm_provider, llm_model}` |
| `Message` | `id, role, content, created_at`; `role` is `user` or `assistant` |

Chat request body: `{"message": "<text>"}` or `{"retry": true}`. Stream events: `token` with `{"text": "..."}`, `error` with `{"code": "model_error", "message": "..."}`, `done` with `{"message_id": "<uuid or null>"}`. `done` is always the last event.

Error codes: `not_found` (404), `unauthorized` (401), `invalid_api_key` (422), `agent_incomplete`, `agent_not_live`, `llm_not_configured`, `missing_api_key`, `reply_in_progress`, `nothing_to_retry` (all 409).

---

### Task 1: Repository, backend skeleton, databases, test harness

**Files:**
- Create: `.gitignore`, `backend/requirements.txt`, `backend/requirements-dev.txt`, `backend/.env.example`, `backend/.env` (not committed), `backend/pytest.ini`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/errors.py`, `backend/app/db/base.py`, `backend/tests/conftest.py`, `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `get_settings() -> Settings` with fields `database_url, test_database_url, supabase_url, supabase_jwt_secret (optional), fernet_master_key, platform_gemini_api_key (optional), summary_model, frontend_origin` (default `http://localhost:5173`), read from `backend/.env`.
  - `create_app() -> FastAPI`; `GET /health` returns `{"status": "ok"}`.
  - `ApiError(status: int, code: str, message: str)`, rendered in the error body format from Global Constraints. FastAPI's own 404/422 keep their default bodies.
  - `get_db() -> AsyncIterator[AsyncSession]` and `session_factory` (an `async_sessionmaker`) in `app/db/base.py`.
  - Test fixtures in `conftest.py`: `client` (httpx `AsyncClient` on the app, database overridden to the test database), `db` (an `AsyncSession` on the test database), `headers_for(sub: str = <fixed uuid>, email: str = "a@example.com", name: str = "User A") -> dict` (a Bearer header with an HS256 token signed with the test secret, audience `authenticated`), `user_a` and `user_b` (two such header dicts with different `sub`).

- [ ] **Step 1: Initialise the repository.** `git init -b main` in the project root. `.gitignore` excludes `.env`, `.env.*` except `.env.example`, `.venv/`, `__pycache__/`, `node_modules/`, `dist/`, `.pytest_cache/`. Commit the existing `Project data/` and `docs/` folders.
- [ ] **Step 2: Create the virtual environment and install.** `py -3.13 -m venv backend/.venv`. `requirements.txt`: `fastapi>=0.163`, `uvicorn[standard]`, `sqlalchemy[asyncio]>=2.1`, `asyncpg`, `alembic`, `pydantic-settings`, `pyjwt[crypto]`, `cryptography`, `httpx`, `langgraph>=1.2`, `langchain>=1.5`, `langchain-google-genai>=4.5`, `langchain-openai>=1.8`. `requirements-dev.txt`: `-r requirements.txt`, `pytest`, `pytest-asyncio`. Install both with the venv's pip.
- [ ] **Step 3: Create the databases (stop point 1, approved).** With `psql -U postgres`, create `agent_platform` and `agent_platform_test`. In `agent_platform`, run `CREATE EXTENSION IF NOT EXISTS vector;` and confirm `SELECT extversion FROM pg_extension WHERE extname='vector';` returns `0.8.7`. This proves the pgvector install; nothing in stage 1 uses it.
- [ ] **Step 4: Write `.env.example` and `.env`.** `.env.example` lists every variable with a comment and no values: `DATABASE_URL`, `TEST_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_JWT_SECRET` (optional), `FERNET_MASTER_KEY`, `PLATFORM_GEMINI_API_KEY`, `SUMMARY_MODEL`, `FRONTEND_ORIGIN`, and the optional `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`. In `.env`, fill `DATABASE_URL` and `TEST_DATABASE_URL` (`postgresql+asyncpg://postgres:<password>@localhost:5432/<db>`) and a freshly generated `FERNET_MASTER_KEY`; leave the Supabase and Gemini values blank for the owner.
- [ ] **Step 5: Write the failing test** in `tests/test_health.py`:

```python
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}

async def test_api_error_body(client):
    r = await client.get("/__test_error")   # route added only in the test app fixture, raises ApiError(409, "agent_not_live", "x")
    assert r.status_code == 409
    assert r.json() == {"detail": {"code": "agent_not_live", "message": "x"}}
```

- [ ] **Step 6: Run** `backend/.venv/Scripts/python -m pytest backend/tests/test_health.py -v`. Expected: FAIL (no app).
- [ ] **Step 7: Implement** `config.py`, `errors.py`, `db/base.py`, `main.py`, `conftest.py`, and Alembic. Run `alembic init -t async alembic` inside `backend/` and point `env.py` at `get_settings().database_url` and the models' metadata. `pytest.ini` sets `asyncio_mode = auto`. In `conftest.py`: a session-scoped fixture runs `alembic upgrade head` against `TEST_DATABASE_URL`; an autouse fixture truncates all tables after each test; the test engine uses `NullPool`; test settings set `supabase_jwt_secret="test-secret"`. CORS allows only `frontend_origin`.
- [ ] **Step 8: Run the tests.** Expected: PASS.
- [ ] **Step 9: Commit** `chore: backend skeleton, databases, and test harness`.

### Task 2: Tables and migration

**Files:**
- Create: `backend/app/db/models.py`, `backend/alembic/versions/0001_stage1_tables.py`
- Test: `backend/tests/test_health.py` (add one test)

**Interfaces:**
- Produces: ORM classes `User`, `LlmKey`, `Agent`, `ChatSession` (table `sessions`), `Message`, with the columns of spec §14. Differences from the spec: `Agent.status` has a check constraint for `draft|live|stopped` and defaults to `draft`; `Agent.llm_provider` and `Agent.llm_model` are nullable; `Agent.system_prompt` defaults to `''`; `Agent.kb_enabled` defaults to false and `Agent.search_mode` to `hybrid` (unused until stage 2). All IDs are UUIDs generated in Python except `User.id`, which is the Supabase user ID. Foreign keys from `agents`, `llm_keys`, `sessions` to `users`, and from `sessions` to `agents` and `messages` to `sessions`, all use `ON DELETE CASCADE`. `llm_keys` has `unique(user_id, provider)`. Indexes on `agents.user_id`, `sessions(agent_id, last_message_at)`, `messages(session_id, created_at)`.

- [ ] **Step 1: Write the failing test:**

```python
async def test_stage1_tables_exist(db):
    rows = await db.execute(text("select tablename from pg_tables where schemaname='public'"))
    assert {"users", "llm_keys", "agents", "sessions", "messages"} <= {r[0] for r in rows}
```

- [ ] **Step 2: Run it.** Expected: FAIL (tables missing).
- [ ] **Step 3: Implement the models**, then generate the migration with `alembic revision --autogenerate -m "stage1 tables"`, rename it to `0001_stage1_tables.py`, and read it to confirm the constraints above are present.
- [ ] **Step 4: Run** `alembic upgrade head` against `agent_platform`, then the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: stage 1 database tables`.

### Task 3: Sign-in check and current user

**Files:**
- Create: `backend/app/core/security.py`, `backend/app/api/deps.py`, `backend/app/api/schemas.py`, `backend/app/api/me.py`
- Modify: `backend/app/main.py` (add router)
- Test: `backend/tests/test_auth.py`

**Interfaces:**
- Produces:
  - `verify_token(token: str) -> Claims` where `Claims` has `sub: UUID, email: str, name: str | None, avatar_url: str | None`. Uses HS256 with `supabase_jwt_secret` when it is set; otherwise fetches public keys from `{supabase_url}/auth/v1/.well-known/jwks.json` with `jwt.PyJWKClient` and accepts `ES256` and `RS256`. Audience must be `authenticated`. Name and avatar come from the token's `user_metadata` (`full_name` or `name`, `avatar_url` or `picture`). Any failure raises `ApiError(401, "unauthorized", "Your session expired. Sign in again.")`.
  - `get_current_user(...) -> User` dependency: verifies the Bearer token and returns the `User` row, creating it if it does not exist.
  - `GET /me -> User`: also updates `email`, `name`, `avatar_url`, and `last_login_at`.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_me_creates_user(client, user_a, db):
    r = await client.get("/me", headers=user_a)
    assert r.status_code == 200 and r.json()["email"] == "a@example.com"
    assert (await db.scalar(select(func.count()).select_from(User))) == 1

async def test_me_twice_keeps_one_row(client, user_a, db): ...   # count stays 1

@pytest.mark.parametrize("header", [
    {},                                             # no header
    {"Authorization": "Bearer not-a-token"},        # malformed
    "expired", "wrong_secret", "wrong_audience",    # built with headers_for variants
])
async def test_bad_tokens_get_401(client, header): 
    # r.status_code == 401 and r.json()["detail"]["code"] == "unauthorized"
```

- [ ] **Step 2: Run** `pytest backend/tests/test_auth.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `verify_token`, `get_current_user`, the `User` schema, and `GET /me`.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: Supabase token verification and current user`.

### Task 4: LLM keys and the model list

**Files:**
- Create: `backend/app/core/encryption.py`, `backend/app/core/llm_catalog.py`, `backend/app/agent/llm.py`, `backend/app/api/llm_keys.py`
- Modify: `backend/app/api/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_llm_keys.py`

**Interfaces:**
- Produces:
  - `encrypt_key(plain: str) -> str`, `decrypt_key(token: str) -> str` (Fernet with `fernet_master_key`), `key_hint(plain: str) -> str` (the last four characters).
  - `CATALOG: dict` in the `ModelCatalog` shape, and `is_valid_model(provider: str, model: str) -> bool`.
  - `async validate_key(provider: str, api_key: str) -> bool`: one read-only request with a 10-second timeout — Gemini `GET https://generativelanguage.googleapis.com/v1beta/models` with header `x-goog-api-key`; OpenAI `GET https://api.openai.com/v1/models` with a Bearer header. True only on HTTP 200.
  - `get_key_validator()` dependency returning `validate_key`, so tests can override it.
  - `async get_user_api_key(db, user_id, provider) -> str | None` (decrypted) in `app/agent/llm.py`.
  - Endpoints `GET /llm-models -> ModelCatalog`, `GET /llm-keys -> list[LlmKey]`, `PUT /llm-keys/{provider}` (body `{"api_key": str}`, returns `LlmKey`), `DELETE /llm-keys/{provider}` (204). An unknown provider returns 404.

- [ ] **Step 1: Pick the model list.** Look up the providers' current model pages (ai.google.dev and platform.openai.com/docs/models). For each provider choose three current, generally available chat models: the cheapest fast one, the balanced one, and the most capable one. Put their exact IDs and display names in `CATALOG`. Set `SUMMARY_MODEL` in `.env.example` to the cheapest Gemini one.
- [ ] **Step 2: Write the failing tests:**

```python
def test_encrypt_round_trip():
    t = encrypt_key("sk-abc1234"); assert t != "sk-abc1234" and decrypt_key(t) == "sk-abc1234"
def test_key_hint(): assert key_hint("sk-abc1234") == "1234"

async def test_save_key_returns_hint_only(client, user_a, valid_keys):
    r = await client.put("/llm-keys/gemini", json={"api_key": "AIza-secret-9xyz"}, headers=user_a)
    assert r.status_code == 200 and r.json()["key_hint"] == "9xyz"
    assert "AIza-secret-9xyz" not in r.text
    assert "AIza-secret-9xyz" not in (await client.get("/llm-keys", headers=user_a)).text

async def test_key_is_encrypted_in_database(client, user_a, valid_keys, db): ...  # stored value != plain
async def test_invalid_key_rejected(client, user_a, invalid_keys): ...  # 422, code invalid_api_key, nothing stored
async def test_replace_key_keeps_one_row(...): ...
async def test_delete_key(...): ...                       # 204, then list is empty
async def test_keys_are_per_user(client, user_a, user_b, valid_keys): ...  # B sees none of A's
async def test_unknown_provider_404(...): ...
async def test_model_catalog(client, user_a): ...        # both providers, each with >= 1 model
```

`valid_keys` and `invalid_keys` are fixtures in this file that override `get_key_validator` to return True or False.

- [ ] **Step 3: Run the tests.** Expected: FAIL.
- [ ] **Step 4: Implement.** The API key is never written to a log line or an error message.
- [ ] **Step 5: Run the tests.** Expected: PASS.
- [ ] **Step 6: Commit** `feat: encrypted LLM keys and model list`.

### Task 5: Personas and agents

**Files:**
- Create: `backend/app/agent/personas.py`, `backend/app/api/personas.py`, `backend/app/api/agents.py`
- Modify: `backend/app/api/deps.py`, `backend/app/api/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_agents.py`

**Interfaces:**
- Consumes: `get_current_user`, `is_valid_model`.
- Produces:
  - `PERSONAS: list[Persona]` with keys `customer_care, developer, tester, friend, store_owner, teacher, doctor, career_guidance, writer, research_assistant, sales_assistant, personal_coach`, and `get_persona(key) -> Persona | None`. Each prompt is 80–150 words covering role, tone, and response style. The `doctor` prompt says the agent gives general health information, is not a substitute for a doctor, and recommends seeing one for diagnosis, treatment, or emergencies.
  - `get_owned_agent(agent_id: UUID, ...) -> Agent` dependency: 404 `not_found` unless the agent belongs to the current user.
  - `GET /personas`, `GET /agents` (newest first), `POST /agents` (body `{name, description?}`, returns a `draft`), `GET|PATCH|DELETE /agents/{agent_id}`, `POST /agents/{agent_id}/deploy`, `POST /agents/{agent_id}/stop`.
- Rules:
  - `name` 1–100 characters after trimming; `description` up to 500; `system_prompt` up to 20,000.
  - PATCH with `persona_key` and no `system_prompt` sets `system_prompt` to that persona's prompt. PATCH with `system_prompt` stores it as given. When `persona_key` is null, `custom_prompt` mirrors `system_prompt`. An unknown `persona_key` is 422.
  - `llm_provider` and `llm_model` must be sent together and pass `is_valid_model`, else 422.
  - Deploy: `draft` or `stopped` → `live`; requires a non-empty `system_prompt`, else 409 `agent_incomplete`. A missing model or key does not block it.
  - Stop: `live` → `stopped`; from any other status, 409 `agent_not_live`.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_create_agent_is_draft(client, user_a): ...     # 201, status == "draft", system_prompt == ""
async def test_blank_name_rejected(...): ...                   # "   " -> 422
async def test_name_over_100_rejected(...): ...
async def test_choose_persona_fills_prompt(client, user_a):
    # PATCH {"persona_key": "teacher"} -> system_prompt == get_persona("teacher").prompt
async def test_edit_prompt_keeps_persona(...): ...             # PATCH persona + system_prompt -> stored text is the edited one
async def test_custom_prompt_mirrors(...): ...                 # persona_key null + system_prompt "X" -> custom_prompt == "X"
async def test_unknown_persona_422(...): ...
async def test_model_must_match_provider(...): ...             # openai + a gemini model id -> 422
async def test_deploy_needs_prompt(...): ...                   # empty prompt -> 409 agent_incomplete
async def test_deploy_without_model_or_key_allowed(...): ...   # -> live
async def test_lifecycle_live_stopped_live(...): ...           # deploy, stop, deploy
async def test_stop_draft_409(...): ...                        # agent_not_live
async def test_other_user_gets_404(client, user_a, user_b):   # GET, PATCH, DELETE, deploy, stop as B on A's agent -> all 404
async def test_list_only_own_agents(...): ...
async def test_personas_has_twelve_with_prompts(client, user_a): ...
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: personas and agent lifecycle`.

### Task 6: Chats and message history

**Files:**
- Create: `backend/app/api/sessions.py`
- Modify: `backend/app/api/deps.py`, `backend/app/api/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_sessions.py`

**Interfaces:**
- Consumes: `get_owned_agent`.
- Produces:
  - `get_owned_session(session_id: UUID, ...) -> ChatSession` dependency: 404 unless the chat belongs to the current user. Loads its agent.
  - `GET /agents/{agent_id}/sessions -> list[Session]` ordered by `last_message_at` descending.
  - `POST /agents/{agent_id}/sessions -> Session` (201); title starts as `"New chat"`; 409 `agent_not_live` unless the agent is `live`.
  - `GET /sessions/{session_id} -> SessionDetail`, `GET /sessions/{session_id}/messages -> list[Message]` oldest first, `DELETE /sessions/{session_id}` (204).

- [ ] **Step 1: Write the failing tests:**

```python
async def test_create_session_on_live_agent(...): ...      # 201, title "New chat"
async def test_create_session_on_draft_409(...): ...       # agent_not_live
async def test_sessions_newest_activity_first(...): ...
async def test_session_detail_includes_agent_status(...): ...
async def test_messages_oldest_first(client, user_a, db): ...  # rows inserted directly
async def test_delete_session_removes_messages(...): ...
async def test_delete_agent_removes_sessions_and_messages(client, user_a, db): ...   # Review Focus 5
async def test_other_user_gets_404(...): ...               # list, create, detail, messages, delete
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: chats and message history`.

### Task 7: Chat with streaming replies

**Files:**
- Create: `backend/app/agent/context.py`, `backend/app/agent/graph.py`, `backend/app/agent/runner.py`, `backend/app/api/chat.py`
- Modify: `backend/app/agent/llm.py`, `backend/app/api/schemas.py`, `backend/app/main.py`
- Test: `backend/tests/test_context.py`, `backend/tests/test_chat.py`

**Interfaces:**
- Consumes: `get_owned_session`, `get_user_api_key`, `session_factory`.
- Produces:
  - `build_chat_model(provider: str, model: str, api_key: str) -> BaseChatModel` in `app/agent/llm.py`, using `init_chat_model` with `model_provider` `google_genai` for `gemini` and `openai` for `openai`, streaming on, a 60-second timeout. The key is passed as the `api_key` argument only; it is never put in an environment variable, a message, or a log line, so it stays out of LangSmith traces. `get_model_factory()` dependency returns it so tests can override it.
  - `build_messages(system_prompt: str, summary: str | None, history: list[Message]) -> list[BaseMessage]` in `context.py`. `history` is the last 20 rows of the chat, oldest first, ending with the user message being answered. Output: one `SystemMessage` (the prompt, then, if a summary exists, a blank line and `Summary of the conversation so far:` followed by it), then the history as `HumanMessage`/`AIMessage`. Leading assistant messages in the window are dropped so the first one after the system message is always from the user.
  - `build_graph(model: BaseChatModel) -> CompiledStateGraph` in `graph.py`: a `StateGraph(MessagesState)` with a single node named `agent` between `START` and `END`. Stage 2 adds a tool node here.
  - `sse(event: str, data: dict) -> str` and `async run_turn(*, session_id: UUID, system_prompt: str, summary: str | None, model: BaseChatModel) -> AsyncIterator[str]` in `runner.py`.
  - `POST /sessions/{session_id}/chat` returning `text/event-stream`.
- Rules for the endpoint, checked in this order before any streaming, each as a JSON error:
  1. Body is `{"message": str}` with 1–20,000 characters after trimming, or `{"retry": true}`; anything else is 422.
  2. Agent status is `live`, else 409 `agent_not_live`.
  3. Agent has a provider and model, else 409 `llm_not_configured`.
  4. The user has a key for that provider, else 409 `missing_api_key`, with the provider's display name in the message.
  5. No reply is being generated for this chat, else 409 `reply_in_progress`. Tracked with an in-process set of session IDs in `runner.py`, added before streaming and removed in a `finally`.
  6. For a retry: the chat's last message has role `user`, else 409 `nothing_to_retry`. No new row is saved.
  7. For a new message: save the user row, set `last_message_at`, and if the title is still `"New chat"` set it to the first 60 characters of the message.
- Rules for `run_turn`:
  - It opens its own database session from `session_factory`; it does not use the request's.
  - It streams the graph with `stream_mode="messages"` and yields a `token` event for each non-empty text chunk from node `agent`. Chunk content may be a string or a list of parts; extract the text of both.
  - Normal finish: save the assistant row, yield `done` with its ID.
  - Model exception: log the exception type only, save nothing, yield `error` with code `model_error` and message `The model couldn't reply. Check your API key and try again.`, then `done` with a null ID.
  - Cancelled (Stop pressed or client gone): in a `finally`, save the text generated so far as the assistant row if it is non-empty, using `asyncio.shield`.
  - After a saved reply, start `maybe_update_summary(session_id)` with `asyncio.create_task` (Task 8 provides it; until then a no-op).

- [ ] **Step 1: Write the failing tests for the context** in `test_context.py`:

```python
def test_system_prompt_only(): ...             # no summary -> content == prompt
def test_summary_appended(): ...                # contains "Summary of the conversation so far:\nS"
def test_roles_mapped_in_order(): ...           # user, assistant, user -> Human, AI, Human
def test_leading_assistant_dropped(): ...       # history starting with assistant -> first after system is Human
def test_history_ending_with_user_ok(): ...     # the retry case
```

- [ ] **Step 2: Write the failing tests for chat** in `test_chat.py`. A fixture `fake_model(reply="Hello there")` overrides `get_model_factory` with a `GenericFakeChatModel`; `failing_model(after=1)` yields one chunk then raises; `slow_model` waits on an `asyncio.Event` between chunks. A helper `read_events(response) -> list[tuple[str, dict]]` parses the stream. A fixture `live_chat` gives a live agent with a provider, model, saved key, and one session.

```python
async def test_reply_streams_and_is_saved(client, user_a, live_chat, fake_model, db):
    events = read_events(await client.post(f"/sessions/{sid}/chat", json={"message": "Hi"}, headers=user_a))
    assert "".join(d["text"] for e, d in events if e == "token") == "Hello there"
    assert events[-1][0] == "done" and events[-1][1]["message_id"]
    # messages table: [("user", "Hi"), ("assistant", "Hello there")]

async def test_first_message_sets_title(...): ...                 # title == first 60 chars
@pytest.mark.parametrize("body", [{"message": ""}, {"message": "   "}, {"message": "x" * 20001}, {}])
async def test_bad_message_422_saves_nothing(...): ...             # Review Focus 1
async def test_stopped_agent_409(...): ...                         # agent_not_live      (Review Focus 5)
async def test_no_model_409(...): ...                              # llm_not_configured
async def test_no_key_409(...): ...                                # missing_api_key     (Review Focus 5)
async def test_model_failure_sends_error_then_done(client, user_a, live_chat, failing_model, db):
    # events end with ("error", {"code": "model_error", ...}), ("done", {"message_id": None})
    # messages table has only the user row                         # Review Focus 2
async def test_retry_answers_without_duplicating(...): ...        # after a failure, {"retry": true} -> one user row, one assistant row
async def test_retry_with_nothing_to_retry_409(...): ...
async def test_second_send_while_replying_409(client, user_a, live_chat, slow_model): ...   # Review Focus 3
async def test_cancel_saves_partial_reply(...): ...               # close the stream mid-reply -> assistant row holds the partial text
async def test_list_content_chunks_are_joined(...): ...           # model emitting content as a list of text parts
async def test_other_user_gets_404(...): ...
async def test_error_message_has_no_key_or_exception_text(...): ...
```

- [ ] **Step 3: Run** `pytest backend/tests/test_context.py backend/tests/test_chat.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement** `context.py`, `graph.py`, `runner.py`, `chat.py`, and `build_chat_model`.
- [ ] **Step 5: Run the whole backend suite.** Expected: PASS.
- [ ] **Step 6: Commit** `feat: streaming chat with retry and partial save`.

### Task 8: Chat summaries

**Files:**
- Create: `backend/app/agent/summarizer.py`
- Modify: `backend/app/agent/runner.py` (call it)
- Test: `backend/tests/test_summarizer.py`

**Interfaces:**
- Consumes: `session_factory`, `get_settings`.
- Produces: `async maybe_update_summary(session_id: UUID, *, model: BaseChatModel | None = None) -> bool`. Counts the chat's messages created after `summary_updated_at` (all of them when it is null). Under 10: returns False. Otherwise it asks the model for a 50–100 word summary given the previous summary and those messages, stores it in `sessions.summary`, sets `summary_updated_at` to now, and returns True. When `model` is None it builds a Gemini model from `summary_model` and `platform_gemini_api_key`; if that key is empty it returns False. Any exception is logged by type and returns False; it never raises.

- [ ] **Step 1: Write the failing tests:**

```python
async def test_under_ten_messages_no_summary(db, chat_with_messages): ...     # 9 messages -> False, summary None
async def test_ten_messages_writes_summary(...): ...                          # fake model -> True, summary == its text, summary_updated_at set
async def test_counts_only_messages_after_last_summary(...): ...              # summarised, then 9 more -> False
async def test_previous_summary_is_sent_to_model(...): ...                    # the fake model's received prompt contains the old summary
async def test_missing_platform_key_returns_false(...): ...
async def test_model_error_returns_false_and_keeps_old_summary(...): ...
```

- [ ] **Step 2: Run the tests.** Expected: FAIL.
- [ ] **Step 3: Implement**, and replace the no-op in `runner.py`.
- [ ] **Step 4: Run the whole backend suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat: chat summaries on the platform key`.

### Task 9: Frontend shell — landing, sign-in, app layout

**Files:**
- Create: everything under `frontend/` except the files Tasks 10–12 own; in particular `src/main.jsx`, `App.jsx`, `index.css`, `lib/supabase.js`, `lib/api.js`, `lib/auth.jsx`, `lib/queryClient.js`, `layouts/AppShell.jsx`, `pages/Landing.jsx`, `pages/Analytics.jsx`, `components/StatusBadge.jsx`, `.env.example`

**Interfaces:**
- Produces:
  - `supabase` client from `lib/supabase.js`, built from `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`.
  - `api(path, {method, body}) -> Promise<json>` in `lib/api.js`: prefixes `VITE_API_URL`, adds the Bearer token from the current Supabase session, throws `ApiError {status, code, message}` on a non-2xx response, and on 401 signs out and redirects to `/` with the message "Your session expired. Sign in again." Also `getAccessToken()` for the SSE helper.
  - `AuthProvider` and `useAuth() -> {session, user, loading, signInWithGoogle, signOut}` in `lib/auth.jsx`; `user` comes from `GET /me`.
  - `<StatusBadge status>` for `draft` (amber, "Draft"), `live` (green, "Live"), `stopped` (grey, "Stopped").
  - Routes: `/` Landing (signed-in users go to `/app/agents`); `/app/agents`, `/app/agents/new`, `/app/agents/:agentId`, `/app/chat`, `/app/chat/:agentId/:sessionId?`, `/app/analytics/:agentId?`, all inside `AppShell` behind a guard that redirects to `/` without a session.

- [ ] **Step 1: Scaffold.** `npm create vite@latest frontend -- --template react`, add Tailwind with `@tailwindcss/vite`, add `jsconfig.json` and the Vite alias `@` → `src`, then `npx shadcn@latest init` with defaults (neutral base). Install the packages from the frontend doc §3 except `react-dropzone` and `recharts`. Add shadcn components: button, input, textarea, label, card, badge, dialog, alert-dialog, dropdown-menu, select, radio-group, skeleton, sonner, avatar, separator, sheet, alert.
- [ ] **Step 2: Write `.env.example`** with `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL=http://localhost:8000`.
- [ ] **Step 3: Implement** the lib files, `App.jsx` with the router and guard, `Landing.jsx` (copy and states exactly as frontend doc §4), `AppShell.jsx` (frontend doc §5.1 and §5.3; the user menu has "API keys" and "Sign out"), and `Analytics.jsx` showing "Analytics arrives in a later stage."
- [ ] **Step 4: Verify the build.** Run `npm run build` and `npm run lint` in `frontend/`. Expected: both finish with no errors.
- [ ] **Step 5: Stop point 2.** Ask the project owner to fill in `frontend/.env` and the Supabase and Gemini values in `backend/.env`, and to confirm the Google provider and the `http://localhost:5173` redirect URL are set in Supabase.
- [ ] **Step 6: Verify in the browser.** Start both servers. The landing page shows the headline and the Google button. After the owner signs in: the app shell appears with their name and avatar, the three nav items switch pages, a `users` row exists, and Sign out returns to `/`. Opening `/app/agents` while signed out redirects to `/`.
- [ ] **Step 7: Commit** `feat: frontend shell with Google sign-in`.

### Task 10: API keys dialog

**Files:**
- Create: `frontend/src/components/ApiKeysDialog.jsx`
- Modify: `frontend/src/layouts/AppShell.jsx` (open it from the user menu)

**Interfaces:**
- Consumes: `api`, `GET /llm-keys`, `PUT|DELETE /llm-keys/{provider}`.
- Produces: `<ApiKeysDialog open onOpenChange />`, and an exported `useLlmKeys()` query hook (query key `["llm-keys"]`) that Tasks 11 and 12 reuse. Saving or removing a key invalidates that query.

- [ ] **Step 1: Implement** as frontend doc §5.2: one row per provider; input + "Save key" when none is saved; hint (`•••• 9xyz`) + "Replace" and "Remove" when saved; spinner while checking; toast "Key saved"; inline error "This key didn't work. Check it and try again." on `invalid_api_key`; the note about encrypted storage.
- [ ] **Step 2: Verify.** `npm run build` and `npm run lint` pass. In the browser: saving a wrong key shows the inline error; saving a real key shows the hint and never the key; Replace and Remove work; the browser's network tab shows no response containing the full key.
- [ ] **Step 3: Commit** `feat: API keys dialog`.

### Task 11: Agent list and wizard

**Files:**
- Create: `frontend/src/pages/AgentsList.jsx`, `frontend/src/pages/AgentWizard/index.jsx`, `Basics.jsx`, `Behavior.jsx`, `Model.jsx`, `Deploy.jsx`

**Interfaces:**
- Consumes: `api`, `useLlmKeys`, `StatusBadge`, the agents, personas, and `llm-models` endpoints.
- Produces: an exported `useAgents()` query hook (query key `["agents"]`) reused by Task 12.

- [ ] **Step 1: Implement the list** as frontend doc §6.1, with these additions: the row menu has "Chat", "Stop" (live) or "Start" (stopped), and "Delete"; Chat is disabled for drafts. Delete asks "Delete {name}? Its chats will be deleted too."
- [ ] **Step 2: Implement the wizard** as frontend doc §6.2 with four numbered steps: Basics, Behavior, Model, Deploy. The current step is kept in the URL as `?step=`. Basics "Continue" on a new agent calls `POST /agents` and moves to `/app/agents/{id}?step=behavior`; every later "Continue" calls `PATCH`. On edit, any step can be opened directly. Forms use react-hook-form with zod and the limits from Task 5.
  - Behavior: radio cards for the twelve personas plus "Custom prompt"; choosing a persona puts its prompt in the editable text area; choosing Custom prompt empties it.
  - Model: provider radio, model select, key status with inline "Save key", and a "Skip for now" link.
  - Deploy: read-only summary with an "Edit" link per step; warning "Add your API key before chatting." when no key exists for the provider; "Deploy agent" for draft and stopped agents, "Save changes" for live ones; on success the toast "{name} is live" with a "Start chatting" button.
- [ ] **Step 3: Verify.** `npm run build` and `npm run lint` pass. In the browser: the empty state shows before any agent exists; creating an agent and leaving after step 1 keeps it as a Draft; the full wizard ends with a Live agent; edit reopens it prefilled; Stop and Start change the badge; Delete removes the row.
- [ ] **Step 4: Commit** `feat: agent list and wizard`.

### Task 12: Chat page

**Files:**
- Create: `frontend/src/lib/sse.js`, `frontend/src/pages/Chat.jsx`, `frontend/src/components/AgentSelect.jsx`, `frontend/src/components/chat/SessionList.jsx`, `MessageList.jsx`, `Message.jsx`, `Composer.jsx`

**Interfaces:**
- Consumes: `api`, `getAccessToken`, `useAgents`, `useLlmKeys`, the sessions and chat endpoints.
- Produces: `streamChat({sessionId, body, signal, onToken, onError, onDone}) -> Promise<void>` in `lib/sse.js`, built on `fetchEventSource` with `method: "POST"` and `openWhenHidden: true`. Its `onopen` turns a non-200 response into an `ApiError`; its `onerror` rethrows, so the library never retries by itself.

- [ ] **Step 1: Implement** the layout of frontend doc §7.1, messages as §7.2, and the blocked state as §7.6.
  - The agent selector lists live and stopped agents. No such agents: "You don't have a live agent yet." with "Create agent".
  - "New chat" creates a session and opens it. Sessions are grouped by date and have a "Delete" menu item.
  - Replies render with react-markdown and remark-gfm. While streaming, "Send" becomes "Stop", which aborts the request and then reloads the messages. Enter sends; Shift+Enter adds a line. The view scrolls to the newest message unless the user has scrolled up.
  - An `error` event or a failed request shows an inline error under the user's message with "Retry", which sends `{"retry": true}`.
  - No key for the agent's provider: the composer is replaced by "Add your {provider} API key to start chatting." with "Add API key", which opens the keys dialog; saving a key unlocks the chat without a reload.
  - Stopped agent: history stays readable and the composer is replaced by "This agent is stopped. Start it to chat." with "Start agent".
  - The session list refreshes after each reply so new titles and ordering appear.
- [ ] **Step 2: Verify.** `npm run build` and `npm run lint` pass. In the browser with a real key: a reply streams token by token and renders Markdown (ask for a table and a code block); Stop keeps the partial reply after a reload; a second chat keeps its own history; deleting a chat removes it; removing the key shows the blocked state and re-adding it unlocks the chat; stopping the agent shows the stopped state.
- [ ] **Step 3: Commit** `feat: chat page with streaming`.

### Task 13: Final walkthrough (stop point 3)

**Files:** none, unless the walkthrough finds a defect.

- [ ] **Step 1: Run the whole backend suite** with `backend/.venv/Scripts/python -m pytest backend/tests -v`. Expected: all pass.
- [ ] **Step 2: Check for secrets.** `git log -p` contains no value from either `.env` file; both `.env` files are untracked (`git status --ignored`); the backend's console output from the walkthrough contains no API key.
- [ ] **Step 3: Walk through with the project owner** every goal in design §2, in order, in the browser. Check goal 7 by sending ten messages in one chat and reading `sessions.summary` in the database. Check goal 8 by signing in with a second Google account and confirming the first account's agents, keys, and chats are absent.
- [ ] **Step 4: Fix anything found**, each fix with a test where the backend is involved, then re-run steps 1 and 2.
- [ ] **Step 5: Commit** any fixes. Do not push.
