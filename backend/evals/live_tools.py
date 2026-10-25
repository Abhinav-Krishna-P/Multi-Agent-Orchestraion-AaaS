"""One real call to every outside-service tool, with the real keys. Run by hand:

    python -m evals.live_tools            (from the backend directory)

Each call spends a little of the platform's quota. Prints the start of each result.
"""
import asyncio
import datetime as dt
import sys

from app.tools.http import ToolError
from app.tools.registry import REGISTRY, available

IN_30 = (dt.date.today() + dt.timedelta(days=30)).isoformat()
IN_32 = (dt.date.today() + dt.timedelta(days=32)).isoformat()

CALLS = {
    "get_current_weather": {"location": "Kochi"},
    "get_weather_forecast": {"location": "Kochi", "days": 2},
    "convert_currency": {"amount": 100, "from_currency": "USD", "to_currency": "INR"},
    "get_exchange_rates": {"base_currency": "USD", "currencies": ["INR", "EUR"]},
    "get_stock_quote": {"symbol": "AAPL"},
    "find_stock_symbol": {"company": "Infosys"},
    "get_company_news": {"symbol": "AAPL", "days": 5},
    "search_flights": {"origin": "COK", "destination": "DEL", "departure_date": IN_30, "stops": "nonstop"},
    "web_search": {"query": "who won the last cricket world cup"},
    "search_books": {"query": "atomic habits"},
    "search_images": {"query": "kerala backwaters"},
    "translate_text": {"text": "Good morning, how are you?", "target_language": "ml"},
    "search_news": {"query": "Kerala", "time_range": "week"},
    "find_places": {"query": "cafes", "location": "Kochi, Kerala"},
    "search_stays": {"location": "Goa", "check_in": IN_30, "check_out": IN_32, "guests": 2,
                     "room_type": "entire_home", "max_price": 8000},
    "search_products": {"query": "running shoes", "min_price": 1000, "max_price": 4000},
    "search_amazon": {"query": "wireless mouse", "sort": "price_low_to_high", "max_price": 1500},
}


async def main() -> int:
    failed = 0
    for name, args in CALLS.items():
        spec = REGISTRY[name]
        if not available(spec):
            print(f"-- {name}: skipped, its key is not set")
            continue
        try:
            result = await spec.tool.ainvoke(args)
            status = "ok"
        except ToolError as error:
            result, status, failed = str(error), "FAILED", failed + 1
        except Exception as error:  # a bug in the tool, not a service problem
            result, status, failed = f"{type(error).__name__}: {error}", "BUG", failed + 1
        print(f"-- {name}: {status}\n   {result[:330]}")
    return failed


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
