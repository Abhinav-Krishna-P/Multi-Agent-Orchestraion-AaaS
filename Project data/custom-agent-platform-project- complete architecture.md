# Custom Agent Platform (Agent as a Service) — Complete Project Specification

> This document is the single source of truth for the project. It was written from a full design discussion so that a developer or another AI can build the project without any other context. Read it fully before writing code.

---

## 1. The Idea

### 1.1 What the app is
A web platform where users build their own custom AI agents without writing agent code. A user gives an agent:
- a **personality / behavior** (a predefined persona or a custom prompt),
- **knowledge** (their own text documents, searched through a RAG pipeline),
- **API tools** (weather, web search, currency, flights, etc.),
- **app connections / plugins** (GitHub, Gmail, Google Drive, Notion via Composio),

then **chats with the agent inside the website** using **their own LLM API key** (Gemini or OpenAI), and sees **analytics** of how the agent performs.

**One-line pitch:** *A platform where anyone can build their own AI agent, give it knowledge, a personality, tools and app connections, then chat with it using their own Gemini or ChatGPT key, and track how it performs.*

### 1.2 Target users
Developers, product creators and product owners.

### 1.3 Project status and stage
- This is a **production product being built as an MVP**. It will be scaled after the MVP.
- The MVP is **built and run locally first**. Hosting/deployment is decided later.
- **No billing, credits or payments in the MVP.**
- The platform does **not** provide LLMs. Users bring their own API key (BYOK).

### 1.4 Example of the core experience
A user creates an agent, connects GitHub, then types in chat: *"What is the latest project I'm working on in GitHub?"*
The agent picks the GitHub "list repositories" tool (from Composio), calls it with the user's stored connected-account ID, gets the repos sorted by most recent activity, and replies: *"Your latest repo is `xyz`, last updated …"*.
If the user types *"Create a repo called my-app"* and write access is enabled, the chat shows an **Approve / Reject** card. The repo is created only after Approve.

---

## 2. MVP Scope

### 2.1 In scope
- Google sign-in (Supabase Auth), user synced into our own Postgres.
- Three pages: **Create your agent**, **Chat with your agent**, **Analytics**.
- Agent configuration: persona (one), custom prompt, knowledge base, API tools, Composio plugins, LLM provider/model.
- Knowledge base: pasted text, `.txt`, `.md`, text-based `.pdf`.
- RAG pipeline on **pgvector** with **Gemini embeddings**, hybrid search, re-ranking.
- 10 external API services exposed as ~10–20 tools, plus built-in tools.
- Composio app connections with read-only or read-write access.
- Approval step (human-in-the-loop) before every write action.
- Sessions with full raw message history + a short summary per session.
- Streaming chat responses (SSE).
- User-facing analytics via **PostHog**.
- Internal tracing/evaluation via **LangSmith** (developer-only, not shown to users).
- LLM providers: **Gemini and OpenAI (ChatGPT) API keys only**.

### 2.2 Explicitly out of scope for the MVP (future)
- Public developer API (using agents from external projects), platform API keys, end-user IDs, webhooks.
- Billing, credits, pay-as-you-go, payment system.
- MCP (both as client and as server).
- Multi-agent systems.
- Images, scanned PDFs, OCR in the knowledge base.
- Other LLM providers (Claude etc.) and account/subscription-based LLM connections.
- Destructive actions (deleting repos, emails, files).
- LLM token-usage analytics (optional, skipped for MVP — see §13).
- Hosting/deployment.

---

## 3. Pages and User Flow

### 3.1 Overall flow
1. User opens the website → **signs in with Google** (Supabase Auth).
2. Backend verifies the token and **upserts the user** into our `users` table.
3. User lands in the app. **Chat with your agent** is empty because no agent exists yet → user is guided to **Create your agent**.
4. User creates and configures an agent, then clicks **Deploy** → agent status becomes `live`.
5. User goes to **Chat with your agent**, selects one of their agents, starts a conversation (a new **session**).
6. User checks **Analytics** for that agent.

### 3.2 Page 1 — Create your agent
An agent starts as an empty node with zero knowledge. The user configures it step by step (a wizard/form; no drag-and-drop canvas in the MVP):

1. **Basics:** name, description.
2. **Behavior (persona):** choose **exactly one** predefined persona, or write a **custom prompt**. The user can also edit the persona prompt.
3. **LLM:** choose provider (Gemini or OpenAI) and model; enter the API key (or reuse a saved key). **This step can be skipped** and done later.
4. **Knowledge base (memory):** toggle on/off. If on: choose search mode (semantic / keyword / hybrid — hybrid is default) and add documents (paste text, upload `.txt`, `.md`, `.pdf`). Documents can also be added later from the agent's settings.
5. **API tools:** tick which tools the agent can use (from the built-in catalog of 10 API services).
6. **Plugins (apps):** list of Composio apps (Gmail, GitHub, Google Drive, Notion, …). For each app the user connects, they choose **Read only** or **Read & write**, then complete the app's OAuth login. Then they tick which actions of that app the agent may use.
7. **Deploy:** agent becomes `live` and appears in the chat page.

