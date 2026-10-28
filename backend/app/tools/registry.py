"""Every tool the platform writes itself. An agent is only given the ones its owner switched on.

To add a tool: write it, then register() it here with the words the user sees.
"""
from dataclasses import dataclass

from langchain_core.tools import BaseTool

from app.core.config import get_settings
from app.tools.apis import finnhub, frankfurter, open_meteo, serpapi, serper
from app.tools.builtin import calculator, get_current_datetime
from app.tools.forms import FormField


@dataclass(frozen=True)
class ToolSpec:
    name: str  # what the model calls; must equal tool.name
    label: str  # what the user sees in the wizard
    description: str  # one line for the wizard (the model reads the tool's own docstring)
    group: str  # heading in the wizard, by what the tool does
    activity: str  # shown in chat while it runs
    tool: BaseTool
    app: str = ""  # the service the user knows it by ("Google Flights"); its card and logo in the wizard
    access: str = "read"  # "write" tools will need approval in stage 3
    requires: str | None = None  # the setting holding the platform key this tool needs
    form: tuple[FormField, ...] = ()  # the details dialog, for tools with filters


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    assert spec.name == spec.tool.name and spec.name not in REGISTRY, spec.name
    REGISTRY[spec.name] = spec


def available(spec: ToolSpec) -> bool:
    """False while the platform key a tool needs is missing from the server's settings."""
    return spec.requires is None or bool(getattr(get_settings(), spec.requires))


def catalog() -> dict:
    """The usable tools grouped for the wizard, in the order they were registered."""
    groups: dict[str, list[dict]] = {}
    for spec in REGISTRY.values():
        if available(spec):
            groups.setdefault(spec.group, []).append(
                {"name": spec.name, "label": spec.label, "description": spec.description, "app": spec.app}
            )
    return {"groups": [{"name": name, "tools": tools} for name, tools in groups.items()]}


# The service each tool belongs to, as the user knows it. Tools of one service share a card
# and a logo in the wizard.
_APPS = {
    "calculator": "Calculator", "get_current_datetime": "Clock",
    "web_search": "Google Search", "search_books": "Google Books", "search_images": "Google Images",
    "translate_text": "Google Translate", "search_news": "Google News", "find_places": "Google Maps",
    "search_products": "Google Shopping", "search_flights": "Google Flights",
    "get_current_weather": "Open-Meteo", "get_weather_forecast": "Open-Meteo",
    "convert_currency": "Frankfurter", "get_exchange_rates": "Frankfurter",
    "get_stock_quote": "Finnhub", "find_stock_symbol": "Finnhub", "get_company_news": "Finnhub",
    "search_stays": "Airbnb", "search_amazon": "Amazon",
}


def _add(tool: BaseTool, label: str, description: str, group: str, activity: str, **extra) -> None:
    register(ToolSpec(tool.name, label, description, group, activity, tool, app=_APPS[tool.name], **extra))


_PRICES = (FormField("min_price", "Minimum price", "number"), FormField("max_price", "Maximum price", "number"))
_COUNTRY = FormField("country", "Country code (such as in, us)")

# --- Basics ---
_add(calculator, "Calculator", "Works out arithmetic exactly.", "Basics", "Calculating…")
_add(get_current_datetime, "Current date and time", "Tells the agent today's date and the time in any time zone.",
     "Basics", "Checking the date and time…")

# --- Search and knowledge ---
_add(serpapi.web_search, "Web search", "Searches Google for current information and websites.",
     "Search and knowledge", "Searching the web…", requires="serpapi_api_key")
_add(serpapi.search_books, "Book search", "Finds books by title, author or subject.",
     "Search and knowledge", "Searching books…", requires="serpapi_api_key")
_add(serper.search_images, "Image search", "Finds images and the pages they are on.",
     "Search and knowledge", "Searching images…", requires="serper_api_key")
_add(serpapi.translate_text, "Translate text", "Translates text between languages.",
     "Search and knowledge", "Translating…", requires="serpapi_api_key")

# --- Weather ---
_add(open_meteo.get_current_weather, "Current weather", "Tells the weather right now in any place.",
     "Weather", "Checking the weather…")
_add(open_meteo.get_weather_forecast, "Weather forecast", "Gives the forecast for the next 1 to 7 days.",
     "Weather", "Checking the forecast…")

