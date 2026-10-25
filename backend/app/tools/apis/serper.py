"""Google News, Images, Places and Shopping through Serper."""
import re
from typing import Literal

from langchain_core.tools import tool

from app.core.config import get_settings
from app.tools.http import MAX_RESULTS, check_price_range, fetch_json, in_price_range, no_results, pick, wrap

BASE_URL = "https://google.serper.dev"
_TIME_RANGES = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m"}


async def _search(service: str, path: str, *, country: str | None = None, num: int = MAX_RESULTS, **body) -> dict:
    settings = get_settings()
    body = {"q": body.pop("q").strip(), "gl": (country or settings.default_country).lower(), "num": num,
            **{key: value for key, value in body.items() if value}}
    return await fetch_json(service, f"{BASE_URL}/{path}", method="POST", json=body, headers={"X-API-KEY": settings.serper_api_key})


def _amount(price: str | None) -> float | None:
    """The number inside a price such as "₹1,499.00"; None when there isn't one."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", price or "")
    return float(match.group().replace(",", "")) if match else None


@tool
async def search_images(query: str) -> str:
    """Search Google Images. Returns links to images and the pages they are on."""
    service = "Google Images"
    data = await _search(service, "images", q=query)
    images = [pick(item, title="title", image="imageUrl", page="link", source="source") for item in (data.get("images") or [])[:MAX_RESULTS]]
    return wrap(service, images) if images else no_results(service)


@tool
async def search_news(
    query: str, time_range: Literal["any", "day", "week", "month"] = "any", country: str | None = None
) -> str:
    """Search Google News for recent news on a topic. `time_range` limits it to the past day,
    week or month. `country` is a two-letter code such as "in" or "us"."""
    service = "Google News"
    data = await _search(service, "news", q=query, country=country, tbs=_TIME_RANGES.get(time_range))
    news = [pick(item, title="title", source="source", date="date", link="link", snippet="snippet") for item in (data.get("news") or [])[:MAX_RESULTS]]
    return wrap(service, news) if news else no_results(service)


@tool
async def find_places(query: str, location: str | None = None) -> str:
    """Find places and businesses, such as restaurants, cafes, hospitals or shops, with their
    address, rating and contact details. `query` is the kind of place; `location` is the
    city or area to look in."""
    service = "Google Places"
    data = await _search(service, "places", q=query, location=(location or "").strip())
    places = [
        pick(item, name="title", address="address", rating="rating", reviews="ratingCount",
             category="category", phone="phoneNumber", website="website")
        for item in (data.get("places") or [])[:MAX_RESULTS]
    ]
    return wrap(service, places) if places else no_results(service)


@tool
async def search_products(
    query: str, min_price: float | None = None, max_price: float | None = None, country: str | None = None
) -> str:
    """Search Google Shopping to compare a product's prices across stores. Prices are in the
    country's currency. `country` is a two-letter code such as "in" or "us"."""
    service = "Google Shopping"
    check_price_range(min_price, max_price)
    data = await _search(service, "shopping", q=query, country=country, num=40)
    # Serper has no price filter, so 40 results are fetched and the range is applied here.
    products = [
        pick(item, title="title", price="price", store="source", rating="rating", reviews="ratingCount", link="link")
        for item in data.get("shopping") or []
        if in_price_range(_amount(item.get("price")), min_price, max_price)
    ][:MAX_RESULTS]
    return wrap(service, products) if products else no_results(service)