All settings are editable later.

### 3.3 Page 2 — Chat with your agent
- Select an agent (only the user's own agents are listed).
- Start a new conversation (creates a session) or continue an old one.
- **If the user has no API key saved for the agent's provider, the chat is blocked** with a message: *"Add your API key to start chatting"* and a link to add it.
- Replies stream token by token (SSE).
- The UI shows tool activity (e.g. "Searching knowledge base…", "Calling GitHub…"), sources/citations for knowledge-base answers, **Approve / Reject cards** for write actions, and a **Reconnect** button when an app connection has expired.

### 3.4 Page 3 — Analytics
Per agent: number of sessions and messages, tool calls (by tool and by type: API / plugin / knowledge base), success vs failure, average tool latency, knowledge-base searches, write actions approved vs rejected, connection errors, activity over time. Data comes from **PostHog**, queried **server-side by our backend** and filtered to the user's own agents (the frontend never queries PostHog directly for other users' data).

---

## 4. Architecture Overview

```
User (browser, React)
   │  Google sign-in (Supabase Auth) → JWT
   ▼
FastAPI backend (REST + SSE)
   │  verify JWT → user_id (upsert into users)
   │
   ├── Agent config CRUD ───────────────► Postgres (core DB)
   │
   ├── Document upload ─► ingestion (background) ─► chunk ─► embed (Gemini) ─► pgvector
   │
   └── Chat (SSE) ─► LangGraph agent
                        │  context: persona system prompt + session summary + recent messages
                        │  LLM: user's own key (Gemini / OpenAI)
                        │
                        ├─► Tools layer (only this agent's enabled tools)
                        │     ├─ Built-in tools (calculator, date/time)
                        │     ├─ API tools ─► Open-Meteo, Tavily, Wikipedia, ... (10 services)
                        │     ├─ Knowledge-base search ─► pgvector (filtered by agent_id)
                        │     └─ Composio tools ─► ◇ Write action?
                        │                              No  ─► Composio ─► GitHub/Gmail/...
                        │                              Yes ─► Approve/Reject card in chat
                        │                                       Approve ─► Composio ─► app
                        │                                       Reject  ─► back to agent ("user declined")
                        │
                        ├─► Postgres: messages, session summary, LangGraph checkpoints
                        ├─► PostHog: analytics events (user-facing)
                        └─► LangSmith: traces + evals (developer-only)
```

---

## 5. Tech Stack (final)

