# Stage 1 Design — Sign-in, Agents, and Chat

Date: 2026-11-16
Status: waiting for approval

This document scopes stage 1 of the Custom Agent Platform MVP. The full product is described in two existing documents, which stay the source of truth for anything not said here:

- `Project data/custom-agent-platform-project- complete architecture.md` — called **the spec** below.
- `Project data/custom-agent-platform-design.md` — called **the frontend doc** below.

Where this document disagrees with them, this document wins for stage 1.

## 1. Intent

Build the MVP in three stages, each ending with something that works in the browser. Stage 1 delivers the core loop: a person signs in with Google, creates an agent, and chats with it using their own Gemini or OpenAI key.

| Stage | Contents |
|---|---|
| **1 (this document)** | Google sign-in, agents (create, edit, deploy, stop), API keys, chat with streaming replies, sessions, session summaries |
| 2 | Tools (built-in, the 10 APIs, SerpApi) and the knowledge base (RAG on pgvector) |
| 3 | App connections (Composio), approve/reject for write actions, analytics (PostHog) |

## 2. Goals

At the end of stage 1, on the local machine:

1. A visitor opens the landing page and signs in with Google.
2. They save a Gemini or OpenAI key, which is checked, encrypted, and never shown again.
3. They create an agent through the wizard (basics, behavior, model, deploy) and can edit it later.
4. They deploy the agent, stop it, and start it again.
5. They chat with a live agent. Replies stream in, render as Markdown, and can be stopped.
6. They can have several chats per agent, reopen old ones, and delete them.
7. Each chat keeps a short summary so long chats stay within the model's context.
8. A user can never see or change another user's agents, keys, or chats.

## 3. Non-goals for stage 1

- Tools of any kind, the knowledge base, app connections, approve/reject, analytics.
- Wizard steps 4 (knowledge), 5 (tools), and 6 (apps). The stepper shows only the four steps that exist.
- The Analytics page. The nav item exists and opens a placeholder that says it arrives in a later stage.
- Rate limiting, deployment, dark mode, polished mobile layout.
- The LangGraph Postgres checkpointer. It is only needed to pause for approvals, so it arrives in stage 3.

## 4. Anti-goals

- No secret (LLM key, database password, Supabase or Gemini key) is ever committed, logged, returned by the API, or sent to tracing.
- Nothing in stage 1 may block stages 2 and 3. The agent graph, the database migrations, and the wizard must accept tools, documents, and apps later without a rewrite.
- No pushing to any remote. Commits are local only.

## 5. Constraints

- Windows 11, no Docker. PostgreSQL 18.7 installed directly, running as service `postgresql-x64-18`.
- Python 3.13, installed next to the machine's existing Python 3.10.9, which stays untouched. The current FastAPI, LangChain, and SQLAlchemy releases need Python 3.11 or newer. The project uses 3.13 only inside `backend/.venv`.
- Node.js 26.13.1, git 2.47.
- Backend runs on `http://localhost:8000`, frontend on `http://localhost:5173`.
- A free Supabase cloud project is used for Google sign-in only. All data lives in the local Postgres.
- The project owner must approve any serious action (installs, anything outside the project folder, anything destructive).

## 6. Approaches considered

**How to split the work into stages**

- **A — core loop first (chosen).** Stage 1 is sign-in, agents, and chat. It is a full day, but it ends with the real product loop working, and stages 2 and 3 each add one clear capability on top.
- **B — smaller first stage.** Stage 1 is sign-in and agent creation only, with no chat. Safer for one day, but nothing can be tested end to end, and stage 3 becomes very heavy.

A was chosen because every stage ends with something usable.

