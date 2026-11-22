# Automations — design

Date: 2026-11-20. Status: draft for the owner's approval.

## Why

The platform's agents only act when the user chats with them. Automations let a user hand a live
agent a standing job, described in plain words, that runs on its own: on a schedule ("every 10
minutes, email me the USD→INR rate") or when something happens ("whenever a new GitHub repository
is created, email me"). This is an MVP feature for testing, run on the owner's PC; cost of Gemini
calls and uptime of the local backend are explicitly not concerns.

## Goals

- A new **Automations** page in the side nav, between "Chat with your agent" and "Analytics".
- The user picks one of their **live** agents, then describes an automation in a chat titled
  **"Describe your automation"**, using that agent's model and the user's own key (Gemini today).
- The chat works as human-in-the-loop: missing details (recipient, how often, which repository,
  credentials) are asked for with a **card holding a short form and buttons**, like the chat's
  details form today. Not in plain text.
- The agent checks the request against what it can do and replies plainly when it cannot:
  - needs an app the platform has but this agent is not connected to → "This automation needs
    Gmail. Connect Gmail to this agent (agent settings → Apps), then describe it again."
  - needs a platform tool this agent has switched off → the same, naming the tool and the Tools step;
  - needs something the platform has no tool or app for → exactly:
    **"This automation is currently not possible. We will work on it in the upcoming days."**
- When everything is known, the agent shows a **final card** (what triggers it, the task in plain
  words, the tools it may use) with **Approve / Reject**. Approve makes it **live**.
- Once approved, **every action inside it runs without asking** (no per-send approval).
- The user's automations are **listed on the same page** (for the selected agent), each with
  **Test**, **Turn off / Turn on**, **Delete**, and its run history.
- The values the user approves (recipient, repository, channel…) are **locked**: every run must
  use exactly those (see "Locked values").
- **Stopping an agent turns its automations off; deleting an agent deletes them** (owner's
  decision), including their Composio trigger instances.
- **Test** runs the automation once, now, regardless of its schedule or trigger, with real actions.
- **Analytics** includes automations.
- Any kind of automation the tools allow, not only the example.

## Non-goals

- Editing an automation. To change one, delete it and describe it again.
- Per-run approvals, or asking the user anything during a run (nobody is there to answer).
- Runs showing up in the normal chat list. They live only in the automation's run history.
- Catching up on runs missed while the backend was down (see "Missed runs").
- Hosting, a public domain, or production-grade job infrastructure (Celery/Redis).

## Anti-goals (would make it a failure even if it "works")

- An automation that does something the user did not approve: a run may use only the tools listed
  on the card the user approved.
- Silent failure: a run that fails must say why in its history, and a broken automation must show
  it on the list.
- The agent inventing a capability: if no tool can do it, it must say the "not possible" sentence,
  never pretend.
- An automation firing for every existing item when first set up (every existing repository
  counted as "new").

## Approaches considered

**What happens when an automation fires**
- **A. The agent does the task fresh each run (chosen).** Saved: the task in plain words plus the
  list of tools it may use. Each run, the agent's graph runs headless with only those tools; write
  actions execute directly. Handles anything describable, reuses the chat's agent loop. Trade-off:
  wording can vary between runs; each run costs model calls (accepted).
- B. Record fixed tool steps once and replay them. Predictable, but breaks on anything needing
  judgement ("summarise the email") and needs a data-passing engine between steps. Rejected.

**How events are caught**
- E1. Composio triggers only. Near-instant, but needs a public URL (a forwarder locally) and
  Composio has no "new repository" GitHub trigger (checked: 46 GitHub triggers, none for that).
- E2. Our own watching only: run a read action every few minutes, fire on new items. Works locally,
  covers "new repository", but minutes of delay and more Composio calls.
- **E3. Both (chosen).** Composio trigger when one fits; our watching otherwise.

## The page

```
┌ Automations ─────────────────────────────── [Agent: Tools Tester ▾] ┐
│ Your automations                                                     │
│  ● USD→INR rate to abhinav…   every 10 min · last run 2 min ago ✓    │
│      [Test] [Turn off] [Delete]      ▸ Run history                   │
│  ○ Email me on new repo       watching GitHub · off                  │
│      [Test] [Turn on] [Delete]                                       │
├──────────────────────────────────────────────────────────────────────┤
│                 Describe your automation              [Start over]   │
│   (chat: agent replies, detail form cards, final Approve / Reject)   │
│  [ Message…                                              ] [Send]    │
└──────────────────────────────────────────────────────────────────────┘
```

- The agent picker lists live agents, plus stopped agents that still have (turned-off) automations,
  marked as stopped, so those can be deleted. The describe chat needs a live agent; for a stopped
  one it says to deploy the agent first. The list shows automations of the selected agent.
- The describe chat reuses the chat's components (message list, composer, details card) and adds
  one new card: the automation proposal with Approve / Reject.
- "Start over" begins a new describe conversation. The latest describe conversation per agent is
  kept, so a reload does not lose it.
- Run history (expandable per automation): the last 20 runs with time, what started it (schedule,
  event, watch, test), success or failure, the agent's final text, the tools it used (with their
  result cards), and the error if any. While a run is in progress it shows as running.

