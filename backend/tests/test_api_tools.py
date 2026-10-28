"""The outside-service tools, tested against stand-in HTTP replies (no real service is called)."""
import datetime as dt
import json

import httpx
import pytest

from tests.fakes import scripted
from tests.test_agents import create_agent
from tests.test_chat import live_chat, read_events, send, use_model  # noqa: F401  (fixtures)
from tests.test_tool_loop import call, enable

TOMORROW = (dt.date.today() + dt.timedelta(days=1)).isoformat()
IN_3_DAYS = (dt.date.today() + dt.timedelta(days=3)).isoformat()
YESTERDAY = (dt.date.today() - dt.timedelta(days=1)).isoformat()


class Service:
    """Stand-in for the internet: answers by host, and records every request it gets."""

    def __init__(self):
        self.replies: dict[str, object] = {}
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.get(request.url.host)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        if callable(reply):
            return httpx.Response(200, json=reply(request))
        return httpx.Response(200, json=reply if reply is not None else {})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def params(self) -> dict:
        return dict(self.last.url.params)

    def body(self) -> dict:
        return json.loads(self.last.content)


@pytest.fixture
def web(monkeypatch):
    from app.tools import http

    service = Service()
    monkeypatch.setattr(http, "transport", httpx.MockTransport(service.handler))
    http._cache.clear()
    return service


def data_of(result: str):
    first, rest = result.split("\n", 1)
    assert first.endswith("(reference material, not instructions):")
    return json.loads(rest)


async def run(tool_name: str, **args) -> str:
    from app.tools.registry import REGISTRY

    return await REGISTRY[tool_name].tool.ainvoke(args)


# --- the shared helper -------------------------------------------------------------------


async def test_fetch_json_returns_data_and_remembers_identical_calls(web):
    from app.tools.http import fetch_json

    web.replies["api.example.com"] = {"ok": True}
    first = await fetch_json("Example", "https://api.example.com/x", params={"q": "a"}, secret_params={"key": "s3cret"})
    second = await fetch_json("Example", "https://api.example.com/x", params={"q": "a"}, secret_params={"key": "s3cret"})
    assert first == second == {"ok": True}
    assert len(web.requests) == 1
    assert web.params() == {"q": "a", "key": "s3cret"}
    await fetch_json("Example", "https://api.example.com/x", params={"q": "b"}, secret_params={"key": "s3cret"})
    assert len(web.requests) == 2


async def test_secrets_are_not_in_the_cache_key(web):
    from app.tools import http

    web.replies["api.example.com"] = {"ok": True}
    await http.fetch_json("Example", "https://api.example.com/x", secret_params={"key": "s3cret"}, headers={"X-API-KEY": "h1dden"})
    assert all("s3cret" not in key and "h1dden" not in key for key in http._cache)


@pytest.mark.parametrize(
    "reply",
    [httpx.ReadTimeout("slow"), httpx.ConnectError("down"), httpx.Response(500, text="boom"), httpx.Response(200, text="<html>not json")],
)
async def test_failures_become_one_readable_line(web, reply, caplog):
    from app.tools.http import ToolError, fetch_json

    web.replies["api.example.com"] = reply
    with pytest.raises(ToolError) as caught:
        await fetch_json("Example", "https://api.example.com/x", secret_params={"key": "s3cret"})
    assert str(caught.value) == "Example could not be reached right now."
    assert "s3cret" not in caplog.text
    web.replies["api.example.com"] = {"ok": True}  # a failure is never remembered
    assert await fetch_json("Example", "https://api.example.com/x", secret_params={"key": "s3cret"}) == {"ok": True}


# --- keys and the catalog -----------------------------------------------------------------


async def test_catalog_groups_the_new_tools(client, user_a):
    groups = {g["name"]: [t["name"] for t in g["tools"]] for g in (await client.get("/tools", headers=user_a)).json()["groups"]}
    assert groups["Weather"] == ["get_current_weather", "get_weather_forecast"]
    assert groups["Travel"] == ["search_stays", "search_flights"]
    assert {"web_search", "search_books", "search_images", "translate_text"} <= set(groups["Search and knowledge"])
    assert {"convert_currency", "get_exchange_rates", "get_stock_quote", "find_stock_symbol", "get_company_news"} <= set(groups["Money and markets"])
    assert groups["News"] == ["search_news"] and groups["Places"] == ["find_places"]
    assert groups["Shopping"] == ["search_products", "search_amazon"]
    assert "ask_for_details" not in sum(groups.values(), [])