| Area | Choice |
|---|---|
| Language | Python |
| Backend | FastAPI (REST API + SSE streaming) |
| Frontend | React (JS) |
| Agent framework | LangGraph (agent loop, tool node, interrupts, checkpointer) |
| LLM/RAG utilities | LangChain (`init_chat_model`, text splitters, loaders, retrievers) |
| Core database | PostgreSQL (our own instance) |
| Vector store | pgvector extension inside the same Postgres |
| Embeddings | Google Gemini embedding model ("Gemini Embedding 2" — verify exact model ID in Google's docs) |
| Auth | Supabase Auth, Google sign-in only (auth only; data lives in our Postgres) |
| App integrations | Composio |
| User-facing analytics | PostHog (events) |
| Internal tracing & evals | LangSmith (developer use only) |
| LLM providers (BYOK) | Gemini, OpenAI |

Removed from earlier drafts and **not** part of the MVP: MCP, multi-agent, payment/credit system.

---

## 6. Authentication

- **Supabase Auth is used only for Google sign-in.** It is *not* the application database.
- Frontend uses Supabase's JS client for the Google login flow and sends the Supabase access token (JWT) as `Authorization: Bearer <token>` on every API request.
- FastAPI verifies the JWT (Supabase JWT secret / JWKS) on every request and reads `sub` (user ID), email, name.
- On first request (or every login), backend **upserts** the user into our `users` table. **Our `users.id` = Supabase user ID** so they always match.
- A free Supabase cloud project is required for login even while developing locally.
- One sign-in method only (Google) for the MVP.

---

## 7. Agent Configuration Details

### 7.1 Behavior / personas
- 10–15 predefined personas defined in code as an array/dictionary, e.g.: **Customer care, Developer, Tester, Friend, Store owner, Teacher, Doctor, Professional career guidance**, and others.
- Each persona = a prompt template with rules for tone, response style and role.
- The user selects **exactly one** persona, or writes a **custom prompt**.
- Implementation: when the agent is saved, build the agent's full **system prompt** from the chosen template (and/or custom text) and store it on the agent row. The user can edit it. This is more predictable than injecting rules conditionally at runtime.
- No dedicated backend complexity: personas are static data; the agent stores `persona_key` + final `system_prompt`.

### 7.2 LLM provider and API keys (BYOK)
- Supported in MVP: **Gemini** and **OpenAI** API keys only.
- Keys are stored **per user per provider**, encrypted at rest (e.g. Fernet with a master key from environment variables for the MVP; a KMS later).
- Never return the key to the frontend after saving; show only a hint (last 4 characters).
- Never log keys; keep them out of LangSmith traces.
- Validate the key with a cheap test call when it's entered.
- Each agent stores its chosen `llm_provider` and `llm_model`.
- Use LangChain `init_chat_model` (or equivalent) so one code path supports both providers.
- Key entry can be skipped during agent creation; chat is blocked until a key exists.

### 7.3 Knowledge base (memory)
Optional per agent. See §8 for the pipeline.

### 7.4 API tools
Selected from the catalog in §9. Saved in `agent_tools`.

### 7.5 Plugins (Composio apps)
Connected per agent with read-only or read-write access. Enabled actions saved in `agent_tools`. See §10.

### 7.6 Deploy
`agents.status` goes from `draft` to `live`. Only `live` agents appear in the chat page.

---

## 8. RAG Pipeline (Knowledge Base)

### 8.1 Supported inputs (MVP)
- Pasted text (text box)
- `.txt`, `.md` files
- `.pdf` — **text-based only**. Extract text with a LangChain PDF loader and keep the page number per chunk. If a PDF yields no text (scanned/image PDF), reject it with: *"This PDF has no readable text."*
- No images, no OCR in the MVP.

### 8.2 Ingestion flow (runs in the background)
1. Upload → create `documents` row with status `pending`.
2. Background task (FastAPI BackgroundTasks for MVP; Celery/ARQ later) sets status `processing`.
3. Extract text (PDF loader for PDFs).
4. **Split** into chunks with LangChain's recursive text splitter (with overlap). Chunk size to be tuned with evals.
5. Prepend **contextual header** (document title / section) to each chunk's text before embedding.
6. **Embed** each chunk with the Gemini embedding model. *(The embedding model embeds; it does not chunk — splitting and embedding are separate steps.)*
7. Store chunks in `document_chunks` with `agent_id`, `user_id`, metadata (document name, page, section), the vector, and a full-text `tsvector`.
8. Status `ready` (or `failed` with an error message). UI shows indexing status.
9. Optional: store a content hash to avoid duplicate uploads.

**Lock the embedding model:** store the model name with each document/chunk. Vectors from different models can't be mixed; switching models requires re-embedding everything.

### 8.3 Isolation
- One shared `document_chunks` table. **Every search is filtered by `agent_id`** (and the backend verifies the agent belongs to the requesting user). No index or table per agent.
- Deleting an agent deletes its documents and chunks (cascade).

### 8.4 Retrieval (at chat time)
1. Retrieval is exposed as a **tool** (`search_knowledge_base`) that the agent calls only when needed (not on every message like "hi").
2. **Query rewriting:** rewrite follow-up questions into a standalone query using the chat history.
3. **Search mode** per agent: semantic (pgvector), keyword (Postgres full-text search, BM25-style ranking), or **hybrid (default)** — both merged with **Reciprocal Rank Fusion (RRF)**.
4. Retrieve ~20 candidates → **re-rank** to the top ~5 (Cohere Rerank or a free cross-encoder such as BGE reranker).
5. **Relevance threshold:** if the best score is too low, the agent says it doesn't know instead of guessing.
6. Return chunks with **citations** (document name, page) — shown in the chat UI.
7. Indexes: **HNSW** on the vector column, **GIN** on the `tsvector`, B-tree on `agent_id`.

### 8.5 Evaluation (LangSmith, developer-only)
- Build a test set of 20–30 questions with expected answers from sample documents.
- Measure: did retrieval return the right chunks; is the answer faithful to the chunks; is it relevant to the question.
- Re-run after every change to chunk size, overlap, search mode or re-ranking, to prove each change helps.

---

## 9. Tools Layer

### 9.1 Concept
Every capability the agent has is a **tool**: a Python function with a name, a clear description and typed parameters. The LLM sees only the tool schema, decides which tool to call, LangGraph's tool node runs it, and the result goes back to the LLM, which writes the answer. The agent is **not** connected to APIs directly.

Three tool sources feed one combined list:
1. **Built-in / API tools** — written by us, kept in a **tool registry** (a dictionary `{tool_name: function}`). This includes the 10 direct API services (§9.4) and the SerpApi services (§9.5).
2. **Composio tools** — generated by the Composio SDK for the user's connected apps (we don't write these).
3. **Knowledge-base tool** — our RAG search.

### 9.2 Rules
- **One tool per action**, not per API (e.g. weather → `get_current_weather` and `get_weather_forecast`).
- Each tool is flagged **read** or **write** in the registry. All direct API services and all SerpApi services are read-only.
- Write clear descriptions — this is what makes the LLM pick the right tool.
- Load **only the agent's enabled tools** (from `agent_tools`) per request.
- For Composio, load only the **enabled actions**, never an app's full action list (GitHub alone has hundreds; too many tools confuse the LLM and waste tokens).
- API keys for these services (including the SerpApi key) are **platform keys in server environment variables**, never in prompts.
- Every HTTP call has a **timeout**; on failure, return a clean error message to the LLM instead of crashing.
- **Trim large JSON responses** before returning them to the LLM. This matters most for SerpApi, whose responses are large.
- Cache results for tight-quota APIs (AviationStack) and for SerpApi calls (faster repeat answers).
- Log a PostHog event after every tool call (see §13).