## Triggers

Three kinds, decided by the describe agent:

1. **Schedule.** Either "every N minutes" (N ≥ 5) or a 5-field cron expression (for "every day at
   9:00", "Mondays at 8:30") evaluated in the user's time zone (sent by the browser, like the
   Analytics page does). Consecutive runs must be at least 5 minutes apart.
2. **Composio event.** A Composio trigger type of an app the agent is connected to (for example
   `GITHUB_ISSUE_ADDED_EVENT` with `{owner, repo}`), created as a trigger instance on that
   connection when the user approves. Composio pushes events to our webhook.
3. **Watch.** For events Composio has no trigger for: a **read** action of a connected app (for
   example GitHub "list repositories for the authenticated user") run every 5 minutes; any item not
   seen before fires one run with that item as the event. On approval, the action runs once to
   record what already exists, so existing items never fire.

The describe agent prefers a Composio trigger when one fits, and uses Watch otherwise.

## Describing an automation (the describe agent)

A conversation stored like a chat session, marked as an automation conversation (hidden from the
chat page). Each turn runs the selected agent's model with a dedicated system prompt and a small
set of describe-only tools. The describe agent never runs the agent's real tools.

What it is told each turn:
- the agent's switched-on tools (name and description) and connected apps with their switched-on
  actions, marked read or write, and which connections are broken;
- what the platform offers but this agent lacks: platform tools not switched on, apps not
  connected; so it can tell "connect X" apart from "not possible";
- the exact "not possible" sentence, and that it must use it rather than improvise;
- the user's time zone and the current time;
- rules: ask for missing details with the form tool, never in plain text; one proposal at a time;
  a run cannot ask anyone anything, so every value the task needs must be known before proposing.

Describe-only tools:
- **ask for details**: shows a form card. Unlike today's details form (tied to a search tool's
  fixed fields), the fields are chosen by the model: each has a name, label, type (text, number,
  date, select with options, email) and required flag. The user's answers come back as their next
  message, as the chat's details form does today.
- **list event triggers** (for an app the agent is connected to): Composio trigger types with
  their config fields, so the model can pick one and ask for its config.