async def test_tool_without_its_key_is_hidden_and_unusable(client, user_a, live_chat, use_model, monkeypatch):  # noqa: F811
    from app.core.config import get_settings

    agent, session = live_chat
    await enable(client, user_a, agent, "search_news", "calculator")
    monkeypatch.setattr(get_settings(), "serper_api_key", "")
    names = [t["name"] for g in (await client.get("/tools", headers=user_a)).json()["groups"] for t in g["tools"]]
    assert "search_news" not in names and "find_places" not in names and "web_search" in names
    # A tool the agent does not have yet cannot be switched on without its key...
    r = await client.put(f"/agents/{agent['id']}/tools", json={"tools": ["find_places"]}, headers=user_a)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_tools"
    # ...but the wizard resubmits what the agent already has, and that must still save.
    r = await client.put(f"/agents/{agent['id']}/tools", json={"tools": ["search_news", "calculator"]}, headers=user_a)
    assert r.status_code == 200 and r.json()["tools"] == ["calculator", "search_news"]
    model = scripted(["Hello."])
    use_model(model)
    await send(client, user_a, session["id"], {"message": "Hi"})
    assert model.bound == ["calculator"]  # the agent still lists search_news, but it is not offered


async def test_tool_error_reaches_the_model_in_plain_words(client, user_a, live_chat, use_model, web):  # noqa: F811
    agent, session = live_chat
    await enable(client, user_a, agent, "get_stock_quote")
    web.replies["finnhub.io"] = httpx.Response(503, text="down")
    model = scripted(call("get_stock_quote", symbol="AAPL"), ["I couldn't check that right now."])
    use_model(model)
    r = await send(client, user_a, session["id"], {"message": "Apple price?"})
    events = read_events(r.text)
    assert events[0][1]["label"] == "Checking the stock price…" and events[1][1]["ok"] is False
    assert model.received[1][-1].content == "Finnhub could not be reached right now."
    assert events[-1][1]["message_id"]


# --- weather (Open-Meteo) ---------------------------------------------------------------------


def _open_meteo(request: httpx.Request):
    if request.url.host == "geocoding-api.open-meteo.com":
        if request.url.params["name"] == "Nowhereville":
            return {}
        return {"results": [{"name": "Kochi", "country": "India", "admin1": "Kerala", "latitude": 9.93, "longitude": 76.26}]}
    return {
        "timezone": "Asia/Kolkata",
        "current": {"time": "2026-11-18T10:00", "temperature_2m": 29.4, "relative_humidity_2m": 70, "wind_speed_10m": 9.1, "weather_code": 61},
        "daily": {
            "time": ["2026-11-18", "2026-11-19"], "weather_code": [61, 2],
            "temperature_2m_max": [31.0, 32.5], "temperature_2m_min": [24.0, 24.5], "precipitation_probability_max": [80, 20],
        },
    }


@pytest.fixture
def weather(web):
    web.replies["geocoding-api.open-meteo.com"] = _open_meteo
    web.replies["api.open-meteo.com"] = _open_meteo
    return web


async def test_current_weather(weather):
    data = data_of(await run("get_current_weather", location="Kochi"))
    assert data["place"] == "Kochi, Kerala, India"
    assert data["temperature_c"] == 29.4 and data["humidity_percent"] == 70 and data["wind_kmh"] == 9.1
    assert data["conditions"] == "Rain"
    assert weather.params()["latitude"] == "9.93" and "temperature_2m" in weather.params()["current"]


async def test_forecast_days(weather):
    data = data_of(await run("get_weather_forecast", location="Kochi", days=2))
    assert weather.params()["forecast_days"] == "2"
    assert data["days"][0] == {"date": "2026-11-18", "conditions": "Rain", "high_c": 31.0, "low_c": 24.0, "rain_chance_percent": 80}
    assert len(data["days"]) == 2


