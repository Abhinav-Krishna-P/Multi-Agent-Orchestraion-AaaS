"""Google News, Images, Places and Shopping through Serper."""
import re
from typing import Literal

from app.core.config import get_settings
from app.tools.http import (
    LIST_RESULTS, MAX_RESULTS, card_tool, check_price_range, fetch_json, in_price_range, no_results, pick, shown,
)

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


@card_tool
async def search_images(query: str) -> tuple[str, dict | None]:
    """Search Google Images. Returns links to images and the pages they are on."""
    service = "Google Images"
    data = await _search(service, "images", q=query, num=LIST_RESULTS)
    found = (data.get("images") or [])[:LIST_RESULTS]
    if not found:
        return no_results(service)
    images = [pick(item, title="title", image="imageUrl", page="link", source="source") for item in found]
    return shown(service, images, "images", items=[
        pick(item, title="title", image="imageUrl", thumbnail="thumbnailUrl", source="source", link="link") for item in found
    ])


@card_tool
async def search_news(
    query: str, time_range: Literal["any", "day", "week", "month"] = "any", country: str | None = None
) -> tuple[str, dict | None]:
    """Search Google News for recent news on a topic. `time_range` limits it to the past day,
    week or month. `country` is a two-letter code such as "in" or "us"."""
    service = "Google News"
    data = await _search(service, "news", q=query, country=country, tbs=_TIME_RANGES.get(time_range))
    found = (data.get("news") or [])[:MAX_RESULTS]
    if not found:
        return no_results(service)
    news = [pick(item, title="title", source="source", date="date", link="link", snippet="snippet") for item in found]
    return shown(service, news, "links", items=[
        pick(item, title="title", source="source", date="date", link="link", snippet="snippet", image="imageUrl") for item in found
    ])


def _place_card(item: dict) -> dict:
    card = pick(item, name="title", title="title", address="address", latitude="latitude", longitude="longitude",
                rating="rating", reviews="ratingCount", price_level="priceLevel", category="category",
                phone="phoneNumber", website="website")
    if item.get("cid"):
        card["link"] = f"https://www.google.com/maps?cid={item['cid']}"
    return card


@card_tool
async def find_places(query: str, location: str | None = None) -> tuple[str, dict | None]:
    """Find places and businesses, such as restaurants, cafes, hospitals or shops, with their
    address, rating and contact details. `query` is the kind of place; `location` is the
    city or area to look in."""
    service = "Google Places"
    data = await _search(service, "places", q=query, location=(location or "").strip())
    found = (data.get("places") or [])[:MAX_RESULTS]
    if not found:
        return no_results(service)
    places = [
        pick(item, name="title", address="address", rating="rating", reviews="ratingCount",
             category="category", phone="phoneNumber", website="website")
        for item in found
    ]
    return shown(service, places, "places", items=[_place_card(item) for item in found])


@card_tool
async def search_products(
    query: str, min_price: float | None = None, max_price: float | None = None, country: str | None = None
) -> tuple[str, dict | None]:
    """Search Google Shopping to compare a product's prices across stores. Prices are in the
    country's currency. `country` is a two-letter code such as "in" or "us"."""
    service = "Google Shopping"
    check_price_range(min_price, max_price)
    data = await _search(service, "shopping", q=query, country=country, num=40)
    # Serper has no price filter, so 40 results are fetched and the range is applied here.
    found = [
        item for item in data.get("shopping") or [] if in_price_range(_amount(item.get("price")), min_price, max_price)
    ][:LIST_RESULTS]
    if not found:
        return no_results(service)
    products = [pick(item, title="title", price="price", store="source", rating="rating", reviews="ratingCount", link="link")
                for item in found]
    return shown(service, products, "products", items=[
        pick(item, title="title", image="imageUrl", price="price", store="source", rating="rating",
             reviews="ratingCount", link="link")
        for item in found
    ])