# --- News ---
_add(serper.search_news, "News search", "Finds recent news on any topic.", "News", "Searching the news…",
     requires="serper_api_key",
     form=(FormField("query", "Topic", required=True),
           FormField("time_range", "From the past", "select",
                     (("any", "Any time"), ("day", "Day"), ("week", "Week"), ("month", "Month"))),
           _COUNTRY))

# --- Money and markets ---
_add(frankfurter.convert_currency, "Currency conversion", "Converts an amount between currencies at today's rate.",
     "Money and markets", "Converting currency…")
_add(frankfurter.get_exchange_rates, "Exchange rates", "Gives the latest exchange rates for a currency.",
     "Money and markets", "Checking exchange rates…")
_add(finnhub.get_stock_quote, "Stock quote", "Gives a stock's latest price.",
     "Money and markets", "Checking the stock price…", requires="finnhub_api_key")
_add(finnhub.find_stock_symbol, "Find a stock symbol", "Finds a company's ticker symbol from its name.",
     "Money and markets", "Looking up the stock symbol…", requires="finnhub_api_key")
_add(finnhub.get_company_news, "Company news", "Finds recent news about a listed company.",
     "Money and markets", "Checking company news…", requires="finnhub_api_key")

# --- Travel ---
_add(serpapi.search_stays, "Stays search (Airbnb)", "Finds places to stay, with dates, guests and budget.",
     "Travel", "Searching stays…", requires="serpapi_api_key",
     form=(FormField("location", "Where", required=True),
           FormField("check_in", "Check-in", "date"), FormField("check_out", "Check-out", "date"),
           FormField("guests", "Guests", "number"),
           FormField("room_type", "Room type", "select",
                     (("any", "Any"), ("entire_home", "Entire home"), ("private_room", "Private room"))),
           FormField("min_price", "Minimum price per night", "number"),
           FormField("max_price", "Maximum price per night", "number")))
_add(serpapi.search_flights, "Flight search (Google Flights)", "Finds flights and fares between two cities.",
     "Travel", "Searching flights…", requires="serpapi_api_key",
     form=(FormField("origin", "From (airport code, such as COK)", required=True),
           FormField("destination", "To (airport code, such as DEL)", required=True),
           FormField("departure_date", "Departure", "date", required=True),
           FormField("return_date", "Return", "date"),
           FormField("passengers", "Passengers", "number"),
           FormField("travel_class", "Class", "select",
                     (("economy", "Economy"), ("premium_economy", "Premium economy"),
                      ("business", "Business"), ("first", "First"))),
           FormField("stops", "Stops", "select",
                     (("any", "Any"), ("nonstop", "Non-stop only"), ("one_or_fewer", "One stop or fewer"))),
           FormField("max_price", "Maximum price", "number")))

# --- Places ---
_add(serper.find_places, "Find places", "Finds restaurants, shops and other places with ratings and contact details.",
     "Places", "Searching places…", requires="serper_api_key",
     form=(FormField("query", "What are you looking for", required=True), FormField("location", "City or area")))

# --- Shopping ---
_add(serper.search_products, "Product search (Google Shopping)", "Compares a product's prices across stores.",
     "Shopping", "Searching products…", requires="serper_api_key",
     form=(FormField("query", "Product", required=True), *_PRICES, _COUNTRY))
_add(serpapi.search_amazon, "Amazon product search", "Finds products on Amazon with prices and ratings.",
     "Shopping", "Searching Amazon…", requires="serpapi_api_key",
     form=(FormField("query", "Product", required=True),
           FormField("marketplace", "Amazon site", "select",
                     (("amazon.in", "Amazon India"), ("amazon.com", "Amazon US"), ("amazon.co.uk", "Amazon UK"),
                      ("amazon.ae", "Amazon UAE"), ("amazon.de", "Amazon Germany"), ("amazon.ca", "Amazon Canada"),
                      ("amazon.com.au", "Amazon Australia"))),
           FormField("sort", "Sort by", "select",
                     (("relevance", "Relevance"), ("price_low_to_high", "Price: low to high"),
                      ("price_high_to_low", "Price: high to low"), ("rating", "Rating"), ("newest", "Newest"))),
           *_PRICES))