@pytest.mark.parametrize("days", [0, 8, -1])
async def test_forecast_days_out_of_range_refused_before_any_request(weather, days):
    from app.tools.http import ToolError

    with pytest.raises(ToolError, match="between 1 and 7"):
        await run("get_weather_forecast", location="Kochi", days=days)
    assert weather.requests == []


async def test_unknown_place(weather):
    from app.tools.http import ToolError

    with pytest.raises(ToolError, match="couldn't find a place called 'Nowhereville'"):
        await run("get_current_weather", location="Nowhereville")


# --- currency (Frankfurter) -------------------------------------------------------------------


async def test_convert_currency(web):
    web.replies["api.frankfurter.dev"] = {"amount": 1.0, "base": "USD", "date": "2026-11-18", "rates": {"INR": 88.5}}
    data = data_of(await run("convert_currency", amount=200, from_currency="usd", to_currency="inr"))
    assert web.params() == {"base": "USD", "symbols": "INR"}
    assert data == {"amount": 200, "from": "USD", "to": "INR", "rate": 88.5, "result": 17700.0, "source": "Frankfurter"}


async def test_exchange_rates(web):
    web.replies["api.frankfurter.dev"] = {"base": "EUR", "date": "2026-11-18", "rates": {"USD": 1.1, "INR": 97.0}}
    data = data_of(await run("get_exchange_rates", base_currency="eur", currencies=["usd", "inr"]))
    assert web.params() == {"base": "EUR", "symbols": "USD,INR"}
    assert data == {"base": "EUR", "rates": {"USD": 1.1, "INR": 97.0}, "source": "Frankfurter"}


def _google_rate(request: httpx.Request):
    """SerpApi's Google reply to a "1 USD to INR" search."""
    quote = request.url.params["q"].split(" to ")[1]
    return {"answer_box": {"type": "currency_converter", "price": {"INR": 93.44, "EUR": 0.86}[quote], "currency": quote}}


async def test_currency_falls_back_to_google_when_frankfurter_is_down(web):
    web.replies["api.frankfurter.dev"] = httpx.ReadTimeout("slow")
    web.replies["serpapi.com"] = _google_rate
    data = data_of(await run("convert_currency", amount=10, from_currency="USD", to_currency="INR"))
    assert data == {"amount": 10, "from": "USD", "to": "INR", "rate": 93.44, "result": 934.4, "source": "Google"}
    assert web.params()["q"] == "1 USD to INR" and web.params()["engine"] == "google"
    data = data_of(await run("get_exchange_rates", base_currency="USD", currencies=["INR", "EUR"]))
    assert data == {"base": "USD", "rates": {"INR": 93.44, "EUR": 0.86}, "source": "Google"}


async def test_currency_fails_readably_when_both_sources_are_down(web):
    from app.tools.http import ToolError

    web.replies["api.frankfurter.dev"] = httpx.ReadTimeout("slow")
    web.replies["serpapi.com"] = {"organic_results": []}  # no currency answer in the reply
    with pytest.raises(ToolError, match="exchange rate"):
        await run("convert_currency", amount=10, from_currency="USD", to_currency="INR")


async def test_exchange_rates_without_a_list_needs_frankfurter(web):
    web.replies["api.frankfurter.dev"] = {"base": "USD", "rates": {f"C{i:02d}"[:3].upper(): float(i) for i in range(30)}}
    data = data_of(await run("get_exchange_rates", base_currency="USD"))
    assert "symbols" not in web.params() and len(data["rates"]) == 30


@pytest.mark.parametrize(
    "args", [{"amount": 0, "from_currency": "USD", "to_currency": "INR"}, {"amount": -5, "from_currency": "USD", "to_currency": "INR"},
             {"amount": 5, "from_currency": "DOLLARS", "to_currency": "INR"}, {"amount": 5, "from_currency": "USD", "to_currency": "1N"}],
)
async def test_bad_currency_arguments_refused(web, args):
    from app.tools.http import ToolError

    with pytest.raises(ToolError):
        await run("convert_currency", **args)
    assert web.requests == []


