# Result Cards Design — tool results shown as cards in chat

Date: 2026-11-19
Status: approved by the owner in chat ("yes go ahead")

This replaces the stage 2B non-goal "Showing results as rich cards". Everything else in `2026-11-18-stage-2b-api-tools-design.md` still holds.

## 1. Intent

Today a tool's result reaches the user only as the agent's prose. Photos, product links, old prices, delivery details and airline logos are dropped before the chat sees them. The owner wants every tool's result shown as a visual card with images, ratings and working links, using every useful field the service returns.

## 2. Goals

1. Every one of the 19 tools shows a card under the agent's reply when it succeeds.
2. A field appears on a card only when the service returned it. Nothing is invented.
3. Cards are saved with the message and are still there when a chat is reopened.
4. The agent's text becomes a short summary instead of repeating the list.
5. A follow-up such as "tell me more about the second one" still works.

## 3. Non-goals and anti-goals

- No booking, buying or any other action from a card. Cards only link out.
- No per-flight booking link: SerpApi needs a second paid call per flight for that. The flights card links to the same search on Google Flights.
- Images and links written by the agent in its own text stay blocked, as today. Only addresses that came from a service's reply are loaded.
- No platform key reaches the browser. No database migration.

## 4. Approaches

- **A. Tools send their result to the chat beside the agent's text (chosen).** Each tool returns its text for the model, as today, plus a card payload built from the service's reply. The cards never pass through the model, so their links and images are exactly what the service returned.
- **B. The agent writes the cards itself** (structured text the chat turns into cards). Rejected: the model can drop, change or invent links and prices, and it would reopen the image safety hole.
- **C. The chat page parses the agent's prose.** Rejected: fragile, and the photos are not in the prose at all.

## 5. Design

### Backend

- Tools use LangChain's `response_format="content_and_artifact"` (already used by the knowledge-base and details tools). The artifact is `{"card": {"kind", "service", ...}}`. One helper in `app/tools/http.py` builds both halves; `no_results` returns no card.
- `runner.py`: a tool message whose artifact has `card` adds it to that tool's entry. It goes out in the `tool_end` event and is saved in `Message.tool_calls` (existing JSONB column), so `GET messages` returns it under `tools[].card`.
- `context.py`: an earlier assistant reply that had list cards gets a short bracketed note appended for the model only (item name, price, link), so follow-ups work now that the text no longer lists everything.
- `chat.py`: one extra instruction when the agent has tools: results are shown as cards, so write a short summary, do not repeat the list or write links, and never write the bracketed notes.
- Fields are taken with `pick`, so missing ones are simply absent. Every list card uses `items`, and each item has `title` (or `name`), plus `price` and `link` where they exist.

Card kinds and what each carries (confirmed against one live call per service on 2026-11-19):

| Kind | Tools | Fields |
|---|---|---|
| `products` | Amazon, Google Shopping | title, image, price, old_price, price_unit, rating, reviews, store, delivery, offers, sponsored, link (Amazon's clean product link) |
| `stays` | Airbnb | name, title (type and area), description, images (up to 6), price, old_price, price_qualifier, rating, reviews, bedrooms, beds, bathrooms, is_new, link, latitude/longitude |
| `flights` | Google Flights | currency, lowest_price, price_level, typical_price_range, origin and destination city, link to the search; per flight: title, price, duration, stops, trip, logo, emissions difference, legs (airline, logo, flight number, airports and times, duration, airplane, class, legroom), layovers |
| `weather` | current weather | place, time, conditions, temperature, feels like, humidity, wind, precipitation, day or night |
| `forecast` | forecast | place; per day: date, conditions, high, low, rain chance, rain amount, wind, UV, sunrise, sunset |
| `conversion`, `rates` | Frankfurter | amount, from, to, rate, result, source / base, rates, source |
| `quote` | Finnhub quote | symbol, price, change, change %, high, low, open, previous close, time, plus name, logo, currency, exchange, industry and website from Finnhub's free company profile (one extra call, fetched at the same time; the quote still works if it fails) |
| `symbols` | find symbol | symbol, name, type |
| `links` | web search, news, company news, books | optional direct answer; per item: title, link, snippet, source, date, image, favicon, authors |
| `images` | image search | thumbnail, full image, title, source, page link |
| `places` | places | name, address, rating, reviews, category, price level, phone, website, Google Maps link |
| `translation` | translate | original, translation, both languages, pronunciations, link to Google Translate |
| `calculation`, `clock` | calculator, date and time | expression and result / date, time, time zone |

Products, stays and images return 8 items instead of 5 so a row of cards looks full; the model sees the same items the cards show.

### Frontend

- `sse.js` / `Chat.jsx`: `tool_end` carries `card`; it is kept on the streaming tool entry.
- `components/chat/cards/`: a `ResultCards` component picks a card component by `kind`; an unknown kind shows nothing. `Message.jsx` renders it under the reply text, for live and saved messages alike.
- Two shared pieces carry the safety rules: an image component (http/https only, lazy, no referrer, removes itself if it fails to load) and an external link (http/https only, new tab, `noreferrer noopener`).
- Layout: product, stay and image cards are a horizontally scrolling row; flights, links and places are stacked rows; weather, currency, stocks, translation, calculator and clock are single compact panels with the key number large. Stay cards have a small photo carousel.

## 6. Testing

- Backend, test-first: each tool's card carries the expected fields from a canned service reply and nothing when there are no results; `tool_end` and saved messages carry the card; the history note is built; the instruction is added.
- Frontend: build and lint, then a walkthrough in the owner's Chrome with a real search for each kind.

## 7. Left to the builder

Exact card styling, which fields are shown at a glance and which behind a "details" line, and file layout inside `components/chat/cards/`.
