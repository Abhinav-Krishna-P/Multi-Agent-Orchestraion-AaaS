# Stage 2, Part B Design — API Tools and the Details Dialog

Date: 2026-11-18
Status: waiting for approval

Part A (`docs/superpowers/specs/2026-11-17-stage-2a-knowledge-base-design.md`) built the tool loop, the tool registry, and the Tools step in the wizard. Part B adds the outside services listed in `Api txt/Api  docs.txt` as tools, and a dialog in the chat for searches that have filters. Where this document disagrees with the original spec in `Project data/`, this document wins.

## 1. Intent

Give agents real abilities: search the web, check weather, flights, stocks and exchange rates, find stays, products, places, news, books and images, and translate text. For searches with many options, the agent does not guess: the chat shows a small form (dates, guests, price, type) and searches with what the user chose.

## 2. Goals

1. A user switches on any of the new tools for an agent in the Tools step, grouped by what they do.
2. In chat, the agent uses the right tool for a question and answers from its result, with links where the service gives them.
3. A simple request ("rooms in Goa") runs at once.
4. A request that needs details the user did not give ("a place to stay in Goa next month") makes the agent show a **details dialog** in the chat, filled in with what it already understood. The user completes it and the search runs, or chooses to skip the filters.
5. After a search with a filterable tool, the answer carries a **Refine with filters** button that opens the same dialog with the values that were used.
6. A dialog still works after the page is reloaded.
7. A service that is slow, down, or out of quota produces a clear line in chat and the reply still finishes.
8. A tool whose API key is missing from the server does not appear in the Tools step.

## 3. Non-goals

- App connections (Composio), approve/reject for write actions, analytics: stage 3.
- Booking, buying, or any action on these services. Every tool in Part B only reads.
- Services dropped from the original spec because they are not in the owner's list: Tavily, Wikipedia, NewsData.io, Nager.Date, REST Countries, OpenRouteService, and SerpApi's Maps, Hotels and YouTube.
- Per-user limits on how many searches spend the platform's SerpApi and Serper credits.
- Showing results as rich cards (photos, maps). Results are the agent's text with links.

## 4. Anti-goals

- No platform API key is ever sent to the browser, the model, a log line, or LangSmith.
- Text returned by a service is untrusted, like document text: it must never be treated as instructions.
- Stage 1 and Part A behaviour does not regress: their 262 tests keep passing.
- No pushing.

## 5. Constraints

- Keys already in `backend/.env`: `SERPAPI_API_KEY`, `SERPER_API_KEY`, `AVIATIONSTACK_API_KEY`, `FINNHUB_API_KEY`. Open-Meteo and Frankfurter need none.
- All the services were called once on 2026-11-18 with these keys and answered, except Frankfurter's `v2` address, which timed out; the build rechecks it and falls back to `v1` if needed.
- Every SerpApi and Serper call spends the owner's credits, including during testing.
- Gemini only. The machine has 7.3 GB of memory.

## 6. Approaches considered

**How the agent pauses for details**

- **A saved request and an ordinary reply (chosen).** The agent calls a small `ask_for_details` tool. That ends its turn; the form it asked for is saved with its message and shown in chat. The user's choices come back as their next message, written out in words ("Search stays: location Goa; check-in 2026-12-10; …"), and the agent then calls the search tool with them. Nothing new is needed on the server to resume, a reload loses nothing, and the chat history reads naturally.
- **LangGraph's interrupt with a checkpoint database.** The graph freezes mid-turn and resumes when the user answers. It needs a second set of tables, a resume endpoint, and its Postgres driver has a known problem with the event loop on Windows. Stage 3's approve/reject cards can reuse the chosen approach's dialog card instead.

**When the dialog appears** (decided by the project owner): the agent decides, plus a refine button.

**One tool or several per service:** one tool per function, as the owner asked. A search tool's filters are optional arguments of that one tool.

## 7. Decisions already made by the project owner

- The API list in `Api txt/Api  docs.txt`, with SerpApi and Serper for the Google and marketplace searches.
- One tool per API function, and as many tools as are useful.
- A details dialog (human in the loop) for tools with filters, in the same way across services.
- The dialog appears when the agent judges that needed details are missing, and every filterable result has a Refine button.

## 8. What gets built

### 8.1 The tools

Sixteen tools. Each is one function with a clear description, typed arguments, a time limit of 15 seconds, and a trimmed result (the top 5 items and only the useful fields), so replies stay fast and cheap.