# --- stocks (Finnhub) ----------------------------------------------------------------------------


async def test_stock_quote_and_unknown_symbol(web):
    web.replies["finnhub.io"] = {"c": 190.5, "d": 1.5, "dp": 0.79, "h": 191.0, "l": 188.0, "o": 189.0, "pc": 189.0, "t": 1}
    data = data_of(await run("get_stock_quote", symbol="aapl"))
    assert web.params() == {"symbol": "AAPL", "token": "test-finnhub-key"}
    assert data == {"symbol": "AAPL", "price": 190.5, "change": 1.5, "change_percent": 0.79, "high": 191.0, "low": 188.0, "open": 189.0, "previous_close": 189.0}
    from app.tools import http

    http._cache.clear()
    web.replies["finnhub.io"] = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    assert await run("get_stock_quote", symbol="ZZZZ") == "Finnhub found no results."


async def test_find_symbol_and_company_news(web):
    web.replies["finnhub.io"] = {"count": 7, "result": [{"description": f"Tesla {i}", "displaySymbol": f"TSLA{i}", "symbol": f"TSLA{i}", "type": "Common Stock"} for i in range(7)]}
    data = data_of(await run("find_stock_symbol", company="tesla"))
    assert len(data) == 5 and data[0] == {"symbol": "TSLA0", "name": "Tesla 0", "type": "Common Stock"}
    web.replies["finnhub.io"] = lambda request: [
        {"headline": f"News {i}", "source": "Wire", "datetime": 1794900000, "url": f"https://n/{i}", "summary": "s" * 500, "image": "x"} for i in range(9)
    ]
    data = data_of(await run("get_company_news", symbol="aapl", days=3))
    assert len(data) == 5 and set(data[0]) == {"headline", "source", "date", "link", "summary"} and len(data[0]["summary"]) <= 200
    assert web.params()["symbol"] == "AAPL" and web.params()["to"] == dt.date.today().isoformat()
    assert web.params()["from"] == (dt.date.today() - dt.timedelta(days=3)).isoformat()


# --- SerpApi: web, books, translate, stays, Amazon ----------------------------------------------------


async def test_web_search(web):
    web.replies["serpapi.com"] = {
        "answer_box": {"answer": "Canberra", "extra": 1},
        "organic_results": [{"title": f"T{i}", "link": f"https://x/{i}", "snippet": f"S{i}", "position": i, "favicon": "f"} for i in range(8)],
    }
    data = data_of(await run("web_search", query="capital of australia"))
    assert web.params() == {"engine": "google", "q": "capital of australia", "gl": "in", "num": "5", "api_key": "test-serpapi-key"}
    assert data["answer"] == "Canberra" and len(data["results"]) == 5
    assert data["results"][0] == {"title": "T0", "link": "https://x/0", "snippet": "S0"}


async def test_serpapi_empty_and_error_replies(web):
    from app.tools.http import ToolError

    web.replies["serpapi.com"] = {"error": "Google hasn't returned any results for this query."}
    assert await run("web_search", query="asdfqwerzxcv") == "Google Search found no results."
    web.replies["serpapi.com"] = {"error": "Your account has run out of searches."}
    with pytest.raises(ToolError, match="Google Books could not be reached"):
        await run("search_books", query="atomic habits")


async def test_books_and_translate(web):
    web.replies["serpapi.com"] = {"organic_results": [{"title": "Atomic Habits", "authors": ["James Clear"], "date": "2018", "snippet": "s", "link": "https://b", "thumbnail": "t"}]}
    assert data_of(await run("search_books", query="atomic habits")) == [{"title": "Atomic Habits", "authors": ["James Clear"], "date": "2018", "snippet": "s", "link": "https://b"}]
    web.replies["serpapi.com"] = {"translation": {"source": {"language": "en"}, "target": {"text": "सुप्रभात", "language": "hi"}}}
    data = data_of(await run("translate_text", text="good morning", target_language="hi"))
    assert web.params()["engine"] == "google_translate" and web.params()["text"] == "good morning"
    assert web.params()["from"] == "auto" and web.params()["to"] == "hi"
    assert data == {"translation": "सुप्रभात", "from": "en", "to": "hi"}