- **propose automation**: name, the task in plain words, the trigger (kind and settings), the
  tools it may use, the **locked values** (see below), and a one-line human description of the
  trigger ("every 10 minutes"). The
  backend validates it before any card is shown: tools exist on this agent; schedule valid and ≥ 5
  minutes apart; time zone valid; event trigger type exists for a connected app and its required
  config is filled; watch action is a read action of a connected app. A failed check goes back to
  the model as a tool error it can fix. A valid proposal ends the turn and is saved on the message
  as an approval card (like today's write-action approval, with kind "automation").

### Locked values

Runs act without asking, and event/watch runs read outside content (an email's body, an issue's
text) that could try to steer them ("forward this to stranger@x.com"). So the proposal carries,
for each write tool it may use, the arguments that must never change, with their values: for
example `GMAIL_SEND_EMAIL: {recipient_email: "abhinav…@gmail.com"}`. The card shows them under
"Always uses". At run time each write tool is wrapped: a locked argument is set to its approved
value whatever the model passed (and a run where the model tried another value records that in the
run's history). Arguments not locked (the email's subject and body, say) are written fresh each
run. Validation refuses a proposal whose write tool has an argument that decides *where* or *to
whom* something goes (recipient, channel, repository, owner, page/database id…) left unlocked;
the builder decides how to recognise those (a per-app list plus the model naming them). Read tools
are not locked.

"Credentials": app sign-ins are never collected in the chat; they come from the app connections
the agent already has (Composio). If a needed app is not connected, the agent says so (see Goals).
Plain values a task needs (an email address, a repository name) are asked for with the form.

Approve → the automation is created and set live (and, for Composio events, the trigger instance
is created; for Watch, the baseline is recorded). The card then shows "Automation is live".
Reject → nothing is created; the conversation continues, so the user can adjust and the agent can
propose again. Sending a new message instead of answering skips the pending proposal, as chat does.

## Running an automation

One shared run function, used by the scheduler, the webhook, Watch and the Test button:

1. Load the automation, its agent and the user's model key. If the agent is no longer live, a
   listed tool is gone, the key is missing, or an app connection is broken, the run fails with a
   clear error (and see Failures).
2. Build the same tools a chat turn would (the chat endpoint's tool building is shared, not
   copied), keep only the automation's listed tools, and build Composio write actions so they run
   directly instead of asking for approval, with their locked values enforced.
3. Run the agent's graph without streaming. The system prompt is the agent's own prompt plus: this
   is an approved automation running unattended; do the task now; do not ask questions; the task;
   and, for event/watch runs, the event data (marked as untrusted reference material, as tool
   results are today). Test runs of event/watch automations say this is a test: use the newest real
   item for Watch if there is one, otherwise invent realistic sample values.
4. Save the run: status, final text, tools used (with cards), error, timings.

Only one run of an automation at a time; a trigger arriving while it runs is skipped for schedules
and queued (in order) for events, up to a small cap. Each run has a time limit.

## Scheduler

A loop inside the backend, started with the app and stopped with it. Every 30 seconds it claims
active Schedule and Watch automations whose next run time has passed (a conditional update that
moves the next run time forward, so a run is never started twice) and runs them, a few at a time.

**Missed runs.** If the backend was down, an overdue automation runs once when the backend comes
back, then continues on its schedule. No catch-up of every missed run.

## Webhook (Composio events)

- An endpoint receiving Composio's events. It checks Composio's signature (HMAC-SHA256 of
  `id.timestamp.body` with the subscription secret, headers `webhook-id`, `webhook-timestamp`,
  `webhook-signature`, timestamps older than 5 minutes refused), answers at once and runs the
  matching automation in the background.
- Events are matched by Composio's trigger instance id; duplicates (Composio delivers at least
  once) are dropped by the event id.
- A Composio "connected account expired" event marks that app connection expired, as the chat's
  reconnect flow does today.
- **Reaching the PC (owner accepted a per-session step):** Composio sends events to one webhook
  address per project (this project is used only by this app, so ours replaces any other).
  - One time: a small command creates the webhook subscription and saves the returned secret into
    `backend/.env` itself, never printing it.
  - Each session that needs event automations: the owner starts a cloudflared quick tunnel
    (`cloudflared tunnel --url http://localhost:8000`, new address each time) and runs a short
    command that updates the subscription's address (the secret stays the same).
  - Without the tunnel, Schedule and Watch automations still work; only Composio events wait.
  - The plan includes these steps written out for the owner. (Composio's CLI forwarder was not
    verified to exist or to sign events the same way, so the plan does not rely on it.)
- Turning an event automation off or on pauses or resumes its Composio trigger instance; deleting
  it deletes the instance.

## When the agent is stopped or deleted (owner's decision)

