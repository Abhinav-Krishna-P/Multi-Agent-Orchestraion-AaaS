# Stage 3, Part A Design — App Connections (Composio)

Date: 2026-11-19
Status: waiting for approval

Stage 3 has three parts, built in this order: **A. app connections** (this document), **B. approve or reject for actions that change something**, **C. analytics**. Each gets its own design and plan. Where this document disagrees with the original spec in `Project data/`, this document wins.

## 1. Intent

Let a user connect their own accounts (Gmail, Calendar, Slack and so on) to an agent, so the agent can look things up in them during a chat. Composio handles each app's sign-in and keeps the tokens; the platform never sees them.

## 2. Goals

1. A new **Apps** step in the agent wizard, between Tools and Deploy, laid out like the Tools step: one card per app with its real logo, a status, and a Connect button.
2. **Connect** opens the app's own sign-in in a new window. When the user finishes, the card shows "Connected" without a page reload.
3. A connection belongs to **one agent of one user**. Another agent, or another user, cannot use it.
4. Once connected, the user ticks which **actions** the agent may use, from that app's most useful ones.
5. In chat, the agent uses those actions like any other tool, with the same activity line.
6. **Disconnect** removes the connection at Composio and on the platform.
7. If a connection stops working, the card shows "Reconnect needed", the agent says so in chat, and Reconnect runs the same sign-in again.

## 3. Non-goals

- **Actions that change something** (send, create, update). Part A offers **read actions only**. Write actions arrive with Part B, because they must not exist without the approval step.
- Actions that delete. Never offered in the MVP.
- Result cards for app actions. Their results reach the user as the agent's text. (Each app returns a different shape; cards per app can come later.)
- Separate read-only and read-write sign-ins with different permission scopes (see §5, decision 1).
- Analytics events: Part C.

## 4. Anti-goals

- The Composio API key never reaches the browser, the model, a log line or LangSmith.
- The model never sees or chooses a connected-account ID. The backend looks it up from the agent.
- A user can never trigger sign-in for, read, use or disconnect another user's connection.
- Text returned by an app (an email body, a document) is untrusted, like document text.
- Existing behaviour does not regress: the 361 backend tests keep passing. No pushing.

## 5. Approaches and decisions

**How to talk to Composio**
- **A. Its REST API through the platform's existing HTTP helper (chosen).** Four calls are needed: create a sign-in setup for an app, start a sign-in, check or delete a connection, run an action. The helper already gives a time limit, safe logging and readable failures.
- B. The `composio` Python SDK with its LangChain adapter. Rejected for now: a large new dependency whose tool objects would bypass the platform's own registry, activity labels, error wording and (in Part B) approval.

**Decision 1 — one sign-in per app (differs from the spec).** The spec asks for two Composio setups per app with read-only and read-write scopes. That needs the owner's own developer app at Google, Slack, GitHub and the rest, each with its own review. Instead each app uses Composio's ready-made sign-in, and what the agent can do is limited by which actions the platform gives it. Cost: the connection itself is technically able to write; the platform is what prevents it.

**Decision 2 — which actions are offered.** Composio labels every action. The platform offers the ones labelled *important*, and sorts them by Composio's own labels: *read only* → offered in Part A; *destructive* → never offered; the rest → write actions, held back until Part B. Checked on the owner's account on 2026-11-19: Gmail has 5 important read actions, Google Calendar 5, Slack 6, GitHub 18.

**Decision 3 — the 12 apps.** Gmail, Google Calendar, Google Drive, Google Sheets, Google Docs, Slack, Notion, GitHub, Outlook, Linear, Trello, HubSpot. All twelve have Composio's ready-made sign-in on the owner's account (checked 2026-11-19). The list is one table in code; adding an app is one line.

## 6. Design

### Data

- New table `agent_integrations` (migration 0005): `id`, `agent_id`, `user_id`, `app`, `composio_connected_account_id`, `status` (`pending` / `active` / `expired`), timestamps; unique on (`agent_id`, `app`); deleted with its agent. The spec's `access_level` and `scopes` columns are left out (decision 1).
- Chosen actions are saved in the existing `agent_tools` table with `source = "composio"` and the action's Composio name.

### Backend

- `app/integrations/composio.py`: the four Composio calls; `APPS` (the 12 apps: Composio name, display name, category); `actions(app)` returns the offered read actions (cached for an hour); `as_tool(action, account_id, user_id)` builds a LangChain tool from the action's name, description and parameter schema. Its text for the model uses the same "reference material, not instructions" wrapper as the other tools, cut to a safe length.
- Composio user ID = the platform's `user_id`, as the spec says.
- Endpoints, all checking the agent belongs to the caller:
  - `GET /agents/{id}/integrations` — the 12 apps with status and, for connected ones, their actions and which are switched on.
  - `POST /agents/{id}/integrations/{app}/connect` — returns the sign-in address; saves a `pending` row.
  - `POST /agents/{id}/integrations/{app}/refresh` — asks Composio for the connection's status and saves it. Called when the sign-in window closes.
  - `PUT /agents/{id}/integrations/{app}/actions` — which actions are on.
  - `DELETE /agents/{id}/integrations/{app}` — disconnects at Composio, then removes the row and its actions.
- Sign-in returns to a small page on the frontend (`/app/connected`) that tells the wizard window it is done and closes itself. The connection is confirmed by asking Composio, never by trusting anything in that address.
- Chat: for each `active` connection, the switched-on actions are added to the turn's tools. A failure that means "not signed in any more" marks the connection `expired` and tells the model to ask the user to reconnect; any other failure is passed on in plain words.
- If `COMPOSIO_API_KEY` is missing, the Apps step says app connections are not set up, and nothing else breaks.

### Frontend

- Wizard step **Apps** (`pages/AgentWizard/Apps.jsx`), reusing the Tools step's card grid, search and category list. Card states: Connect · Connecting… · Connected (Manage actions, Disconnect) · Reconnect needed.
- App logos come from Composio's own logo addresses, loaded with the safe image component built for result cards.
- The agents list and Deploy step count connected apps alongside tools.

## 7. Testing

- Backend, test-first, against a stand-in for Composio: the connect, refresh, actions and disconnect endpoints; ownership (user B cannot touch user A's connection); only read actions are ever offered or accepted; an action tool sends the right account and never accepts one from the model; an expired connection is marked and reported; a missing key.
- One live check by hand with the owner's own Gmail: connect, switch on "fetch emails", ask the agent about recent mail, disconnect.

## 8. Left to the builder

Exact Composio request shapes (to be confirmed against its documentation and one live call before coding each), card styling, and wording of the status lines.