| Group | Tool | Service | Filters in the dialog |
|---|---|---|---|
| Search and knowledge | Web search | SerpApi (Google) | — |
| | Book search | SerpApi (Google Books) | — |
| | Image search | Serper | — |
| | Translate text | SerpApi (Google Translate) | — |
| Weather | Current weather | Open-Meteo | — |
| | Weather forecast (1 to 7 days) | Open-Meteo | — |
| News | News search | Serper | Time range, country |
| Money and markets | Convert currency | Frankfurter | — |
| | Exchange rates | Frankfurter | — |
| | Stock quote | Finnhub | — |
| | Find a stock symbol | Finnhub | — |
| | Company news | Finnhub | — |
| Travel | Stays search | SerpApi (Airbnb) | Check-in, check-out, guests, room type, price range |
| | Flight status | AviationStack | Date |
| Places | Find places | Serper | Kind of place, location |
| Shopping | Product search | Serper (Google Shopping) | Price range, country |
| | Amazon search | SerpApi (Amazon) | Marketplace, sort order, price range |

The exact arguments each service accepts for a filter are checked against its documentation while building. A filter a service does not support is left out of that tool's dialog.

Rules for every tool:

- The platform key is added on the server. The model never sees it and cannot choose it.
- A failure (time-out, quota, bad response) is logged with the service's name and status, and the model is told in one line that the service could not be used, so it can say so.
- Identical calls within 10 minutes are answered from memory, to save credits.
- A tool whose key is missing is left out of the catalog.
- Results are wrapped as reference material and the model is told not to follow instructions inside them, as with documents. Images in results are given as links.

### 8.2 The details dialog

- A tool that has filters declares a **form**: its fields (text, date, number, or a choice from a list), their labels, and which are required.
- When an agent has at least one such tool switched on, it also gets `ask_for_details(tool, known)`. Its instruction: use it when a request needs details the user has not given, and never invent dates, budgets or other specifics.
- Calling it ends the turn. The chat shows a card with the tool's fields, filled in with `known`. The card is saved with the assistant's message.
- **Search** sends the user's next message as a readable line listing the chosen values. **Skip filters** sends a line asking to search with what is known. Either way the agent then calls the real tool.
- After any reply that used a tool with a form, the message carries a **Refine with filters** button. It opens the same card, filled in with the values that were used.
- Only the newest message's card or button is active; older ones are shown as a plain line of what was asked.
- Dates cannot be in the past, check-out must be after check-in, and numbers must be positive: checked in the card, and again by the tool.

### 8.3 Frontend

- The Tools step shows the new groups automatically, since it already draws whatever the catalog returns.
- New chat pieces: the details card and the Refine button. Tool activity lines use each tool's own words ("Searching stays…", "Checking the weather…").

### 8.4 Tests

- Each tool is tested against saved example responses from its service: the right request is built, the result is trimmed correctly, and time-outs and error replies become the one-line failure.
- The dialog: asking ends the turn and saves the form; the form reappears after a reload; the Refine offer is saved with the right values; a tool without a form never offers one; the catalog hides tools without keys.
- One live check of every tool with the real keys, run by hand, with its output recorded.
- The browser walkthrough covers a simple search, a search that opens the dialog, Skip filters, Refine, and a failing service.

## 9. Builder's calls

- The pause is a saved request plus an ordinary reply (§6).
- Which tools have a dialog, and their fields (§8.1).
- Sixteen tools; top 5 results each; 15-second limit; 10-minute memory of identical calls.
- The tools are grouped by what they do, not by provider.
- Weather tools take a place name and look up its coordinates themselves.
- The memory of identical calls is per server process and is lost on restart.

## 10. Risks

- **Credits.** Every search spends SerpApi or Serper credits, and nothing limits a user's use yet.
- **The agent's judgement.** Whether the dialog opens is the model's decision, so it will sometimes ask when it need not, or search when it should have asked. The Refine button covers the second case.
- **Free-plan limits.** AviationStack's free plan allows few requests per month and may not allow searching by date; the dialog's date field is dropped if so.
- **Commercial terms.** Open-Meteo's free service is for non-commercial use, and SerpApi and Serper have their own terms; these need checking before a public launch.

## 11. Done means

- Every goal in §2 has been walked through in the browser.
- All automated tests pass, including the 262 earlier ones.
- Every tool has been called once for real and its result recorded.