async def test_translate_refuses_empty_and_huge_text(web):
    from app.tools.http import ToolError

    for text in ("   ", "x" * 5001):
        with pytest.raises(ToolError):
            await run("translate_text", text=text, target_language="hi")
    assert web.requests == []


def _stays(request):
    return {"organic_results": [
        {"title": f"Villa {i}", "price": f"₹{4000 + i} per night", "extracted_price": 4000 + i, "rating": 4.8, "reviews": 120,
         "link": f"https://air/{i}", "bedrooms": 2, "beds": 3, "images": ["a", "b"], "gps_coordinates": {}} for i in range(9)
    ]}


async def test_stays_simple_and_filtered(web):
    web.replies["serpapi.com"] = _stays
    data = data_of(await run("search_stays", location="Goa"))
    assert web.params() == {"engine": "airbnb", "q": "Goa", "adults": "1", "currency": "INR", "api_key": "test-serpapi-key"}
    assert len(data) == 5 and data[0] == {"title": "Villa 0", "price": "₹4000 per night", "rating": 4.8, "reviews": 120, "link": "https://air/0", "bedrooms": 2, "beds": 3}
    await run("search_stays", location="Goa", check_in=TOMORROW, check_out=IN_3_DAYS, guests=2, room_type="entire_home", min_price=2000, max_price=6000)
    sent = web.params()
    assert sent["check_in_date"] == TOMORROW and sent["check_out_date"] == IN_3_DAYS and sent["adults"] == "2"
    assert sent["room_type"] == "entire_home" and sent["min_price"] == "2000" and sent["max_price"] == "6000"


@pytest.mark.parametrize(
    "args, message",
    [
        ({"check_in": IN_3_DAYS, "check_out": TOMORROW}, "after the check-in"),
        ({"check_in": TOMORROW, "check_out": TOMORROW}, "after the check-in"),
        ({"check_in": YESTERDAY, "check_out": TOMORROW}, "in the past"),
        ({"check_in": TOMORROW}, "both a check-in and a check-out"),
        ({"check_in": "next friday", "check_out": TOMORROW}, "YYYY-MM-DD"),
        ({"guests": 0}, "at least 1"),
        ({"min_price": -1}, "can't be negative"),
        ({"min_price": 5000, "max_price": 1000}, "lower than the maximum"),
    ],
)
async def test_bad_stay_filters_refused_before_any_request(web, args, message):
    from app.tools.http import ToolError

    with pytest.raises(ToolError, match=message):
        await run("search_stays", location="Goa", **args)
    assert web.requests == []


async def test_amazon_sort_marketplace_and_local_price_filter(web):
    web.replies["serpapi.com"] = {"organic_results": [
        {"title": f"Mouse {i}", "price": f"₹{price}", "extracted_price": price, "rating": 4.2, "reviews": 50, "link": f"https://amz/{i}", "asin": "A"}
        for i, price in enumerate([300, 800, 1200, 2500, None, 950])
    ]}
    data = data_of(await run("search_amazon", query="wireless mouse", sort="price_low_to_high", min_price=500, max_price=1500))
    assert web.params() == {"engine": "amazon", "k": "wireless mouse", "amazon_domain": "amazon.in", "s": "price-asc-rank", "api_key": "test-serpapi-key"}
    assert [item["title"] for item in data] == ["Mouse 1", "Mouse 2", "Mouse 5"]  # only those inside the price range
    assert set(data[0]) == {"title", "price", "rating", "reviews", "link"}
    await run("search_amazon", query="wireless mouse", marketplace="amazon.com")
    assert web.params()["amazon_domain"] == "amazon.com" and "s" not in web.params()


# --- Serper: images, news, places, shopping ------------------------------------------------------------


