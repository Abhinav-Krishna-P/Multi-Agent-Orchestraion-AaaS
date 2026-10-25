"""Exchange rates. Frankfurter (European Central Bank data, no key) first; if it does not
answer, Google's currency converter through SerpApi."""
import re

from langchain_core.tools import tool

from app.tools.apis import serpapi
from app.tools.http import ToolError, fetch_json, wrap

URL = "https://api.frankfurter.dev/v1/latest"
FALLBACK_CURRENCIES = ("USD", "EUR", "GBP", "INR", "JPY", "AED")
MAX_FALLBACK = 6  # each fallback rate is one paid search


def _code(value: str) -> str:
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ToolError(f"'{value}' isn't a currency code. Use three letters, such as USD, EUR or INR.")
    return code


async def _rates(base: str, quotes: list[str] | None) -> tuple[dict[str, float], str]:
    """Rates for one unit of `base`, and where they came from."""
    try:
        data = await fetch_json("Frankfurter", URL, params={"base": base, **({"symbols": ",".join(quotes)} if quotes else {})})
        if data.get("rates"):
            return data["rates"], "Frankfurter"
    except ToolError:
        pass  # fall through to Google
    rates = {}
    for quote in (quotes or [c for c in FALLBACK_CURRENCIES if c != base])[:MAX_FALLBACK]:
        box = (await serpapi.search("Google", "google", q=f"1 {base} to {quote}")).get("answer_box") or {}
        if box.get("type") == "currency_converter" and box.get("price"):
            rates[quote] = box["price"]
    if not rates:
        raise ToolError("I couldn't get an exchange rate for those currencies right now.")
    return rates, "Google"


@tool
async def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount of money from one currency to another at the latest exchange rate.
    Currencies are three-letter codes such as USD, EUR, INR."""
    if amount <= 0:
        raise ToolError("Give an amount greater than zero.")
    base, quote = _code(from_currency), _code(to_currency)
    rates, source = await _rates(base, [quote])
    if quote not in rates:
        raise ToolError("I couldn't get an exchange rate for those currencies right now.")
    return wrap(source, {"amount": amount, "from": base, "to": quote, "rate": rates[quote],
                         "result": round(amount * rates[quote], 2), "source": source})


@tool
async def get_exchange_rates(base_currency: str, currencies: list[str] | None = None) -> str:
    """Get the latest exchange rates for one unit of a currency against others. Currencies are
    three-letter codes; leave `currencies` out for the main ones."""
    base = _code(base_currency)
    quotes = [_code(c) for c in currencies] if currencies else None
    rates, source = await _rates(base, quotes)
    return wrap(source, {"base": base, "rates": rates, "source": source})