**Where chat history lives** (builder's call, see §9)

- **Messages table as the source of truth (chosen).** Each turn, the backend builds the model's input from the `messages` table. Simple, and the context stays small.
- **LangGraph checkpointer as the source of truth.** The graph state holds the whole conversation. It keeps growing and duplicates the `messages` table.

## 7. Decisions already made by the project owner

- The platform's own Gemini key pays for session summaries (and later for embeddings and query rewriting). The user's own key pays only for the agent's chat replies.
- Models: a short fixed list of Gemini and OpenAI models.
- Agents can be deployed, stopped, restarted, and edited after creation.
- Persona prompts are drafted by the builder.
- No pushing during development.

## 8. What gets built

### 8.1 Backend (`backend/`)

Python, FastAPI, SQLAlchemy 2 (async, `asyncpg`), Alembic migrations, LangGraph, LangChain `init_chat_model`. Folder layout follows spec §17.

**Database.** A new database `agent_platform` in the local Postgres. Stage 1 creates five tables exactly as spec §14 defines them: `users`, `llm_keys`, `agents`, `sessions`, `messages`. The other tables arrive as new migrations in later stages. Two differences from the spec:

- `agents.status` allows `draft`, `live`, and `stopped`.
- `agents.llm_provider` and `agents.llm_model` may be empty until the user completes the model step, because the frontend doc lets them skip it.

**Sign-in.** Every request carries the Supabase token as `Authorization: Bearer <token>`. The backend verifies it and takes the user ID only from the token. It supports both Supabase signing methods: public keys (JWKS) by default, or the shared secret if `SUPABASE_JWT_SECRET` is set. The user row is created or updated on `GET /me`.

**Endpoints** (from spec §15, plus three marked new):

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | Current user; creates the user row on first call |
| GET | `/personas` | The predefined personas with their prompts |
| GET | `/llm-models` | **New.** The fixed model list per provider, for the wizard dropdown |
| GET | `/llm-keys` | Saved providers with key hints |
| PUT | `/llm-keys/{provider}` | Check, encrypt, and save a key |
| DELETE | `/llm-keys/{provider}` | Remove a key |
| GET, POST | `/agents` | List and create agents |
| GET, PATCH, DELETE | `/agents/{agent_id}` | Read, update, delete an agent |
| POST | `/agents/{agent_id}/deploy` | Set status to `live` |
| POST | `/agents/{agent_id}/stop` | **New.** Set status to `stopped` |
| GET, POST | `/agents/{agent_id}/sessions` | List and create chats |
| GET | `/sessions/{session_id}` | **New.** One chat with its agent and status |
| GET | `/sessions/{session_id}/messages` | Message history |
| DELETE | `/sessions/{session_id}` | Delete a chat |
| POST | `/sessions/{session_id}/chat` | Send a message; the reply streams back |

Every query is filtered by the user ID from the token. Asking for someone else's agent or chat returns "not found".

**LLM keys.** Encrypted with Fernet using a master key from the environment. The API returns only the provider and the last four characters. A key is checked with one small request to the provider before it is saved.

**Personas.** Twelve, defined in code: Customer care, Developer, Tester, Friend, Store owner, Teacher, Doctor, Career guidance, Writer, Research assistant, Sales assistant, Personal coach. Each has a key, a display name, a one-line description, and a prompt. The Doctor persona's prompt tells the agent to give general health information and to recommend seeing a real doctor. When an agent is saved, its final prompt is stored in `agents.system_prompt`, and the user can edit it.

**Agent lifecycle.** `draft` → `live` ⇄ `stopped`. Deploying needs a name and a prompt; a missing model or key is a warning, not a blocker, as the frontend doc says. A stopped agent keeps its chats readable but refuses new messages. Edits to an agent apply to messages sent after the edit.

**Chat.** One message goes through these steps:

1. Check the token, that the chat and agent belong to the user, that the agent is `live`, and that the user has a key for the agent's provider. Each failure returns a clear error the frontend can show.
2. Build the model's input: the agent's prompt, the chat summary if there is one, the most recent messages (the last 20), and the new message.
3. Run a LangGraph graph with one agent node, using the user's key. The graph is built so a tool node can be added in stage 2 without changing the chat endpoint.
4. Stream the reply as server-sent events: `token`, `error`, `done`. The other event types in spec §12.4 arrive with the features that need them.
5. Save the user message before the model runs and the assistant message when it finishes. If the user presses Stop or disconnects, save what was generated so far.
6. Give a new chat a title from its first message.

**Failed replies and Retry.** If the model call fails, the stream sends `error`, the user's message stays saved, and no assistant message is saved. The frontend shows the error inline with a **Retry** button, as frontend doc §7.3 says. Retry calls the same chat endpoint with `{"retry": true}` and no new text; the backend then answers the last user message again instead of saving a second copy. The endpoint accepts a retry only when the last message in the chat is an unanswered user message. The step that builds the model's input must work when the history ends with a user message.

**Summaries.** After a reply, if ten or more messages have arrived since the last summary, a background task writes a new 50–100 word summary with a small Gemini model on the platform key and stores it on the chat. If the platform key is missing or the call fails, the chat continues without a summary and the failure is logged.

**Tracing.** LangSmith is switched on only by environment variables and is off by default. Keys are passed so they do not appear in traces.

**Configuration.** `backend/.env`, never committed, with a committed `backend/.env.example` listing every variable: database URL, Supabase URL, optional Supabase JWT secret, Fernet master key, platform Gemini key, allowed frontend origin, optional LangSmith settings.

**Tests.** `pytest` against a separate test database `agent_platform_test`. Covered: token checking, user creation, every ownership rule (a second user gets "not found"), key encryption and hints, the agent lifecycle, building the model input, and the chat stream using a fake model, so tests never call a real provider.

### 8.2 Frontend (`frontend/`)

Vite, React (JavaScript), Tailwind, shadcn/ui, and the packages listed in the frontend doc §3. Folder layout follows the frontend doc §11. Screens, copy, and states follow the frontend doc; only the differences are listed here.

| Screen | Stage 1 content |
|---|---|
| Landing | As frontend doc §4 |
| App shell | As §5, with all three nav items. Analytics opens a placeholder |
| API keys dialog | As §5.2 |
| Agent list | As §6.1. The row menu also has **Stop** or **Start**. Status badges: Draft (amber), Live (green), Stopped (grey) |
| Wizard | Steps Basics, Behavior, Model, Deploy, as §6.2. Steps Knowledge, Tools, and Apps are not shown yet |
| Chat | As §7.1, §7.2, and §7.6. Only the `token`, `error`, and `done` events are handled |
| Chat with a stopped agent | History is readable. The message box is replaced by "This agent is stopped. Start it to chat." with a **Start agent** button |

The chat agent selector lists live and stopped agents, so old chats stay reachable. Draft agents are not listed.

Frontend configuration lives in `frontend/.env` (not committed) with a committed `.env.example`: Supabase URL, Supabase publishable key, backend URL.

Frontend checking in stage 1 is done by running the app in the browser and walking through the goals in §2. Automated frontend tests are not part of stage 1.

### 8.3 Repository

`git init` in the project folder, with a `.gitignore` that excludes `.env` files, `node_modules`, Python virtual environments, and build output. Commits are local and frequent. Nothing is pushed.

## 9. Builder's calls

These were decided by the builder, not the project owner. Each can be changed.

- Chat history: the `messages` table is the source of truth, and no checkpointer is used in stage 1 (§6).
- The model sees the last 20 messages plus the summary. The summary refreshes every 10 messages.
- Three new endpoints: `/llm-models`, `/agents/{id}/stop`, `/sessions/{id}`.
- The model step may be skipped, so provider and model can be empty on a draft.
- The twelve personas listed in §8.1.
- The exact model names in the fixed list are checked against the providers' current documentation at build time.
- The wizard hides the three later steps instead of showing them disabled.
- Python dependencies are managed with `pip` and a virtual environment in `backend/.venv`.
- Rate limiting waits for stage 3.
- A failed reply keeps the user's message, and Retry answers it again through the same chat endpoint.
- Build order and stop points: the backend is built and tested first with fake tokens and a fake model, so it does not wait for any secrets. The build stops for the project owner at three points: before creating the databases, before the first real sign-in (the `.env` files must be filled in), and for the final walkthrough.
- The final walkthrough in §11 is done together: the builder starts both servers, and the project owner signs in with Google and enters their own key in the browser.

## 10. What the project owner must provide

Secrets go into the `.env` files by the project owner's own hand, not into the chat.

1. **Supabase:** a project with the Google provider switched on and `http://localhost:5173` added as an allowed redirect URL. From it: the project URL and the publishable (anon) key.
2. **Postgres:** the password of the local `postgres` user, or a ready-made database user, so the `agent_platform` and `agent_platform_test` databases can be created.
3. **Platform Gemini key:** for session summaries.
4. **A Gemini or OpenAI key of their own:** entered in the app's API keys dialog to test chatting.

## 11. Done means

- Every goal in §2 has been walked through in the browser on this machine.
- The backend tests pass.
- No secret appears in git history, logs, or API responses.
