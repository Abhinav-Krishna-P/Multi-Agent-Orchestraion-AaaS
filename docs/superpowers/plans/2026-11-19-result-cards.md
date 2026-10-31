# Result Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every tool's result is shown in chat as a card built from the service's own reply (photos, prices, ratings, links), saved with the message.

**Architecture:** Each tool returns its text for the model plus an artifact `{"card": {...}}`. The runner forwards the card in `tool_end` and saves it in `Message.tool_calls`. The chat renders one card component per `kind`. The model is told to summarise instead of listing, and earlier replies get a short note of what their cards showed.

**Tech Stack:** FastAPI, LangChain tools (`response_format="content_and_artifact"`), LangGraph, pytest; React, Tailwind v4, shadcn/ui, lucide-react.

**Spec:** `docs/superpowers/specs/2026-11-19-result-cards-design.md`

## Global Constraints

- No database migration; cards live in the existing `Message.tool_calls` JSONB.
- No platform key in a card, an event, a log or the browser.
- A card field exists only when the service returned it (`pick`).
- Images and links are loaded only from card data, only `http://` or `https://`.
- Agent-written images stay blocked (`Message.jsx` markdown rules are not changed).
- Existing backend tests keep passing. Never push. Commit trailer: `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.
- Run backend tests from `backend/` with `.venv/Scripts/python -m pytest`; never two runs at once.

## Review Focus

1. A service item with no image, no rating or no link: the card still renders, without a broken image or a dead link.
2. A link or image address that is not http(s) (`javascript:`, `data:`): never rendered as a link or image. Pinned by Task 4's `safeUrl` self-check.
3. A tool that fails or finds nothing: no card, the tick/cross line still shows. Pinned in Tasks 1 and 2.
4. A reply stopped halfway: the cards received so far are saved with the partial reply. Pinned in Task 1.
5. An old saved message with no `card` on its tools: renders as before. Pinned in Task 4's walkthrough (existing chats).

---

### Task 1: Card plumbing, calculator and clock cards

**Files:**
- Modify: `backend/app/tools/http.py`, `backend/app/agent/runner.py`, `backend/app/tools/builtin.py`
- Test: `backend/tests/test_result_cards.py` (new), `backend/tests/test_tool_loop.py` (expected values)

**Interfaces:**
- Produces: `http.shown(service: str, data, kind: str, **card) -> tuple[str, dict]` returning `(wrap(service, data), {"card": {"kind": kind, "service": service, **card}})`; `http.no_results(service) -> tuple[str, None]`.
- Produces: `tool_end` event `{"id", "ok", "card"?}`; saved tool entry `{"label", "ok", "card"?}` (`card` only when present).
- Produces test helper in `test_result_cards.py`: `async def card_of(tool_name: str, **args) -> dict | None` which invokes the registered tool with a tool-call dict and returns `message.artifact["card"]` or `None`.

- [ ] **Step 1: Failing tests** in `test_result_cards.py`:
  - `test_calculator_card`: `card_of("calculator", expression="(1250 * 3) / 4")` == `{"kind": "calculation", "service": "Calculator", "expression": "(1250 * 3) / 4", "result": "937.5"}`; `card_of("calculator", expression="import os")` is `None`.
  - `test_clock_card`: `card_of("get_current_datetime", timezone="Asia/Kolkata")` has `kind == "clock"`, `timezone == "Asia/Kolkata"`, `offset == "UTC+05:30"`, and non-empty `date`, `time`, `weekday`; an unknown zone gives `None`.
  - `test_card_reaches_the_event_and_the_saved_message` (uses the `live_chat`/`use_model` fixtures as `test_tool_loop.py` does): after a calculator turn, the `tool_end` data has `card["kind"] == "calculation"`, and `GET messages` returns it at `tools[0]["card"]`.
  - `test_failed_tool_has_no_card`: a failing tool's `tool_end` has no `card` key.
- [ ] **Step 2:** Run `pytest tests/test_result_cards.py -q`; expect failures (no artifact).
- [ ] **Step 3:** Implement `shown`, change `no_results` to return `(text, None)`; make `calculator` and `get_current_datetime` `@tool(response_format="content_and_artifact")` (error strings return `(text, None)`); in `runner.run_turn` set `used[id]["card"]` and add `card` to the `tool_end` payload when the artifact is a dict with `card`.
- [ ] **Step 4:** Update `test_tool_loop.py` expectations that compare whole tool entries (lines 41, 48, 59, 175) to include the calculator card. Run `pytest tests/test_result_cards.py tests/test_tool_loop.py tests/test_tools.py -q`; expect pass.
- [ ] **Step 5:** Commit `feat: tools can send a result card to the chat; calculator and clock cards`.

### Task 2: Cards for the 17 service tools

**Files:**
- Modify: `backend/app/tools/apis/serpapi.py`, `serper.py`, `open_meteo.py`, `frankfurter.py`, `finnhub.py`
- Test: `backend/tests/test_result_cards.py`, `backend/tests/test_api_tools.py` (fixtures only where a new request or field needs one)

**Interfaces:**
- Consumes: `shown`, `no_results`, `card_of`.
- Produces card payloads exactly as the spec's table: kinds `products`, `stays`, `flights`, `weather`, `forecast`, `conversion`, `rates`, `quote`, `symbols`, `links`, `images`, `places`, `translation`. List cards use `items`; each item has `title` (stays and places also `name`), and `price`, `link` where the service gave them. `http.LIST_RESULTS = 8` for products, stays and images; others stay at `MAX_RESULTS`.

Field sources (new name ← service field):
- Amazon: image←thumbnail, link←link_clean (else link), price, old_price, price_unit, rating, reviews, delivery (list), offers (list), sponsored, bought_last_month.
- Google Shopping: image←imageUrl, store←source, reviews←ratingCount, price, rating, link.
- Airbnb: name, title, description, images (first 6, else `[thumbnail]`), price, old_price, price_qualifier, rating, reviews, bedrooms, beds, bathrooms, is_new←is_new_listing, link, latitude/longitude←gps_coordinates.
- Flights: top level currency, lowest_price, price_level, typical_price_range, link←search_metadata.google_flights_url, origin/destination ← `airports[0].departure[0].city` / `.arrival[0].city`; item: title (`"IndiGo 6E 2127 · COK 21:40 → DEL 00:50"` from the first and last legs), price, duration_minutes, stops, trip, logo←airline_logo, emissions_percent←carbon_emissions.difference_percent, legs (airline, logo, flight, from/to `{id, name, time}`, duration, airplane, travel_class, legroom, overnight, often_delayed), layovers (name, duration, overnight). The model's text keeps today's smaller shape.
- Web search: answer; items title, link, snippet, source, image←thumbnail, favicon. Books: title, link, snippet, date, authors, image←thumbnail. News: title, link, snippet, source, date, image←imageUrl. Company news: title←headline, link←url, snippet←summary (200 chars), source, date, image.
- Images: image←imageUrl, thumbnail←thumbnailUrl, title, source, link.
- Places: name and title←title, address, rating, reviews←ratingCount, category, price_level←priceLevel, phone←phoneNumber, website, link←`https://www.google.com/maps?cid={cid}`.
- Translate: text←source.text, translation, from, to, pronunciation←target.pronunciation, source_pronunciation, link←search_metadata.google_translate_url.
- Weather: add `apparent_temperature,precipitation,is_day` to the `current` request; card has feels_like_c, precipitation_mm, is_day. Forecast: add `precipitation_sum,wind_speed_10m_max,uv_index_max,sunrise,sunset` to `daily`; read every daily series with `.get` so a missing one is skipped.
- Quote: fetch `stock/profile2` together with the quote (`asyncio.gather`, a `ToolError` from the profile is ignored); card adds name, logo, currency, exchange, industry←finnhubIndustry, website←weburl, time←t.

