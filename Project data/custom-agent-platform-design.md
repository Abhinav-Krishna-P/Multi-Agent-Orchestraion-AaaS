# Custom Agent Platform — Frontend Design Specification (MVP)

> Companion to `custom-agent-platform-spec.md`. That file is the source of truth for features, backend, data and APIs. This file covers only how the frontend looks and behaves. Read both before building the UI.

---

## 1. Purpose and Approach

The MVP focuses on **core functionality first**: creating agents, chatting with them, and seeing analytics. The frontend is intentionally simple. It is built from a ready-made React component library and standard packages, with very little custom styling. A full visual redesign comes after the MVP.

Rules for the MVP frontend:
- Use library components as they are. Do not build custom design-system components.
- Every backend feature must be reachable and usable in the UI; polish is secondary.
- Every screen must handle four states: loading, empty, error, and normal.
- Keep copy short, plain and in sentence case.

---

## 2. App Structure

The app is a **single page application (SPA)** with two areas:

1. **Landing page** (public) — hero section with Google sign-in.
2. **App** (signed-in only) — a left navigation bar and three pages:
   - Create your agent
   - Chat with your agent
   - Analytics

### 2.1 Routes (client-side, React Router)
| Path | Screen | Access |
|---|---|---|
| `/` | Landing page (hero + Google sign-in) | Public. Signed-in users are redirected to `/app/agents`. |
| `/app/agents` | Create your agent — list of the user's agents | Signed in |
| `/app/agents/new` | Create agent wizard | Signed in |
| `/app/agents/:agentId` | Edit agent (same wizard, prefilled) | Signed in, owner only |
| `/app/chat` | Chat — pick an agent | Signed in |
| `/app/chat/:agentId/:sessionId?` | Chat with an agent, optional session | Signed in, owner only |
| `/app/analytics/:agentId?` | Analytics for one agent | Signed in, owner only |
| `/app/integrations/callback` | Return point after an app's OAuth login | Signed in |

Any `/app/*` route without a valid Supabase session redirects to `/`.

### 2.2 First-time flow
1. User lands on `/` → clicks **Continue with Google**.
2. After sign-in, frontend calls `GET /me` (upserts the user) → goes to `/app/agents`.
3. No agents yet → the empty state guides the user to **Create agent**.
4. After **Deploy**, the agent appears on the Chat and Analytics pages.

---

## 3. Tech and Packages

| Need | Package |
|---|---|
| Build tool | Vite + React (JavaScript) |
| Routing | `react-router-dom` |
| Components | `shadcn/ui` (built on Radix) + Tailwind CSS |
| Icons | `lucide-react` |
| Auth | `@supabase/supabase-js` (Google OAuth only) |
| Server data | `@tanstack/react-query` (fetching, caching, refetch) |
| Chat streaming (SSE) | `@microsoft/fetch-event-source` — needed because the chat endpoint is a **POST with an `Authorization` header**, which the browser's built-in `EventSource` cannot send |
| Markdown in replies | `react-markdown` + `remark-gfm` |
| File upload | `react-dropzone` |
| Charts | `recharts` |
| Toasts | `sonner` |
| Forms | `react-hook-form` + `zod` |

An admin/dashboard template built on shadcn/ui (sidebar + content layout) can be used as the starting point instead of building the shell from scratch.

---

## 4. Landing Page (Hero + Sign-in)

One screen, no scrolling sections needed for the MVP.

