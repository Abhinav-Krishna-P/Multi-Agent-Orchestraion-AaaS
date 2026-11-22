# Shared cache (Redis)

The backend keeps repeated work in one shared cache. With `REDIS_URL` set in `backend/.env` it uses
Redis; with it empty, each backend process keeps its own in-memory cache (what it did before). The startup
log says which: `Cache: redis` or `Cache: memory`.

```
REDIS_URL=redis://127.0.0.1:6379/0
```

Use `127.0.0.1`, not `localhost`: on Windows `localhost` tries IPv6 first, and a Redis that listens on IPv4
only makes every call wait for the 0.3 s timeout. Any Redis from 5.0 up works.

## What is cached

| What | Kept for | Fresh again when |
|---|---|---|
| Outside-service replies (weather, currency, search, stocks) | 10 minutes | it expires |
| Composio action and trigger lists | 6 hours | it expires |
| Analytics (each tab, range and time zone) | 60 seconds | it expires; a failed PostHog read is never kept |
| Knowledge-base search results, per agent | 1 hour | any document of that agent is added, deleted, or stops being ready |
| Question embeddings | 7 days | it expires |
| A chat reply's model step, per agent and model | 24 hours | the conversation, tools or model differ in any way |

Never cached: anything that does something (sending an email, creating an event), Composio connection
status, automation runs and the "describe your automation" chat. A chat reply's tools always run live; only
the model's own step is reused, and only when its whole input (the full conversation) was seen before.

## If Redis stops

Nothing breaks. A read counts as "not cached", a write is skipped, and Redis is left alone for 30 seconds
before the next try. The log shows one warning per outage.

## Looking inside

```
redis-cli INFO stats              # keyspace_hits / keyspace_misses
redis-cli --scan --pattern "cap:*"
```

Every key starts with `cap:` and has an expiry. Keys are hashes: they never hold a secret or the text of a
question.

## Privacy

Cached values include chat replies and document excerpts. A local Redis without a password is fine for
testing on your own computer. A deployed Redis needs a password and TLS (`rediss://user:password@host:port/0`).