async def test_images(web):
    web.replies["google.serper.dev"] = {"images": [{"title": f"I{i}", "imageUrl": f"https://img/{i}.jpg", "link": f"https://page/{i}", "source": "Site", "thumbnailUrl": "t"} for i in range(7)]}
    data = data_of(await run("search_images", query="kerala backwaters"))
    assert web.last.url.path == "/images" and web.last.headers["x-api-key"] == "test-serper-key"
    assert web.body() == {"q": "kerala backwaters", "gl": "in", "num": 5}
    assert len(data) == 5 and data[0] == {"title": "I0", "image": "https://img/0.jpg", "page": "https://page/0", "source": "Site"}


async def test_news_filters(web):
    web.replies["google.serper.dev"] = {"news": [{"title": "N", "source": "Wire", "date": "1 hour ago", "link": "https://n", "snippet": "s", "imageUrl": "i"}]}
    data = data_of(await run("search_news", query="kerala rain", time_range="week", country="us"))
    assert web.last.url.path == "/news" and web.body() == {"q": "kerala rain", "gl": "us", "num": 5, "tbs": "qdr:w"}
    assert data == [{"title": "N", "source": "Wire", "date": "1 hour ago", "link": "https://n", "snippet": "s"}]
    await run("search_news", query="kerala rain")
    assert web.body() == {"q": "kerala rain", "gl": "in", "num": 5}
    web.replies["google.serper.dev"] = {"news": []}
    assert await run("search_news", query="zzzz") == "Google News found no results."


async def test_places(web):
    web.replies["google.serper.dev"] = {"places": [{"title": "RD Cafe", "address": "NH66", "rating": 4.4, "ratingCount": 900, "category": "Cafe", "phoneNumber": "1", "website": "https://rd", "cid": "9", "latitude": 1}]}
    data = data_of(await run("find_places", query="cafes", location="Kochi, Kerala"))
    assert web.last.url.path == "/places" and web.body() == {"q": "cafes", "gl": "in", "num": 5, "location": "Kochi, Kerala"}
    assert data == [{"name": "RD Cafe", "address": "NH66", "rating": 4.4, "reviews": 900, "category": "Cafe", "phone": "1", "website": "https://rd"}]


async def test_products_price_range_is_applied_to_the_results(web):
    web.replies["google.serper.dev"] = {"shopping": [
        {"title": f"Shoe {i}", "price": price, "source": "Shop", "rating": 4.1, "ratingCount": 10, "link": f"https://s/{i}", "imageUrl": "i"}
        for i, price in enumerate(["₹1,499.00", "₹2,999", "₹899", "₹12,000.50", "Free", "₹2,500"])
    ]}
    data = data_of(await run("search_products", query="running shoes", min_price=1000, max_price=3000))
    assert web.last.url.path == "/shopping" and web.body() == {"q": "running shoes", "gl": "in", "num": 40}
    assert [item["title"] for item in data] == ["Shoe 0", "Shoe 1", "Shoe 5"]
    assert data[0] == {"title": "Shoe 0", "price": "₹1,499.00", "store": "Shop", "rating": 4.1, "reviews": 10, "link": "https://s/0"}
    assert len(data_of(await run("search_products", query="running shoes"))) == 5


async def test_price_range_that_matches_nothing(web):
    web.replies["google.serper.dev"] = {"shopping": [{"title": "Shoe", "price": "₹999", "source": "S", "link": "l"}]}
    assert await run("search_products", query="shoes", min_price=5000) == "Google Shopping found no results."


def test_every_tool_is_registered_completely():
    from app.tools.registry import REGISTRY

    assert len(REGISTRY) == 19  # 2 built-in + 17 services
    for spec in REGISTRY.values():
        assert spec.tool.description and spec.activity.endswith("…")
        for field in spec.form:
            assert field.name in spec.tool.args, (spec.name, field.name)  # every form field is a real argument
    assert {name for name, spec in REGISTRY.items() if spec.form} == {
        "search_stays", "search_flights", "search_news", "find_places", "search_products", "search_amazon",
    }


# --- found by the live check -----------------------------------------------------------------