```
┌──────────────────────────────────────────────────────────────┐
│  [logo] Custom Agent Platform                                │
│                                                              │
│                                                              │
│        Build your own AI agent                               │
│                                                              │
│        Give it a personality, your documents, tools          │
│        and app connections. Chat with it using your          │
│        own Gemini or OpenAI key.                             │
│                                                              │
│        [ G  Continue with Google ]                           │
│                                                              │
│        Create an agent · Chat with it · See how it performs  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

- **Headline:** "Build your own AI agent"
- **Subtext:** "Give it a personality, your documents, tools and app connections. Chat with it using your own Gemini or OpenAI key."
- **Button:** "Continue with Google" — the only sign-in option. Google sign-in creates the account automatically, so there is no separate sign-up button.
- **Three short lines** under the button describing the three pages (can be simple text or three small icon + text items).
- Left-aligned content, vertically centered.

**States**
- While Supabase redirects: button shows a spinner and is disabled.
- Sign-in failed or cancelled: inline message under the button — "Google sign-in didn't finish. Try again."

---

## 5. App Shell (Signed In)

```
┌──────────────┬───────────────────────────────────────────────┐
│ [logo]       │                                               │
│              │                                               │
│ ▸ Create     │                                               │
│   your agent │             Page content                      │
│ ▸ Chat with  │                                               │
│   your agent │                                               │
│ ▸ Analytics  │                                               │
│              │                                               │
│              │                                               │
│──────────────│                                               │
│ (avatar) Name│                                               │
│  ⋯ menu      │                                               │
└──────────────┴───────────────────────────────────────────────┘
```

### 5.1 Left navigation bar
- Fixed width (~240px), full height.
- Three items with icons, highlighted when active:
  1. **Create your agent** (`Bot` icon) → `/app/agents`
  2. **Chat with your agent** (`MessageSquare` icon) → `/app/chat`
  3. **Analytics** (`BarChart3` icon) → `/app/analytics`
- **User menu at the bottom:** avatar + name from Google. Opens a menu with:
  - **API keys** — opens the API keys dialog (§5.2)
  - **Sign out**

### 5.2 API keys dialog
Managed here so it is reachable from any page (it is not a fourth page).

- One row per provider: **Gemini** and **OpenAI**.
- No key saved: input field + **Save key** button.
- Key saved: shows the hint only (e.g. `•••• a1b2`) + **Replace** and **Remove** buttons. The full key is never shown again.
- On save, the backend validates the key. Show a spinner, then either "Key saved" (toast) or an inline error: "This key didn't work. Check it and try again."
- Short note: "Your key is used only for your agents' chat replies. It's stored encrypted."

### 5.3 Small screens
Below ~768px the nav bar collapses into a menu button at the top that opens it as a drawer. The MVP is desktop-first; mobile only needs to be usable, not polished.

---

## 6. Page 1 — Create Your Agent

### 6.1 Agent list (`/app/agents`)
```
Your agents                                   [ + Create agent ]
┌──────────────────────────────────────────────────────────────┐
│ Support Bot        Live    Gemini · gemini-model   [Edit][⋯] │
│ Answers customer questions about our store                   │
├──────────────────────────────────────────────────────────────┤
│ GitHub Helper      Draft   OpenAI · gpt-model      [Edit][⋯] │
│ Tracks my repositories                                       │
└──────────────────────────────────────────────────────────────┘
```
- Each row: name, description, status badge (**Draft** / **Live**), provider and model.
- Row actions: **Edit**, and a menu with **Chat**, **Analytics**, **Delete**.
- Delete asks for confirmation: "Delete Support Bot? Its documents, connections and chats will be deleted too."
- **Empty state:** "You don't have any agents yet. Create one to start chatting." + **Create agent** button.

### 6.2 Create / edit wizard
A stepper at the top, one step per screen, with **Back** and **Continue** buttons at the bottom. The steps are a real sequence, so they are numbered. On edit, the user can jump to any step directly.

```
 ① Basics ─ ② Behavior ─ ③ Model ─ ④ Knowledge ─ ⑤ Tools ─ ⑥ Apps ─ ⑦ Deploy