### 9.3 Built-in tools (no external API)
- `calculator` — plain Python.
- `get_current_datetime` — plain Python with timezone support (LLMs don't know the current date).

### 9.4 The 10 direct API services
These stay as the primary providers for their purpose. Free-tier figures are approximate and change often — **verify each pricing page before relying on them.**

| # | Service | Purpose | Key needed | Free tier (approx.) |
|---|---|---|---|---|
| 1 | Open-Meteo | Weather + forecast, geocoding (city → coordinates) | No | Free for **non-commercial** use (~10,000 calls/day). **Commercial use needs a paid plan** once the product launches. |
| 2 | Tavily | Web search built for AI agents (websites, news, recent info) | Yes (free) | ~1,000 searches/month |
| 3 | Wikipedia (MediaWiki API) | Facts and summaries | No | Free; send a User-Agent header, reasonable request rate |
| 4 | Frankfurter | Currency exchange rates (ECB data) | No | Free |
| 5 | AviationStack | Flight status (all flight questions) | Yes (free) | ~100 requests/month — tightest quota; cache results |
| 6 | Finnhub | Stock prices | Yes (free) | ~60 calls/minute |
| 7 | NewsData.io | News headlines | Yes (free) | ~200 requests/day |
| 8 | Nager.Date | Public holidays by country/year | No | Free |
| 9 | REST Countries | Country info (capital, population, currency, languages) | No | Free |
| 10 | OpenRouteService | Routes and directions | Yes (free) | ~2,000 route requests/day |

Paid plans exist for the keyed services but are not needed for the MVP. RapidAPI was considered as a single-key aggregator and rejected for now (each API is priced separately, not cheaper at scale; possible overage charges). The GitHub list `public-apis/public-apis` can be used to discover more APIs later.

### 9.5 SerpApi services (additional)
SerpApi gives access to Google and marketplace search results through **one API key**. These services are **added on top of** the 10 direct APIs; they do not replace them.

- **Account:** the project owner's existing SerpApi account, with plenty of credits. One platform key in a server environment variable (`SERPAPI_API_KEY`).
- **Credit usage:** every SerpApi tool call from every user spends the owner's credits. **For the MVP this is accepted** — no per-user limits on SerpApi calls. Revisit before scaling.
- **Each service has its own module** (e.g. `tools/apis/serpapi/google_maps.py`) behind our own tool functions, so a provider can be swapped later by changing one file.
- **Not used from SerpApi:** web search (Tavily is used), flights (AviationStack is used), news (NewsData.io is used), stocks (Finnhub is used).

| # | SerpApi service (engine) | Purpose | Notes |
|---|---|---|---|
| 11 | Google Maps (`google_maps`) | Find places, businesses and local results (rating, address, hours, phone) | Returns a `data_id` / place ID used by the reviews tool. OpenRouteService stays for directions. |
| 12 | Google Maps Reviews (`google_maps_reviews`) | Reviews for a place found with Google Maps | Needs the place's `data_id` from tool 11; return only the top few reviews. |
| 13 | Google Shopping (`google_shopping`) | Product search and price comparison across stores | Return title, price, store, rating, link. |
| 14 | Google Hotels (`google_hotels`) | Hotel search by location and dates | Needs check-in / check-out dates; pairs with `get_current_datetime`. |
| 15 | YouTube Search (`youtube`) | Find videos (tutorials, reviews, channels) | Return title, channel, duration, views, link. |
| 16 | Amazon Search (`amazon`) | Amazon product search, prices, ratings | Amazon marketplace/domain is a parameter (default amazon.com). |

Verify the exact engine names, parameters and response fields in SerpApi's docs before building, and confirm SerpApi's terms for commercial use before launch.

### 9.6 Suggested tool names (adjust as needed)
**Direct APIs and built-ins:** `get_current_weather`, `get_weather_forecast`, `web_search`, `search_wikipedia`, `get_wikipedia_summary`, `convert_currency`, `get_exchange_rates`, `get_flight_status`, `get_stock_quote`, `get_company_news`, `get_latest_news`, `get_public_holidays`, `get_country_info`, `get_route_directions`, `geocode_place`, `calculator`, `get_current_datetime`, `search_knowledge_base`.

**SerpApi:** `search_places`, `get_place_reviews`, `search_products`, `search_hotels`, `search_youtube_videos`, `search_amazon_products`.

---

## 10. Composio Integration (Plugins)

### 10.1 What Composio does
Composio handles OAuth login, token storage and token refresh for third-party apps, and exposes each app's actions as tools. We never handle the users' app tokens. Chosen because it has the largest app catalog and native LangChain/LangGraph support, and we don't want to build auth flows for every app. (Nango self-hosted was the only freer alternative and was rejected because of the maintenance burden.)

### 10.2 Platform setup
- One **Composio API key** for the whole platform, stored in a server environment variable (never per user, never sent to the frontend).
- Each of our users maps to a Composio user ID = **our `user_id`**, so connections are separated per user.
- For each app, create **two auth configs** in Composio: **read-only scopes** and **read-write scopes**.

### 10.3 Connect flow (one time per app per agent)
1. User clicks an app (e.g. GitHub) and chooses **Read only** or **Read & write**.
2. Backend asks Composio for a connection link using the matching auth config.
3. User logs into GitHub and approves the scopes.
4. GitHub/Composio redirects to **our callback URL**.
5. We receive a **connected account ID**.
6. We store it in `agent_integrations`, **scoped to `user_id` and `agent_id`**, with app name, access level, scopes and `status = active`.
7. User ticks which actions of that app the agent may use → saved in `agent_tools` with `source = composio` and `access = read|write`.

Switching an app between read-only and read-write requires reconnecting with the other auth config.

### 10.4 Connected account ID facts
- The connected account ID is **permanent**. Composio never regenerates it.
- The **tokens behind it** expire, but Composio **refreshes them automatically**.
- A new ID only appears if the user fully reconnects after a permanent failure; then **overwrite the old ID** in our table.

### 10.5 Runtime (tool call)
1. Agent decides to use a GitHub action.
2. **Our backend looks up the connected account ID** for that agent + app from Postgres. **The LLM never chooses or sees the account ID** — so an agent can only use its own owner's connections.
3. If the action is a write → approval step (§11).
4. Backend calls Composio with the action, parameters and connected account ID.
5. Composio calls GitHub with the stored token and returns the result.
6. Result goes back to the agent, which replies to the user.
7. Log a PostHog event **after** the result returns (success/failure, duration).

### 10.6 Error handling
- **401 / 403 (authentication error) or Composio marks the connection expired:** mark `agent_integrations.status = expired`, emit a `reconnect_required` event to the chat UI, and show a **Reconnect** button that runs the same connect flow again. The agent also tells the user to reconnect.
- **404 (not found, e.g. repo name doesn't exist):** the connection is fine. **No reconnect.** The tool returns a clear message (e.g. *"No repository named my-app found"*) to the agent, which replies naturally.
- **200 with empty result (e.g. empty repo list):** returned to the agent normally; agent replies *"No repositories found."*
- No need to check connection status before every call — handle failures when they happen. Optionally check status when the user opens the agent's dashboard.

### 10.7 Layers of control (important)
1. **Scopes (Composio + the app):** what the token is *able* to do. Set by the auth config the user picked (read-only or read-write).
2. **Enabled actions (our app):** which Composio tools are loaded into each agent (`agent_tools`).
3. **Approval (our app):** whether each write action runs *this time* (§11).

If an action isn't enabled and the user asks for it, the agent simply doesn't have that tool and replies e.g. *"I don't have permission to create repositories."*

---

## 11. Write Actions and Approval (Human-in-the-Loop)

- Agents **can take actions** (e.g. create a GitHub repo, send an email) when the user enabled read-write access and the action.
- **Every write action requires approval in the chat** before it runs.
- Implementation: LangGraph `interrupt()` in the tool step for any tool flagged `write`.
  1. The graph pauses and the backend streams an `approval_required` SSE event with the action and arguments.
  2. Chat UI shows a card: *"Create repo `my-app` (private)? Approve / Reject"*.
  3. User taps a button → frontend calls the approval endpoint → graph resumes.
  4. **Approve** → the action runs via Composio → result to agent.
  5. **Reject** → the tool returns *"User declined this action"* to the agent, which replies accordingly.
- Requires the **LangGraph Postgres checkpointer** (thread ID = session ID) to pause and resume. The same checkpointer stores conversation state.
- Why: protects against the LLM misreading a request (wrong action, wrong name) and against **prompt injection** (e.g. a knowledge-base document or an email containing hidden instructions).
- **Destructive actions** (delete repo, delete email/file) are **excluded from the MVP**.
- Log every approval decision to PostHog (approved/rejected).
- Diagram: a decision diamond "Write action?" on the tool-call line between the Plugins box and Composio. No → straight to Composio. Yes → Approve/Reject → Approve to Composio, Reject back to Agent.

---

## 12. Chat Runtime, Sessions and Memory

### 12.1 Sessions
- A **session** = one conversation between the user and one agent. (Session ID and conversation ID are the same thing; the project uses the name **session ID**.)
- Scoped to `agent_id` + `user_id`. A user can have many sessions with the same agent (like separate chats).
- Backend checks that the session belongs to the requesting user before loading it.
- Session ID is used to: load the right chat history, tag analytics events, debug a specific conversation, and as the LangGraph checkpointer thread ID.

### 12.2 What is stored per session
- **All raw messages** (user, assistant, tool) in the `messages` table — permanent record for history, debugging and evals.
- A **summary** of the session (**50–100 words**) in `sessions.summary`, generated by a small, cheap LLM. Updated periodically (e.g. every N messages and/or when the session goes inactive). Per the original plan, this small model runs on the platform's side; alternatively it can use the user's own key with a cheap model.
- The summary keeps the context window small; the raw messages are never replaced by it.

### 12.3 Request flow for one chat message
1. `POST /sessions/{id}/chat` with the user's message (JWT in header).
2. Verify user → verify the session and agent belong to the user → check the user has an API key for the agent's provider.
3. Load agent config: system prompt, provider/model, KB settings.
4. Load **enabled tools**: API/built-in tools from the registry, KB tool if enabled, Composio tools for enabled actions (with backend-held connected account IDs).
5. Build context: system prompt + session summary + recent messages + new message.
6. Run the LangGraph loop: agent node → (tool node → agent node)* → final answer. Write tools go through `interrupt()`.
7. Stream events to the frontend over **SSE**.
8. Save user and assistant messages; update the summary when due.
9. Send PostHog events.

### 12.4 SSE event types (suggested)
`token` (text chunk), `tool_start`, `tool_end`, `sources` (citations), `approval_required`, `reconnect_required`, `error`, `done`.

### 12.5 Transport decision
HTTP POST with **SSE streaming** for chat (industry standard, stateless, simple). WebSockets were considered and not needed for the MVP. Webhooks are not for chat replies (only for future async events like "document indexed").

---

## 13. Analytics

### 13.1 PostHog (user-facing)
- PostHog alone is used for analytics in the MVP (no billing, so no Postgres usage ledger yet).
- **We send events ourselves** from the backend — Composio and the APIs don't send them.
- Send tool-call events **after the result returns** (so success, error and duration are known).
- Every event includes consistent properties: `user_id`, `agent_id`, `session_id`, `event_type`, plus event-specific fields.
- No counters stored in Postgres; PostHog counts events.

Suggested events:
| Event | Key properties |
|---|---|
| `session_started` | agent_id, session_id |
| `message_sent` | agent_id, session_id |
| `tool_called` | tool_name, tool_type (`api` / `composio` / `knowledge_base` / `builtin`), app (for Composio), success, duration_ms, error_type |
| `knowledge_base_searched` | search_mode, results_count, top_score |
| `write_action_decision` | tool_name, decision (`approved` / `rejected`) |
| `connection_expired` | app |
| `document_ingested` | source_type, chunk_count, status |

- The Analytics page is served by **our backend**, which queries PostHog server-side (e.g. via its query API) filtered to the requesting user's agent.
- **LLM token analytics: skipped for the MVP.** (Possible later: the LLM call passes through our backend, and responses include token counts, so we could log model + tokens per call to show users their own quota usage.)

### 13.2 LangSmith (developer-only)
Used by the project team to trace agent runs, debug tool selection, and run RAG/agent evaluations. Not shown to users. Keep API keys out of traces.

---

## 14. Database Design (PostgreSQL + pgvector)

General rules:
- **One table per entity, never a table per user.** Ownership is a `user_id` column.
- Don't store derived counts (e.g. number of agents); count with queries.
- Every query is scoped by `user_id` so users can never see other users' agents, sessions, documents or analytics.
- Use `ON DELETE CASCADE` from agents to their children.

### `users`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | = Supabase user ID |
| email | text unique | |
| name | text | |
| avatar_url | text | |
| created_at | timestamptz | |
| last_login_at | timestamptz | |

### `llm_keys`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → users | |
| provider | text | `gemini` / `openai` |
| encrypted_key | text | encrypted at rest |
| key_hint | text | last 4 chars for display |
| created_at, updated_at | timestamptz | |
| | | unique(user_id, provider) |

### `agents`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| user_id | uuid FK → users | owner |
| name, description | text | |
| persona_key | text null | predefined persona chosen (null if fully custom) |
| custom_prompt | text null | user's custom instructions |
| system_prompt | text | final compiled prompt |
| llm_provider | text | `gemini` / `openai` |
| llm_model | text | |
| kb_enabled | boolean | |
| search_mode | text | `semantic` / `keyword` / `hybrid` (default) |
| status | text | `draft` / `live` |
| created_at, updated_at | timestamptz | |

### `agent_tools`
One row per enabled tool per agent.
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| agent_id | uuid FK → agents | |
| tool_name | text | registry name or Composio action name |
| source | text | `builtin` / `api` / `composio` / `knowledge_base` |
| app | text null | for Composio tools, e.g. `github` |
| access | text | `read` / `write` |
| enabled | boolean | |
| created_at | timestamptz | |
| | | unique(agent_id, tool_name) |

### `agent_integrations`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| agent_id | uuid FK → agents | |
| user_id | uuid FK → users | |
| app | text | `github`, `gmail`, `googledrive`, `notion`, … |
| composio_connected_account_id | text | permanent handle; **never the tokens** |
| access_level | text | `read_only` / `read_write` |
| scopes | text[] | |
| status | text | `pending` / `active` / `expired` |
| created_at, updated_at | timestamptz | |

### `documents`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| agent_id | uuid FK → agents | |
| user_id | uuid FK → users | |
| filename | text | or a title for pasted text |
| source_type | text | `paste` / `txt` / `md` / `pdf` |
| status | text | `pending` / `processing` / `ready` / `failed` |
| error | text null | |
| content_hash | text | duplicate detection |
| chunk_count | int | |
| embedding_model | text | locked model name |
| created_at | timestamptz | |

### `document_chunks`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| document_id | uuid FK → documents | |
| agent_id | uuid | for filtering |
| user_id | uuid | |
| chunk_index | int | |
| content | text | includes contextual header |
| metadata | jsonb | document name, page, section |
| embedding | vector(dim) | dim depends on the Gemini model |
| tsv | tsvector | for keyword search |
| created_at | timestamptz | |

Indexes: HNSW on `embedding`, GIN on `tsv`, B-tree on `agent_id`.

### `sessions`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | session ID (also LangGraph thread ID) |
| agent_id | uuid FK → agents | |
| user_id | uuid FK → users | |
| title | text | |
| summary | text | 50–100 word summary |
| summary_updated_at | timestamptz | |
| created_at, last_message_at | timestamptz | |

### `messages`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| session_id | uuid FK → sessions | |
| role | text | `user` / `assistant` / `tool` |
| content | text | |
| tool_calls | jsonb null | tool name, args, result summary |
| created_at | timestamptz | |

### LangGraph checkpoint tables
Created by the LangGraph Postgres checkpointer. `thread_id` = `sessions.id`.

### Personas
Static data in code (not a table) for the MVP.

---

## 15. REST API (suggested)

All endpoints require the Supabase JWT and are scoped to the current user.

| Method | Path | Purpose |
|---|---|---|
| GET | `/me` | Current user (upserts on first call) |
| GET | `/personas` | Predefined personas |
| GET | `/llm-keys` | Saved providers with key hints |
| PUT | `/llm-keys/{provider}` | Save/replace a key (validated) |
| DELETE | `/llm-keys/{provider}` | Remove a key |
| GET / POST | `/agents` | List / create agents |
| GET / PATCH / DELETE | `/agents/{agent_id}` | Read / update / delete an agent |
| POST | `/agents/{agent_id}/deploy` | Set status `live` |
| GET | `/tools` | Catalog of built-in + API tools |
| PUT | `/agents/{agent_id}/tools` | Set enabled tools/actions |
| POST | `/agents/{agent_id}/documents` | Upload file or pasted text |
| GET | `/agents/{agent_id}/documents` | List documents + status |
| DELETE | `/agents/{agent_id}/documents/{doc_id}` | Delete document + chunks |
| GET | `/integrations/apps` | Composio apps available |
| POST | `/agents/{agent_id}/integrations/{app}/connect` | Body: access level → returns redirect URL |
| GET | `/integrations/callback` | OAuth callback → store connected account ID |
| GET | `/agents/{agent_id}/integrations` | List connections + status |
| GET | `/agents/{agent_id}/integrations/{app}/actions` | Available actions to enable |
| POST | `/agents/{agent_id}/integrations/{app}/reconnect` | New redirect URL |
| DELETE | `/agents/{agent_id}/integrations/{app}` | Disconnect |
| GET / POST | `/agents/{agent_id}/sessions` | List / create sessions |
| GET | `/sessions/{session_id}/messages` | Message history |
| DELETE | `/sessions/{session_id}` | Delete session |
| POST | `/sessions/{session_id}/chat` | Send message, **SSE stream** response |
| POST | `/sessions/{session_id}/approval` | Body: `{approved: true/false}` → resume graph |
| GET | `/agents/{agent_id}/analytics?range=` | Analytics from PostHog (server-side) |

---

## 16. Security Checklist
- Verify the Supabase JWT on every request; derive `user_id` only from the token.
- Scope every query by `user_id`; verify agent/session ownership before any action.
- Encrypt LLM keys at rest; never return or log them; keep them out of traces.
- Composio API key and all third-party API keys only in server environment variables.
- Never store app OAuth tokens — only Composio connected account IDs.
- The backend selects connected account IDs; the LLM never does.
- Vector search always filtered by `agent_id`.
- Approval required for every write action; no destructive actions in the MVP.
- Treat knowledge-base content and tool results as untrusted (prompt-injection risk).
- Timeouts on all external calls; trim tool outputs.
- Basic rate limiting on chat and upload endpoints; restrict CORS to the frontend origin.

---

## 17. Suggested Project Structure

```
backend/
  app/
    main.py                 # FastAPI app, CORS, routers
    core/                   # config (env), security (JWT verify), encryption
    db/                     # SQLAlchemy/SQLModel models, migrations (Alembic)
    api/                    # routers: agents, keys, documents, integrations, sessions, chat, analytics
    agent/
      graph.py              # LangGraph: agent node, tool node, interrupt for write tools
      context.py            # system prompt + summary + recent messages
      summarizer.py         # session summaries
      personas.py           # predefined persona templates
    tools/
      registry.py           # {name: tool} with read/write flags
      builtin.py            # calculator, datetime
      apis/                 # open_meteo.py, tavily.py, wikipedia.py, ... (one file per service)
      knowledge_base.py     # search_knowledge_base tool
    rag/
      ingest.py             # extract, split, embed, store
      retrieve.py           # query rewrite, hybrid search, RRF, rerank, threshold
    integrations/
      composio_client.py    # connect links, callback, load tools, execute actions, error mapping
    analytics/
      posthog_client.py     # capture events, query for analytics page
frontend/
  src/
    pages/                  # CreateAgent (wizard), Chat, Analytics
    components/             # ApprovalCard, ReconnectButton, ToolActivity, Sources, ...
    lib/                    # supabase client, api client, SSE handling
```

---

## 18. Build Order
1. **Auth:** Supabase Google login → FastAPI JWT verification → user upsert.
2. **Agent creation & config:** agents CRUD, personas, system prompt, deploy.
3. **Chat with the user's LLM key:** key storage/encryption, LangGraph agent, sessions, messages, SSE streaming, summaries.
4. **Tools:** registry, built-in tools, the 10 API services, enabled-tools loading.
5. **RAG:** ingestion, pgvector, hybrid search, re-ranking, KB tool, citations, LangSmith evals.
6. **Composio:** connect flow, callback, actions selection, runtime execution, error handling, reconnect.
7. **Write-action approval:** read/write flags, `interrupt()`, Postgres checkpointer, Approve/Reject UI.
8. **Analytics:** PostHog events everywhere, analytics page.

---

## 19. Future Scope (after the MVP)
- **Public developer API:** use agents from external projects via REST + SSE, platform API keys, `end_user_id` so each of the developer's users has separate sessions/memory, embeddable chat widget.
- **Webhooks** for async events (document indexed, long run finished, connection expired).
- **Billing:** credits per tool call / RAG query / Composio call, with a `usage_events` ledger in Postgres as the source of truth (PostHog stays for insight only, since it can drop or delay events).
- **MCP:** agents as MCP clients (custom MCP server URLs) and/or agents exposed as MCP servers.
- Multi-agent workflows (and possibly a drag-and-drop canvas builder).
- More LLM providers and account/subscription-based connections.
- Images, scanned PDFs (OCR / vision models).
- More API tools; LLM token-usage analytics.
- Destructive actions with stronger safeguards.
- Hosting/deployment; paid plan for Open-Meteo (commercial use) and review of every API's commercial terms.

---

## 20. Things to Verify Before/While Building
- Exact Gemini embedding model ID and its vector dimension.
- Current free-tier limits and commercial terms of all 10 API services.
- Current Composio SDK methods for: creating auth configs with custom scopes, generating connection links, fetching LangChain-compatible tools for specific actions, executing actions with a connected account ID, and connection status values.
- Current LangGraph APIs for `interrupt()` / resume and the Postgres checkpointer.
- Supabase JWT verification method (JWT secret vs JWKS) for the project.

---

## 21. Key Decisions Log
| Decision | Reason |
|---|---|
| Agent-as-a-Service, in-app chat only for MVP | Ship the core experience first; public API later |
| BYOK (Gemini + OpenAI) | No LLM costs for the platform |
| FastAPI + REST | Python ecosystem for LangChain/LangGraph; REST is the API style, FastAPI the framework |
| SSE for chat | Standard for streamed LLM replies; simpler than WebSockets |
| Supabase Auth only for login | Easy Google sign-in; core data stays in our own Postgres |
| pgvector over Pinecone/Qdrant | One database, easy per-agent filtering, cascade deletes, keyword + vector search in one place, free |
| Hybrid search default | Catches exact terms embeddings miss |
| Retrieval as a tool | Avoid searching on small talk |
| Raw messages + 50–100 word summary | Full record for history/debugging/evals; summary keeps context small |
| One persona per agent, compiled into system prompt | Predictable, editable behavior |
| Tools layer with registry, one tool per action | Clear for the LLM; only enabled tools loaded |
| Composio for app connections | No custom OAuth per app; permanent account IDs; automatic token refresh |
| Read-only vs read-write chosen at connect time | User controls what the token can do |
| Approval for every write action | Guards against LLM mistakes and prompt injection |
| PostHog for user analytics, LangSmith internal | Product analytics vs developer tracing/evals |
| No billing, MCP or multi-agent in MVP | Keep scope small |
| Text, .txt, .md, text-based PDF only | Avoid OCR/vision complexity in MVP |
