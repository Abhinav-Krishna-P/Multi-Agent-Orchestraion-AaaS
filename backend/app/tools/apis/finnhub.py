"""Stock prices and company news from Finnhub."""
import asyncio
import datetime as dt

from app.core.config import get_settings
from app.tools.http import MAX_RESULTS, ToolError, card_tool, fetch_json, no_results, pick, shown

SERVICE = "Finnhub"
BASE_URL = "https://finnhub.io/api/v1"


async def _get(path: str, **params):
    return await fetch_json(SERVICE, f"{BASE_URL}/{path}", params=params, secret_params={"token": get_settings().finnhub_api_key})


async def _profile(symbol: str) -> dict:
    """The company behind a symbol: name, logo, currency. The quote is still useful without it."""
    try:
        profile = await _get("stock/profile2", symbol=symbol)
    except ToolError:
        return {}
    return profile if isinstance(profile, dict) else {}


@card_tool
async def get_stock_quote(symbol: str) -> tuple[str, dict | None]:
    """Get the latest price of a stock by its ticker symbol, such as AAPL or TSLA. If you only
    know the company's name, use find_stock_symbol first."""
    symbol = symbol.strip().upper()
    quote, profile = await asyncio.gather(_get("quote", symbol=symbol), _profile(symbol))
    if not quote.get("c") and not quote.get("pc"):  # Finnhub answers an unknown symbol with zeros
        return no_results(SERVICE)
    result = {
        "symbol": symbol, "price": quote["c"], "change": quote.get("d"), "change_percent": quote.get("dp"),
        "high": quote.get("h"), "low": quote.get("l"), "open": quote.get("o"), "previous_close": quote.get("pc"),
        **pick(profile, name="name", currency="currency", exchange="exchange"),
    }
    return shown(
        SERVICE, result, "quote", **result, **pick(quote, time="t"),
        **pick(profile, logo="logo", industry="finnhubIndustry", website="weburl", market_cap_millions="marketCapitalization"),
    )


@card_tool
async def find_stock_symbol(company: str) -> tuple[str, dict | None]:
    """Find a company's stock ticker symbol from its name."""
    data = await _get("search", q=company.strip())
    matches = [
        {"symbol": item.get("symbol"), "name": item.get("description"), "type": item.get("type")}
        for item in (data.get("result") or [])[:MAX_RESULTS]
    ]
    return shown(SERVICE, matches, "symbols", items=matches) if matches else no_results(SERVICE)


@card_tool
async def get_company_news(symbol: str, days: int = 7) -> tuple[str, dict | None]:
    """Get recent news about a company by its ticker symbol, from the last 1 to 30 days."""
    if not 1 <= days <= 30:
        raise ToolError("Choose between 1 and 30 days of company news.")
    today = dt.date.today()
    items = await _get("company-news", symbol=symbol.strip().upper(), **{"from": (today - dt.timedelta(days=days)).isoformat()}, to=today.isoformat())
    news = [
        {
            "headline": item.get("headline"), "source": item.get("source"),
            "date": dt.datetime.fromtimestamp(item["datetime"], dt.UTC).date().isoformat() if item.get("datetime") else None,
            "link": item.get("url"), "summary": (item.get("summary") or "")[:200], "image": item.get("image"),
        }
        for item in (items or [])[:MAX_RESULTS]
    ]
    if not news:
        return no_results(SERVICE)
    return shown(
        SERVICE, [{key: value for key, value in item.items() if key != "image"} for item in news], "links",
        items=[pick(item, title="headline", link="link", snippet="summary", source="source", date="date", image="image") for item in news],
    )