def _two_kochis(request: httpx.Request):
    if request.url.host == "geocoding-api.open-meteo.com":
        return {"results": [
            {"name": "Kochi", "country": "Japan", "country_code": "JP", "admin1": "Kochi", "latitude": 33.55, "longitude": 133.53},
            {"name": "Kochi", "country": "India", "country_code": "IN", "admin1": "Kerala", "latitude": 9.93, "longitude": 76.26},
        ]}
    return _open_meteo(request)


async def test_weather_prefers_the_named_country_then_the_default_one(web):
    web.replies["geocoding-api.open-meteo.com"] = _two_kochis
    web.replies["api.open-meteo.com"] = _two_kochis
    assert data_of(await run("get_current_weather", location="Kochi"))["place"] == "Kochi, Kerala, India"
    geocode = next(r for r in web.requests if r.url.host == "geocoding-api.open-meteo.com")
    assert dict(geocode.url.params) == {"name": "Kochi", "count": "10"}
    assert data_of(await run("get_current_weather", location="Kochi, Japan"))["place"] == "Kochi, Kochi, Japan"
    assert data_of(await run("get_current_weather", location="kochi , kerala"))["place"] == "Kochi, Kerala, India"


async def test_weather_takes_the_first_match_when_no_country_fits(web):
    web.replies["geocoding-api.open-meteo.com"] = lambda request: {"results": [
        {"name": "Paris", "country": "France", "country_code": "FR", "admin1": "Ile-de-France", "latitude": 48.85, "longitude": 2.35},
        {"name": "Paris", "country": "United States", "country_code": "US", "admin1": "Texas", "latitude": 33.66, "longitude": -95.55},
    ]}
    web.replies["api.open-meteo.com"] = _open_meteo
    assert data_of(await run("get_current_weather", location="Paris"))["place"] == "Paris, Ile-de-France, France"


async def test_book_authors_are_plain_names(web):
    web.replies["serpapi.com"] = {"organic_results": [
        {"title": "Atomic Habits", "authors": [{"name": "James Clear", "link": "https://www.google.com/very/long/link"}], "link": "https://b"}
    ]}
    assert data_of(await run("search_books", query="atomic habits")) == [
        {"title": "Atomic Habits", "authors": ["James Clear"], "link": "https://b"}
    ]


# --- flights (SerpApi Google Flights) ------------------------------------------------------------


def _flights(request):
    def option(i, price):
        return {
            "price": price, "total_duration": 190 + i, "type": "One way", "booking_token": "tok", "airline_logo": "l",
            "flights": [{
                "airline": "IndiGo", "flight_number": f"6E {5000 + i}", "duration": 190 + i, "travel_class": "Economy",
                "departure_airport": {"name": "Cochin International Airport", "id": "COK", "time": f"{TOMORROW} 05:45"},
                "arrival_airport": {"name": "Indira Gandhi International Airport", "id": "DEL", "time": f"{TOMORROW} 08:55"},
                "airplane": "A320", "legroom": "28 in",
            }],
        }

    return {
        "best_flights": [option(0, 11877), option(1, 12100)],
        "other_flights": [option(i, 12500 + i) for i in range(2, 8)],
        "price_insights": {"lowest_price": 11877, "price_level": "typical", "price_history": [[1, 2]]},
    }


async def test_one_way_flight_search(web):
    web.replies["serpapi.com"] = _flights
    data = data_of(await run("search_flights", origin="cok", destination="Del", departure_date=TOMORROW))
    assert web.params() == {
        "engine": "google_flights", "departure_id": "COK", "arrival_id": "DEL", "outbound_date": TOMORROW,
        "type": "2", "adults": "1", "travel_class": "1", "currency": "INR", "gl": "in", "hl": "en",
        "api_key": "test-serpapi-key",
    }
    assert data["currency"] == "INR" and data["lowest_price"] == 11877 and data["price_level"] == "typical"
    assert len(data["flights"]) == 5
    assert data["flights"][0] == {
        "price": 11877, "duration_minutes": 190, "stops": 0, "trip": "One way",
        "legs": [{"airline": "IndiGo", "flight": "6E 5000", "from": f"COK {TOMORROW} 05:45", "to": f"DEL {TOMORROW} 08:55"}],
    }


