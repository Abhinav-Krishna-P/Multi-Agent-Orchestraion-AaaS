# Reconnect Design — finishing spec §10.6 (broken app connections)

Date: 2026-11-20
Status: approved by the owner in chat ("yes", to the four gaps listed on 2026-11-20)

## What exists

A failed app action asks Composio about the connection. If it is broken, the row is marked `expired`, the agent is told to ask for a reconnect, the Apps step shows "Reconnect needed" with a Reconnect button, and the app's actions stop being offered.

## The four gaps, and the fix for each

1. **No Reconnect in the chat.** The chat page shows a bar above the message box for each of the agent's broken apps: logo, "Gmail needs reconnecting", **Reconnect**. It uses the same sign-in window flow as the Apps step (moved into one shared hook). The page refreshes the agent's app list after every reply, so a connection that broke during a reply shows its bar straight away.
   - Approach chosen: a bar tied to the app's state, not a button saved on one message (the spec's `reconnect_required` event). It stays visible until the app is fixed, works after a reload, and needs no new column. Rejected: a per-message button, which would go stale once the app is reconnected and would need a migration.
2. **The agent forgets on later messages.** While any of the agent's apps is broken, its instructions say which ones and tell it to point the user to Reconnect instead of claiming it has no access.
3. **No check on opening.** `POST /agents/{id}/integrations/check` asks Composio about each of the agent's connections at once (5-second limit overall), saves what changed, and returns the app list. The Apps step and the chat page call it once when they open.
4. **A connection deleted at Composio stays "Connected".** A 404 from a service becomes its own error type. For a connection lookup it means `expired`. Elsewhere it reads as before ("could not be reached right now"), but for running an action it counts as a definite failure, not "may have been done".

## Not in scope

PostHog `connection_expired` events (Part C), and email or other notifications about broken connections.

## Tasks

1. **Backend, test-first.**
   - `http.NotFound`: 404 raised with the usual "could not be reached" text.
   - `connection_status`: `NotFound` → `expired`.
   - The `check` endpoint: owner only; Composio slow or down leaves statuses unchanged.
   - Instruction `registry.reconnect_instruction(names)`, added in chat when the agent has expired apps.
   - The test stand-in may return any HTTP status.
2. **Frontend.**
   - Shared hook `useAppSignIn(agentId, apps)` (window, message, focus and refresh logic moved from `Apps.jsx`).
   - `ReconnectBar` on the chat page.
   - Check on open in both places.
   - Refresh the integrations query after each reply.
3. **Verify.** Full suite, build and lint. A live look: revoke Composio's access in the owner's Google account, ask the agent about mail, and see the bar; Reconnect fixes it.