- [ ] **Step 1: Failing tests**, one per kind, each feeding a canned reply through the existing `web` fixture and asserting the card: kind, service, item count, and the full first item (every mapped field present; a second item missing image/rating has no such keys). Also `test_no_results_has_no_card` for one SerpApi and one Serper tool, `test_quote_card_without_a_profile` (profile request answers 500 → card still has price, no name), and `test_lists_show_eight` (10 products in → 8 items, and the model text names the same 8).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement per the field table; every tool becomes `content_and_artifact` and returns `shown(...)` or `no_results(...)`.
- [ ] **Step 4:** Run `pytest tests/test_result_cards.py tests/test_api_tools.py tests/test_details_form.py -q`; fix only fixtures that lack a newly requested field or path. Expect pass.
- [ ] **Step 5:** Commit `feat: result cards for every service tool`.

### Task 3: Short replies and a memory of what the cards showed

**Files:**
- Modify: `backend/app/agent/context.py`, `backend/app/api/chat.py`, `backend/app/tools/registry.py` (the instruction text lives beside the registry)
- Test: `backend/tests/test_result_cards.py`

**Interfaces:**
- Produces: `registry.CARDS_INSTRUCTION: str`; `context.cards_note(tool_calls: list | None) -> str` returning `""` or `"\n\n[Shown to the user as cards: 1. <title or name> | <price> | <link>; 2. ...]"` (items of every card in order, at most 8 per card, parts skipped when absent).

