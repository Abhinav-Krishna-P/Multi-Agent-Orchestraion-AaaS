# Multi-Agent Orchestration (AaaS)

Build your own AI agents, give them knowledge and tools, connect them to your apps, let them work on a
schedule, and call them from your own code.

An agent is a persona, a model and a set of tools. You chat with it in the browser, it can search your
documents, call outside services, and act in apps like Gmail or GitHub (asking you first before it changes
anything). Automations run an agent on their own, and the Agent API lets any project use an agent with
one HTTP call.

## Features

- **Agents** — a wizard to pick a persona, a Gemini model, knowledge, tools and apps; draft, live and stopped states.
- **Bring your own key** — each user adds their own LLM API key, stored encrypted (Fernet).
- **Streaming chat** — replies stream over SSE, with retry, partial saves and automatic chat summaries.
- **Knowledge base** — upload documents; hybrid search (BM25 + vector, merged with RRF) on Chroma, with sources in every answer. Chunking and the similarity cut-off were tuned with LangSmith evaluations.
- **Tools** — calculator, clock, weather, currency, stocks, web, news, image, places, books and flight search, shown as result cards in the chat.
- **App connections** — Gmail, GitHub, Calendar and more through Composio. Read actions run directly; write actions show an approval card first. Broken connections are detected and fixed with a Reconnect button.
- **Automations** — describe a job in plain English; the agent proposes it, you approve it. Runs on a schedule (cron), on an app event (webhook) or when new items appear (polling), and pauses itself after repeated failures.
- **Agent API** — a secret key per agent and `POST /v1/run`: text in, JSON out. Rate limited, every call logged, ready-made samples in 9 languages, plus Python and TypeScript packages.
- **Analytics** — chat, automation and API usage per agent, from PostHog.
- **Shared cache** — Redis caches service replies, searches, embeddings and repeated model steps; falls back to memory when Redis is off.

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python 3.13, FastAPI, async SQLAlchemy, Alembic, LangGraph, LangChain (Gemini) |
| Data | PostgreSQL, Chroma (vectors), Redis (cache and rate limits) |
| Frontend | React 19, Vite, Tailwind CSS v4, shadcn/ui, TanStack Query |
| Services | Supabase (Google sign-in), Composio (apps), PostHog (analytics), LangSmith (evaluation), SerpAPI / Serper / Finnhub / Open-Meteo / Frankfurter (tools) |

## How it fits together

```
Browser (React) ──► FastAPI ──► LangGraph agent ──► Gemini (user's own key)
                       │              ├── knowledge base ── Chroma
                       │              ├── service tools ─── SerpAPI, Serper, Finnhub, ...
                       │              └── app actions ───── Composio (Gmail, GitHub, ...)
                       ├── PostgreSQL (users, agents, chats, automations, API keys, call log)
                       ├── Redis (shared cache, API rate limits)
                       └── PostHog (usage events)

Your code ──► POST /v1/run (agent API key) ──► same agent, unattended
Scheduler / Composio webhook ──► automations ──► same agent, unattended
```

## Project layout

```
backend/        FastAPI app, agent graph, tools, integrations, automations, Alembic migrations, tests
  app/api/          HTTP routes (agents, chat, knowledge, apps, automations, analytics, agent API)
  app/agent/        LangGraph graph, tool loop, unattended runs
  app/rag/          document ingest, chunking, hybrid search
  app/tools/        built-in and outside-service tools
  app/integrations/ Composio client
  app/automations/  scheduler, triggers, runs
  evals/            LangSmith evaluations
frontend/       React app (pages, components, query hooks)
sdk/python/     `agentplatform` Python package for the Agent API
sdk/typescript/ `agentplatform` TypeScript package for the Agent API
docs/           guides, design docs and plans
```

## Getting started

### Requirements

- Python 3.13 and Node.js 20+
- PostgreSQL (one database for the app, one for tests)
- A Supabase project with Google sign-in
- Optional: Chroma (knowledge base), Redis 5+ (shared cache), Composio, PostHog, LangSmith and the tool API keys

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env              # then fill in the values
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

The startup log prints `Cache: redis` or `Cache: memory`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env              # then fill in the values
npm run dev                       # http://localhost:5173
```

### Configuration

Secrets live only in the `.env` files, which are never committed. The main settings:

| Variable | What it is for |
|---|---|
| `DATABASE_URL`, `TEST_DATABASE_URL` | PostgreSQL for the app and for tests |
| `SUPABASE_URL`, `SUPABASE_JWT_SECRET` | verifying sign-in tokens |
| `FERNET_MASTER_KEY` | encrypting users' LLM keys |
| `PLATFORM_GEMINI_API_KEY`, `SUMMARY_MODEL` | chat summaries and embeddings |
| `CHROMA_URL`, `CHROMA_TOKEN`, `EMBEDDING_MODEL` | knowledge base |
| `REDIS_URL` | shared cache (use `127.0.0.1`, not `localhost`, on Windows) |
| `COMPOSIO_API_KEY`, `COMPOSIO_WEBHOOK_SECRET`, `COMPOSIO_WEBHOOK_ID` | app connections and event automations |
| `POSTHOG_API_KEY`, `POSTHOG_PROJECT_ID`, `POSTHOG_PERSONAL_API_KEY` | analytics |
| `SERPAPI_API_KEY`, `SERPER_API_KEY`, `FINNHUB_API_KEY` | outside-service tools |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | tracing and evaluations |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_API_URL` | frontend |

## Using an agent from your code

Create a key on the **API** page (it is shown once), then:

```bash
curl -X POST http://localhost:8000/v1/run \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Summarise the latest issues in my repo"}'
```

```python
import os
from agentplatform import Agent

agent = Agent(api_key=os.environ["AGENT_API_KEY"], base_url="http://localhost:8000")
result = agent.run("Summarise the latest issues in my repo")
print(result["reply"])
```

The response holds `reply`, `sources`, `tools_used` and `duration_ms`. Errors come back as
`{"detail": {"code", "message"}}` with codes such as `invalid_api_key`, `rate_limited` and `agent_not_live`.
Full reference: [docs/agent-api.md](docs/agent-api.md).

## Tests

```bash
cd backend && pytest                       # uses TEST_DATABASE_URL
cd frontend && npm run lint && npm run build
cd sdk/python && python -m pytest
cd sdk/typescript && npm test
```

## More docs

- [Agent API](docs/agent-api.md)
- [Shared cache (Redis)](docs/redis-cache.md)
- [Automations on your own computer](docs/automations-local-setup.md)
- Design docs and plans: [docs/superpowers](docs/superpowers)

## License

Private project. All rights reserved.
