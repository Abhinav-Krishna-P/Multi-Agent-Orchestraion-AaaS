"""Google Search, Books, Translate and Flights, Airbnb and Amazon through SerpApi."""
import re
from typing import Literal

from langchain_core.tools import tool

from app.core.config import get_settings
from app.tools.http import (
    MAX_RESULTS, ToolError, check_price_range, fetch_json, in_price_range, no_results, parse_date, pick, wrap,
)

URL = "https://serpapi.com/search.json"

# The marketplace used when the user does not name one, by the platform's default country.
_AMAZON_DOMAINS = {"in": "amazon.in", "us": "amazon.com", "uk": "amazon.co.uk", "gb": "amazon.co.uk",
                   "ca": "amazon.ca", "de": "amazon.de", "ae": "amazon.ae", "au": "amazon.com.au"}
_AMAZON_SORT = {"price_low_to_high": "price-asc-rank", "price_high_to_low": "price-desc-rank",
                "rating": "review-rank", "newest": "date-desc-rank"}


async def search(service: str, engine: str, **params) -> dict:
    """One SerpApi search. An empty result set comes back as {} rather than an error."""
    params = {key: value for key, value in params.items() if value is not None}
    data = await fetch_json(
        service, URL, params={"engine": engine, **params}, secret_params={"api_key": get_settings().serpapi_api_key},
        # SerpApi reports "nothing found" as an error too; that one is a real answer.
        is_error=lambda reply: bool(reply.get("error")) and "returned any results" not in reply["error"],
    )
    return {} if data.get("error") else data


@tool
async def web_search(query: str, country: str | None = None) -> str:
    """Search the web with Google for current information, facts, websites or anything not
    covered by a more specific tool. `country` is a two-letter code such as "in" or "us"."""
    service = "Google Search"
    data = await search(service, "google", q=query.strip(), gl=(country or get_settings().default_country).lower(), num=MAX_RESULTS)
    results = [pick(item, title="title", link="link", snippet="snippet") for item in (data.get("organic_results") or [])[:MAX_RESULTS]]
    if not results and not data.get("answer_box"):
        return no_results(service)
    box = data.get("answer_box") or {}
    answer = box.get("answer") or box.get("result") or box.get("snippet")
    return wrap(service, {**({"answer": answer} if answer else {}), "results": results})


@tool
async def search_books(query: str) -> str:
    """Search Google Books for books by title, author or subject."""
    service = "Google Books"
    data = await search(service, "google_books", q=query.strip())
    books = [pick(item, title="title", authors="authors", date="date", snippet="snippet", link="link")
             for item in (data.get("organic_results") or [])[:MAX_RESULTS]]
    for book in books:  # authors arrive as {name, link}; only the names are useful
        if "authors" in book:
            book["authors"] = [author["name"] if isinstance(author, dict) else author for author in book["authors"]]
    return wrap(service, books) if books else no_results(service)


@tool
async def translate_text(text: str, target_language: str, source_language: str = "auto") -> str:
    """Translate text into another language with Google Translate. Languages are two-letter
    codes such as "hi" (Hindi), "ml" (Malayalam), "fr" (French); leave the source as "auto"
    to detect it."""
    service = "Google Translate"
    if not text.strip():
        raise ToolError("Give some text to translate.")
    if len(text) > 5000:
        raise ToolError("That text is too long to translate at once. Use 5,000 characters or fewer.")
    data = await search(service, "google_translate", text=text, **{"from": source_language.strip().lower()}, to=target_language.strip().lower())
    translation = data.get("translation") or {}
    translated = (translation.get("target") or {}).get("text")
    if not translated:
        return no_results(service)
    return wrap(service, {
        "translation": translated,
        "from": (translation.get("source") or {}).get("language", source_language),
        "to": (translation.get("target") or {}).get("language", target_language),
    })


@tool
async def search_stays(
    location: str,
    check_in: str | None = None,
    check_out: str | None = None,
    guests: int = 1,
    room_type: Literal["any", "entire_home", "private_room"] = "any",
    min_price: float | None = None,
    max_price: float | None = None,
) -> str:
    """Search Airbnb for places to stay in a city or area. Dates are YYYY-MM-DD and optional,
    but prices and availability are only accurate with them. Prices are per night in the
    platform's currency. If the user wants a stay for particular dates or a budget and has
    not given them, ask with ask_for_details instead of guessing."""
    service = "Airbnb"
    if bool(check_in) != bool(check_out):
        raise ToolError("Give both a check-in and a check-out date, or neither.")
    if check_in and parse_date(check_out, "check-out") <= parse_date(check_in, "check-in"):
        raise ToolError("The check-out date must be after the check-in date.")
    if guests < 1:
        raise ToolError("There must be at least 1 guest.")
    check_price_range(min_price, max_price)
    data = await search(
        service, "airbnb", q=location.strip(), check_in_date=check_in or None, check_out_date=check_out or None,
        adults=guests, room_type=None if room_type == "any" else room_type,
        min_price=None if min_price is None else int(min_price), max_price=None if max_price is None else int(max_price),
        currency=get_settings().default_currency,
    )
    stays = [pick(item, title="title", price="price", rating="rating", reviews="reviews", link="link", bedrooms="bedrooms", beds="beds")
             for item in (data.get("organic_results") or [])[:MAX_RESULTS]]
    return wrap(service, stays) if stays else no_results(service)