- [ ] **Step 1: Failing tests:** `test_cards_note` (two items, one without price → exact string above; no cards → `""`; a panel card without `items` → `""`); `test_history_carries_the_note` (`build_messages` with an assistant row whose `tool_calls` hold a products card → that `AIMessage.content` ends with the note; a row object without `tool_calls` still works); `test_instruction_added_when_the_agent_has_tools` (the model's system message in a tool turn contains `CARDS_INSTRUCTION`; an agent with no tools does not get it).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement. Instruction copy: "The results of your tools are shown to the user as cards under your reply, with each item's photo, price, rating and link. Do not list the results again and do not write links or image addresses. Write a short reply: what you found, and which you would pick or what is worth noticing, referring to items by name. A note in [square brackets] at the end of one of your earlier replies was added by the platform to remind you what its cards showed; never write such a note yourself."
- [ ] **Step 4:** Run `pytest tests/test_result_cards.py tests/test_chat.py tests/test_tool_loop.py -q`; expect pass.
- [ ] **Step 5:** Commit `feat: the agent summarises instead of repeating card results`.

### Task 4: Cards in the chat

**Files:**
- Create: `frontend/src/components/chat/cards/index.jsx` (dispatcher `ResultCards`, shared `CardImage`, `ExtLink`, `Stars`, `safeUrl`), `frontend/src/components/chat/cards/lists.jsx` (products, stays, links, images, places, symbols), `frontend/src/components/chat/cards/panels.jsx` (flights, weather, forecast, conversion, rates, quote, translation, calculation, clock)
- Modify: `frontend/src/pages/Chat.jsx` (`onToolEnd` keeps `card`), `frontend/src/components/chat/Message.jsx` (render `<ResultCards tools={tools} />` after the reply text)

**Interfaces:**
- Consumes: `tools[].card` from the stream and from saved messages.
- Produces: `ResultCards({ tools })`; `safeUrl(value) -> string | undefined` (only `http:`/`https:` URLs).

- [ ] **Step 1:** `safeUrl` with a dev-only self-check (`import.meta.env.DEV` `console.assert`s: `https://a.b` passes; `javascript:alert(1)`, `data:text/html,x`, `//a.b`, `""`, `undefined`, `42` are rejected).
- [ ] **Step 2:** Build the shared pieces and the card components per the spec's layout section. `CardImage`: `loading="lazy"`, `referrerPolicy="no-referrer"`, empty `alt` unless a title is given, removed on error. `ExtLink`: `target="_blank" rel="noreferrer noopener"`, renders its children as plain text when the URL is unsafe.
- [ ] **Step 3:** Wire `Chat.jsx` and `Message.jsx`.
- [ ] **Step 4:** `npm run build` and `npm run lint`; expect both clean.
- [ ] **Step 5:** Commit `feat: result cards in chat`.

### Task 5: Verify

- [ ] **Step 1:** Full backend suite `pytest -q` (timeout 10 min); expect all pass.
- [ ] **Step 2:** Restart the backend. In the owner's Chrome with the "Tools Tester" agent, run one real request per kind (Amazon earbuds; Goa stays with dates; COK→DEL flight; weather and forecast; currency; AAPL quote; news; places; images; books; translate; a sum; the time), check each card's images load and links are right, reload the page and check the cards are still there, open an older chat and check it renders unchanged, and ask a follow-up about "the second one".
- [ ] **Step 3:** One fresh reviewer subagent over the branch diff since `cd45f49` against the spec; fix confirmed findings; record deferred minors in `.superpowers/sdd/2026-11-19-result-cards/progress.md`.