async def test_round_trip_with_filters(web):
    web.replies["serpapi.com"] = _flights
    await run("search_flights", origin="COK", destination="DXB", departure_date=TOMORROW, return_date=IN_3_DAYS,
              passengers=3, travel_class="business", stops="nonstop", max_price=90000)
    sent = web.params()
    assert sent["type"] == "1" and sent["return_date"] == IN_3_DAYS and sent["adults"] == "3"
    assert sent["travel_class"] == "3" and sent["stops"] == "1" and sent["max_price"] == "90000"


async def test_no_flights_found(web):
    web.replies["serpapi.com"] = {"best_flights": [], "other_flights": []}
    assert await run("search_flights", origin="COK", destination="DEL", departure_date=TOMORROW) == "Google Flights found no results."


@pytest.mark.parametrize(
    "args, message",
    [
        ({"origin": "Kochi"}, "three-letter airport codes"),
        ({"destination": "D3L"}, "three-letter airport codes"),
        ({"destination": "COK"}, "must be different"),
        ({"departure_date": YESTERDAY}, "in the past"),
        ({"departure_date": "soon"}, "YYYY-MM-DD"),
        ({"departure_date": IN_3_DAYS, "return_date": TOMORROW}, "before the departure"),
        ({"passengers": 0}, "between 1 and 9"),
        ({"passengers": 10}, "between 1 and 9"),
        ({"max_price": -5}, "can't be negative"),
    ],
)
async def test_bad_flight_arguments_refused_before_any_request(web, args, message):
    from app.tools.http import ToolError

    with pytest.raises(ToolError, match=message):
        await run("search_flights", **{"origin": "COK", "destination": "DEL", "departure_date": TOMORROW, **args})
    assert web.requests == []


# --- found by the review ------------------------------------------------------------------------


async def test_keys_stay_out_of_the_log_even_at_info_level(web, caplog):
    """httpx logs every request's full URL at INFO, and three services take their key in the URL."""
    from app.tools.http import fetch_json

    web.replies["api.example.com"] = {"ok": True}
    with caplog.at_level("INFO"):
        await fetch_json("Example", "https://api.example.com/x", secret_params={"api_key": "s3cret-key"})
    assert "s3cret-key" not in caplog.text


@pytest.mark.parametrize("status", [400, 422])
async def test_refused_values_are_not_reported_as_an_outage(web, status):
    from app.tools.http import ToolError, fetch_json

    web.replies["api.example.com"] = httpx.Response(status, json={"error": "bad language code"})
    with pytest.raises(ToolError) as caught:
        await fetch_json("Example", "https://api.example.com/x")
    assert str(caught.value) == "Example did not accept those values. Check them and try again."


async def test_amazon_marketplace_must_be_an_amazon_site(web):
    from app.tools.http import ToolError
    from app.tools.registry import REGISTRY

    with pytest.raises(ToolError, match="amazon.in"):
        await run("search_amazon", query="mouse", marketplace="Amazon India")
    assert web.requests == []
    field = next(f for f in REGISTRY["search_amazon"].form if f.name == "marketplace")
    assert field.type == "select" and ("amazon.in", "Amazon India") in field.options


async def test_catalog_says_which_service_each_tool_belongs_to(client, user_a):
    """The Tools step shows one card per service, with that service's logo."""
    tools = {t["name"]: t for g in (await client.get("/tools", headers=user_a)).json()["groups"] for t in g["tools"]}
    assert tools["web_search"]["app"] == "Google Search" and tools["search_flights"]["app"] == "Google Flights"
    assert tools["search_stays"]["app"] == "Airbnb" and tools["search_amazon"]["app"] == "Amazon"
    assert tools["get_current_weather"]["app"] == tools["get_weather_forecast"]["app"] == "Open-Meteo"
    assert {tools[n]["app"] for n in ("get_stock_quote", "find_stock_symbol", "get_company_news")} == {"Finnhub"}
    assert tools["convert_currency"]["app"] == "Frankfurter" and tools["calculator"]["app"] == "Calculator"
    assert all(t["app"] for t in tools.values())