```

The agent is saved as a **Draft** after step 1, so leaving the wizard never loses work. Each later step saves when the user clicks **Continue**.

#### Step 1 — Basics
- **Name** (required), **Description** (optional).

#### Step 2 — Behavior
- Grid of persona options (Customer care, Developer, Tester, Friend, Store owner, Teacher, Doctor, Career guidance, …) loaded from `GET /personas`. **Exactly one** can be chosen (radio cards).
- Last option: **Custom prompt**.
- Below the grid: a text area showing the full system prompt for the chosen persona, **editable**. For Custom prompt, the text area starts empty.

#### Step 3 — Model
- **Provider:** Gemini or OpenAI (radio).
- **Model:** dropdown for the chosen provider.
- **API key status:**
  - Saved → "Using your saved Gemini key (•••• a1b2)."
  - Not saved → inline key input + **Save key**.
- **Skip for now** link. If skipped, the chat page will ask for the key later.

#### Step 4 — Knowledge
- Toggle: **Use a knowledge base**.
- When on:
  - **Search mode:** Hybrid (default, marked "Recommended"), Semantic, Keyword. One short line explaining each.
  - **Add documents:** drag-and-drop area (`.txt`, `.md`, `.pdf`) + **Paste text** button (opens a dialog with title + text area).
  - **Document list** with live status badge: Pending → Processing → Ready / Failed. Poll every few seconds while any document is Pending or Processing.
  - Failed rows show the error, e.g. "This PDF has no readable text."
  - Each row: name, type, chunk count when ready, **Delete**.
- Note under the upload area: "Text, Markdown and text-based PDFs. Scanned PDFs and images aren't supported yet."

#### Step 5 — Tools
- Checkbox list of tools from `GET /tools`, **grouped by what they do, not by provider**. Users don't need to know whether a tool comes from Open-Meteo or SerpApi.

| Group | Tools |
|---|---|
| Basics | Calculator, Current date and time |
| Search and knowledge | Web search, Wikipedia |
| Weather | Current weather, Weather forecast |
| News | Latest news |
| Money and markets | Currency conversion, Exchange rates, Stock quote, Company news |
| Travel | Flight status, Hotel search, Public holidays, Country info |
| Places and maps | Find places, Place reviews, Directions, Find location |
| Shopping | Product search (Google Shopping), Amazon product search |
| Video | YouTube search |

- Each item: name + one-line description.
- **Select all** per group.
- The knowledge base tool is not listed here; it is turned on automatically by step 4.

#### Step 6 — Apps
Grid of app cards from `GET /integrations/apps` (GitHub, Gmail, Google Drive, Notion, …).

```
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ [GitHub]      │  │ [Gmail]       │  │ [Notion]      │
│ Connected     │  │ Not connected │  │ Needs         │
│ Read & write  │  │               │  │ reconnecting  │
│ [Manage]      │  │ [Connect]     │  │ [Reconnect]   │
└───────────────┘  └───────────────┘  └───────────────┘
```

**Connect flow**
1. **Connect** opens a dialog: "What can this agent do in GitHub?" → **Read only** or **Read & write** (with one line explaining each).
2. **Continue to GitHub** → frontend calls the connect endpoint and redirects to the returned URL.
3. After login, the user returns to `/app/integrations/callback`, which shows "Connecting GitHub…" then sends them back to step 6 of this agent with a toast: "GitHub connected."
4. If it failed: "GitHub wasn't connected. Try again." with a **Try again** button.

**Manage (after connecting)**
- Shows access level, status, and the list of the app's actions as checkboxes from `GET /agents/{id}/integrations/{app}/actions`.
- Actions are split into **Read actions** and **Write actions**. Write actions are disabled for Read-only connections.
- Small note on the write section: "You'll be asked to approve each write action in the chat."
- **Change access** (reconnects with the other level) and **Disconnect**.

**Statuses:** Not connected · Connecting · Connected · Needs reconnecting.

#### Step 7 — Deploy
- Read-only summary of all steps (persona, model, documents count, tools count, apps), each with an **Edit** link back to its step.
- Warnings, not blockers:
  - No API key → "Add your API key before chatting."
  - Documents still processing → "Some documents are still being indexed."
- **Deploy agent** button → status becomes **Live** → toast "Support Bot is live" + **Start chatting** button.
- For an already live agent, the button reads **Save changes**.

---

## 7. Page 2 — Chat with Your Agent

### 7.1 Layout
```
┌─────────────────┬────────────────────────────────────────────┐
│ [Agent ▾]       │ Support Bot                    Gemini      │
│ [+ New chat]    │────────────────────────────────────────────│
│                 │                                            │
│ Today           │  You: What's my latest GitHub project?     │
│  Latest repo    │                                            │
│ Yesterday       │  ⚙ Calling GitHub… ✓                       │
│  Holiday plans  │                                            │
│                 │  Agent: Your latest repo is xyz, last      │
│                 │  updated 2 hours ago.                      │
│                 │                                            │
│                 │────────────────────────────────────────────│
│                 │ [ Message Support Bot…            ] [Send] │
└─────────────────┴────────────────────────────────────────────┘
```

- **Left panel (inside the page):** agent selector (live agents only), **New chat** button, list of sessions grouped by date. Each session has a menu with **Delete**.
- **Main panel:** agent name and model at the top, messages in the middle, message box at the bottom.
- `/app/chat` with no agent selected: "Pick an agent to start chatting." If the user has no live agents: "You don't have a live agent yet." + **Create agent** button.

### 7.2 Messages
- User messages right-aligned; agent messages left-aligned, rendered as Markdown (code blocks, lists, links, tables).
- Replies stream in token by token. While streaming, the **Send** button becomes **Stop**.
- Enter sends, Shift+Enter adds a new line.
- Auto-scroll to the newest message unless the user has scrolled up.

### 7.3 Streaming events → UI
The chat endpoint streams these SSE events (spec §12.4). Each maps to one UI element:

| SSE event | What the UI shows |
|---|---|
| `token` | Append text to the current agent message |
| `tool_start` | Small activity line in the message, e.g. "Searching knowledge base…", "Calling GitHub…", "Checking the weather…" with a spinner |
| `tool_end` | Activity line turns into a check (✓) or a cross (✕) with a short error |
| `sources` | A "Sources" row under the message: chips with document name and page; clicking shows the chunk text in a popover |
| `approval_required` | Approval card (§7.4) |
| `reconnect_required` | Reconnect banner (§7.5) |
| `error` | Inline error in the message with **Retry** |
| `done` | Stop the streaming state, re-enable the message box |

Activity lines use friendly names from the tool registry, not raw tool names (show "Searching hotels", not `search_hotels`).

### 7.4 Approval card (write actions)
```
┌──────────────────────────────────────────────┐
│ Approve this action?                         │
│ Create a GitHub repository                   │
│   name: my-app                               │
│   private: yes                               │
│                         [Reject] [Approve]   │
└──────────────────────────────────────────────┘
```
- Shows the action in plain words and its arguments.
- While the card is open, the message box is disabled with the hint "Approve or reject the action to continue."
- **Approve** / **Reject** call the approval endpoint and the reply continues streaming in the same message.
- After a decision, the card stays in the history as a single line: "Approved: Create a GitHub repository" or "Rejected: …".
- If the page is reloaded while an approval is pending, the card is shown again.

### 7.5 Reconnect banner
- Shown above the message box: "GitHub needs to be reconnected." + **Reconnect** button.
- Reconnect runs the same OAuth flow as §6.2 step 6 and returns to this chat.

### 7.6 Blocked chat (no API key)
If the user has no key for the agent's provider, the message box is replaced by:
"Add your Gemini API key to start chatting." + **Add API key** (opens the API keys dialog). Once saved, the chat unlocks without a page reload.

---

## 8. Page 3 — Analytics

### 8.1 Layout
```
Analytics    [Agent ▾]                     [Last 7 days ▾]
┌──────────┐┌──────────┐┌──────────┐┌──────────┐
│ Sessions ││ Messages ││ Tool     ││ Success  │
│    42    ││   318    ││ calls 97 ││  rate 94%│
└──────────┘└──────────┘└──────────┘└──────────┘
┌──────────────────────────────────────────────┐
│ Activity over time (line chart)              │
└──────────────────────────────────────────────┘
┌───────────────────────┐┌─────────────────────┐
│ Tool calls by tool    ││ Tool calls by type  │
│ (bar chart)           ││ API / App / KB      │
└───────────────────────┘└─────────────────────┘
┌───────────────────────┐┌─────────────────────┐
│ Knowledge base        ││ Write actions       │
│ searches, avg score   ││ approved / rejected │
└───────────────────────┘└─────────────────────┘
┌──────────────────────────────────────────────┐
│ Tool details table: tool, calls, success,    │
│ failures, avg latency                        │
└──────────────────────────────────────────────┘
┌──────────────────────────────────────────────┐
│ Connection errors: app, count, last seen     │
└──────────────────────────────────────────────┘
```

- **Filters:** agent selector and range (Last 24 hours, Last 7 days, Last 30 days).
- **Stat tiles:** sessions, messages, tool calls, success rate.
- **Charts (recharts):** activity over time (line), tool calls by tool (bar), tool calls by type (bar or donut), write actions approved vs rejected.
- **Tables:** per-tool details with average latency; connection errors per app.
- All data comes from `GET /agents/{id}/analytics?range=`. The frontend never calls PostHog directly.

### 8.2 States
- Loading: skeleton tiles and charts.
- No data yet: "No activity yet. Chat with Support Bot to see analytics here." + **Open chat**.
- Error: "Analytics couldn't load." + **Retry**.

---

## 9. Shared Patterns

### 9.1 States checklist (every screen)
| State | Pattern |
|---|---|
| Loading | Skeletons for lists, tiles and charts; spinner inside buttons for actions |
| Empty | One sentence saying what to do next + one primary button |
| Error | What went wrong and what to do, + **Retry** where it makes sense |
| Success | Toast for completed actions ("Agent deployed", "Key saved", "GitHub connected") |

### 9.2 Copy rules
- Sentence case everywhere ("Create agent", not "Create Agent").
- Buttons say exactly what happens: "Deploy agent", "Save key", "Connect", "Approve".
- The same action keeps the same name across the flow: button "Deploy agent" → toast "Support Bot is live".
- Errors explain the fix, don't apologize, and never show raw error codes or stack traces.
- Use user words, not system words: "apps" not "integrations", "documents" not "chunks", "chat" not "session".

### 9.3 Session expiry
If any API call returns 401, sign the user out and return to `/` with the message "Your session expired. Sign in again."

### 9.4 Accessibility basics
- Visible keyboard focus on all interactive elements (shadcn/ui provides this).
- All icon-only buttons have labels.
- Color is never the only signal: status badges always include text.

---

## 10. Visual Basics (MVP)

Keep the library defaults; change only the essentials.

| Token | Value |
|---|---|
| Base theme | shadcn/ui default (neutral), light mode only for MVP |
| Primary / accent | One brand color, used for primary buttons, active nav item and links |
| Success | Green — Live badge, ✓ tool results, Connected |
| Warning | Amber — Draft badge, Processing, Needs reconnecting |
| Danger | Red — Failed, errors, Delete, Reject |
| Font | System font stack (no custom fonts in MVP) |
| Radius / spacing / shadows | Library defaults |

Status badge colors:

| Status | Color |
|---|---|
| Live, Ready, Connected | Green |
| Draft, Pending, Processing | Amber |
| Failed, Needs reconnecting | Red |
| Not connected | Grey |

---

## 11. Frontend Folder Structure

Matches spec §17.

```
frontend/
  src/
    main.jsx
    App.jsx                    # router + auth guard
    lib/
      supabase.js              # Supabase client
      api.js                   # fetch wrapper (adds Bearer token, handles 401)
      sse.js                   # fetch-event-source wrapper for chat
    layouts/
      AppShell.jsx             # left nav + user menu + content
    pages/
      Landing.jsx
      AgentsList.jsx
      AgentWizard/             # one file per step
        Basics.jsx  Behavior.jsx  Model.jsx  Knowledge.jsx
        Tools.jsx   Apps.jsx      Deploy.jsx
      Chat.jsx
      Analytics.jsx
      IntegrationCallback.jsx
    components/
      ApiKeysDialog.jsx
      AgentSelect.jsx
      StatusBadge.jsx
      DocumentUpload.jsx
      ToolGroupList.jsx
      AppCard.jsx  ConnectAppDialog.jsx
      chat/
        MessageList.jsx  Message.jsx  ToolActivity.jsx
        Sources.jsx  ApprovalCard.jsx  ReconnectBanner.jsx  Composer.jsx
      analytics/
        StatTile.jsx  ActivityChart.jsx  ToolCallsChart.jsx  ToolTable.jsx
      ui/                      # shadcn/ui generated components
```

---

## 12. Build Order (aligned with spec §18)

1. Landing page + Google sign-in + auth guard + app shell with nav.
2. Agent list + wizard steps 1–3 and 7 (basics, behavior, model, deploy) + API keys dialog.
3. Chat page with streaming text, sessions, blocked state.
4. Wizard step 5 (tools) + tool activity lines in chat.
5. Wizard step 4 (knowledge) + document statuses + sources in chat.
6. Wizard step 6 (apps) + OAuth callback + reconnect banner.
7. Approval card.
8. Analytics page.

---

## 13. After the MVP

- Full visual redesign with a distinct brand identity (custom typography, palette, illustrations).
- Richer landing page: product demo, feature sections, examples of agents.
- Dark mode.
- Polished mobile layout.
- Drag-and-drop canvas agent builder (with multi-agent).
- Onboarding tour for first-time users.