@tool
async def search_amazon(
    query: str,
    marketplace: str | None = None,
    sort: Literal["relevance", "price_low_to_high", "price_high_to_low", "rating", "newest"] = "relevance",
    min_price: float | None = None,
    max_price: float | None = None,
) -> str:
    """Search Amazon for products with prices and ratings. `marketplace` is an Amazon site
    such as "amazon.in" or "amazon.com". Prices are in that marketplace's currency."""
    service = "Amazon"
    check_price_range(min_price, max_price)
    domain = (marketplace or _AMAZON_DOMAINS.get(get_settings().default_country.lower(), "amazon.com")).strip().lower()
    if not re.fullmatch(r"amazon\.[a-z]{2,3}(\.[a-z]{2})?", domain):
        raise ToolError("Give the marketplace as an Amazon site, such as amazon.in or amazon.com.")
    data = await search(service, "amazon", k=query.strip(), amazon_domain=domain, s=_AMAZON_SORT.get(sort))
    # Amazon's search has no price filter of its own here, so the range is applied to what came back.
    products = [
        pick(item, title="title", price="price", rating="rating", reviews="reviews", link="link")
        for item in data.get("organic_results") or []
        if in_price_range(item.get("extracted_price"), min_price, max_price)
    ][:MAX_RESULTS]
    return wrap(service, products) if products else no_results(service)


_TRAVEL_CLASS = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}
_STOPS = {"nonstop": 1, "one_or_fewer": 2}


def _airport(code: str) -> str:
    code = code.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ToolError("Use three-letter airport codes such as COK, DEL or DXB.")
    return code


def _leg(leg: dict) -> dict:
    departs, arrives = leg.get("departure_airport") or {}, leg.get("arrival_airport") or {}
    return {
        "airline": leg.get("airline"), "flight": leg.get("flight_number"),
        "from": f"{departs.get('id')} {departs.get('time')}", "to": f"{arrives.get('id')} {arrives.get('time')}",
    }


@tool
async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    passengers: int = 1,
    travel_class: Literal["economy", "premium_economy", "business", "first"] = "economy",
    stops: Literal["any", "nonstop", "one_or_fewer"] = "any",
    max_price: float | None = None,
) -> str:
    """Search Google Flights for flights and fares between two airports. `origin` and
    `destination` are three-letter airport codes: work them out from city names yourself
    (Kochi is COK, Delhi DEL, Mumbai BOM, Dubai DXB, London LHR). Dates are YYYY-MM-DD; give
    `return_date` for a round trip. Prices are in the platform's currency, for all
    passengers. If the user has not said when they want to fly, ask with ask_for_details
    instead of guessing a date."""
    service = "Google Flights"
    start, end = _airport(origin), _airport(destination)
    if start == end:
        raise ToolError("The origin and destination must be different airports.")
    leaves = parse_date(departure_date, "departure")
    if return_date and parse_date(return_date, "return") < leaves:
        raise ToolError("The return date can't be before the departure date.")
    if not 1 <= passengers <= 9:
        raise ToolError("Choose between 1 and 9 passengers.")
    check_price_range(None, max_price)
    settings = get_settings()
    data = await search(
        service, "google_flights", departure_id=start, arrival_id=end, outbound_date=departure_date,
        return_date=return_date or None, type=1 if return_date else 2, adults=passengers,
        travel_class=_TRAVEL_CLASS[travel_class], stops=_STOPS.get(stops),
        max_price=None if max_price is None else int(max_price),
        currency=settings.default_currency, gl=settings.default_country.lower(), hl="en",
    )
    options = ((data.get("best_flights") or []) + (data.get("other_flights") or []))[:MAX_RESULTS]
    if not options:
        return no_results(service)
    insights = data.get("price_insights") or {}
    return wrap(service, {
        "currency": settings.default_currency,
        **pick(insights, lowest_price="lowest_price", price_level="price_level"),
        "flights": [
            {
                "price": option.get("price"), "duration_minutes": option.get("total_duration"),
                "stops": max(len(option.get("flights") or []) - 1, 0), "trip": option.get("type"),
                "legs": [_leg(leg) for leg in option.get("flights") or []],
            }
            for option in options
        ],
    })