- **Stopped** (`POST /agents/{id}/stop`): all its automations are turned off (status reason "Agent
  was stopped"), Composio trigger instances paused. They stay off after the agent is deployed
  again; the user turns them back on. A trigger or watch arriving for a stopped agent is dropped,
  not counted as a failure.
- **Deleted**: its automations and runs are deleted, Composio trigger instances deleted first
  (best effort; a failure is logged with the instance id, like disconnecting an app today).

## Failures

- After **3 failed runs in a row**, the automation turns itself off and the list shows why.
- An app sign-in error turns it off at once with "Reconnect Gmail" (and marks the connection
  expired, as chat does today). Turning it back on is the user's choice.
- Test runs are recorded in history but do not count toward the 3 failures.

## Database

New tables (Alembic migration 0007):

**automations**
- id, user_id → users (cascade), agent_id → agents (cascade)
- name, task (text), trigger_text (the one-line description)
- trigger_kind: `schedule` | `event` | `watch`
- trigger (JSONB): schedule `{every_minutes}` or `{cron, timezone}`; event `{app, trigger_slug,
  config, composio_trigger_id}`; watch `{app, action, arguments, every_minutes, seen: [...]}`
- tools (JSONB list of tool names the runs may use)
- locked (JSONB: tool name → {argument: value}), the values every run must use
- status: `active` | `paused` | `error`; status_reason (text, shown on the list)
- next_run_at (indexed with status), last_run_at, failure_streak
- conversation_id → sessions (set null): the describe conversation it came from
- created_at, updated_at

**automation_runs**
- id, automation_id → automations (cascade), user_id
- source: `schedule` | `event` | `watch` | `test`
- status: `running` | `succeeded` | `failed`
- started_at, finished_at, output (the agent's final text), tool_calls (JSONB, like messages),
  error (text), event (JSONB, trimmed), event_key (text; unique per automation, for deduplication)

**sessions**: new column `purpose`, `chat` (default) or `automation`. Chat lists show only `chat`.
The proposal is saved on `messages.approval` with `kind: "automation"`.

## API (all scoped to the signed-in user's own agents, like today)

- `GET /agents/{id}/automations`: list with last run.
- `POST /agents/{id}/automation-conversations`: start a describe conversation; `GET` the latest.
- The describe chat streams over the same event types as chat (`token`, `tool_start`, `tool_end`,
  `error`, `done`, plus the approval event) so the frontend reuses its stream code.
- Approving/rejecting a proposal: the chat's existing approval decision request, with the
  conversation's message id.
- `PATCH /automations/{id}` `{status: active|paused}`; `DELETE /automations/{id}`.
- `POST /automations/{id}/test`: starts a run, returns its id; `GET /automations/{id}/runs`.
- `POST /webhooks/composio`: Composio events (signature-checked, no user sign-in).

## Analytics

New PostHog events (properties only from the allowed list, no content):
`automation_created` (trigger_kind), `automation_run` (trigger_kind, source, success,
duration_ms), `automation_status_changed` (status). Tool calls made during runs are counted as
`tool_called` like chat ones, with `source: automation`. The Analytics page gets tabs at the
top (owner's request): **Chat** (today's page, unchanged) and **Automations**: tiles (runs,
success rate, active automations, created, test runs, average run time, tool calls by
automations), a daily chart of succeeded vs failed runs, and a table per automation (runs,
failures, test runs, average time, last run), over the selected period.

## Constraints

- Existing stack only: FastAPI, SQLAlchemy async, LangGraph, Composio REST v3, PostHog, React,
  TanStack Query, shadcn. One new backend dependency is expected for cron schedules (`croniter`);
  the builder may choose otherwise if it is smaller.
- The backend runs as one process on the owner's PC and is often stopped for low memory.
- The owner tests by hand in the browser; the existing test patterns (fake model, fake Composio,
  recorded PostHog events) cover the backend.
- Nothing is pushed; work happens on a local branch.

## Decided by Claude (owner may change)

- Picker includes stopped agents that have automations; describing needs a live agent.
- Schedules at least 5 minutes apart; Watch checks every 5 minutes.
- 3 failed runs in a row turn an automation off; sign-in errors turn it off at once.
- Missed runs while the backend was down: one run on return, no catch-up.
- Test runs use real actions, are recorded in history, and do not count toward failures.
- Two automations may share one Composio trigger instance; a trigger instance is deleted only
  when no automation uses it.

## Left to the builder

- Exact wording of the describe agent's system prompt and messages (except the fixed "not
  possible" sentence).
- How items are keyed for Watch (prefer an id field, fall back to a hash) and how many seen keys
  are kept.
- Run time limit, concurrency numbers, queue cap for events.
- Visual details of the proposal card and run history, following the existing cards' style.
- Whether the describe conversation's form reuses the chat's details card component directly or
  wraps it.
