"""Stock prices and company news from Finnhub."""
import datetime as dt

from langchain_core.tools import tool

from app.core.config import get_settings
from app.tools.http import MAX_RESULTS, ToolError, fetch_json, no_results, wrap

SERVICE = "Finnhub"
BASE_URL = "https://finnhub.io/api/v1"


async def _get(path: str, **params):
    return await fetch_json(SERVICE, f"{BASE_URL}/{path}", params=params, secret_params={"token": get_settings().finnhub_api_key})


@tool
async def get_stock_quote(symbol: str) -> str:
    """Get the latest price of a stock by its ticker symbol, such as AAPL or TSLA. If you only
    know the company's name, use find_stock_symbol first."""
    symbol = symbol.strip().upper()
    quote = await _get("quote", symbol=symbol)
    if not quote.get("c") and not quote.get("pc"):  # Finnhub answers an unknown symbol with zeros
        return no_results(SERVICE)
    return wrap(SERVICE, {
        "symbol": symbol, "price": quote["c"], "change": quote.get("d"), "change_percent": quote.get("dp"),
        "high": quote.get("h"), "low": quote.get("l"), "open": quote.get("o"), "previous_close": quote.get("pc"),
    })


@tool
async def find_stock_symbol(company: str) -> str:
    """Find a company's stock ticker symbol from its name."""
    data = await _get("search", q=company.strip())
    matches = [
        {"symbol": item.get("symbol"), "name": item.get("description"), "type": item.get("type")}
        for item in (data.get("result") or [])[:MAX_RESULTS]
    ]
    return wrap(SERVICE, matches) if matches else no_results(SERVICE)


@tool
async def get_company_news(symbol: str, days: int = 7) -> str:
    """Get recent news about a company by its ticker symbol, from the last 1 to 30 days."""
    if not 1 <= days <= 30:
        raise ToolError("Choose between 1 and 30 days of company news.")
    today = dt.date.today()
    items = await _get("company-news", symbol=symbol.strip().upper(), **{"from": (today - dt.timedelta(days=days)).isoformat()}, to=today.isoformat())
    news = [
        {
            "headline": item.get("headline"), "source": item.get("source"),
            "date": dt.datetime.fromtimestamp(item["datetime"], dt.UTC).date().isoformat() if item.get("datetime") else None,
            "link": item.get("url"), "summary": (item.get("summary") or "")[:200],
        }
        for item in (items or [])[:MAX_RESULTS]
    ]
    return wrap(SERVICE, news) if news else no_results(SERVICE)
