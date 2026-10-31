"""The card each outside-service tool sends, built from a stand-in service reply."""
import datetime as dt

import httpx

from tests.test_api_tools import data_of, run, web  # noqa: F401  (web is a fixture)
from tests.test_result_cards import card_of


def _amazon_item(i, **extra):
    return {"title": f"Buds {i}", "price": f"₹{500 + i}", "extracted_price": 500 + i, "link": f"https://amz/track/{i}", **extra}


async def test_products_card_from_amazon(web):  # noqa: F811
    web.replies["serpapi.com"] = {"organic_results": [
        _amazon_item(0, link_clean="https://amz/dp/0", thumbnail="https://img/0.jpg", old_price="₹999", price_unit="₹5/g",
                     rating=4.1, reviews=1200, delivery=["FREE delivery Sun"], offers=["5% back"], sponsored=True,
                     bought_last_month="1K+ bought in past month"),
        _amazon_item(1),
    ]}
    card = await card_of("search_amazon", query="earbuds")
    assert card["kind"] == "products" and card["service"] == "Amazon" and len(card["items"]) == 2
    assert card["items"][0] == {
        "title": "Buds 0", "image": "https://img/0.jpg", "link": "https://amz/dp/0", "price": "₹500", "old_price": "₹999",
        "price_unit": "₹5/g", "rating": 4.1, "reviews": 1200, "delivery": ["FREE delivery Sun"], "offers": ["5% back"],
        "sponsored": True, "bought_last_month": "1K+ bought in past month",
    }
    # A field the service did not send is simply absent.
    assert card["items"][1] == {"title": "Buds 1", "link": "https://amz/track/1", "price": "₹501"}


async def test_lists_show_eight_and_the_model_sees_the_same_items(web):  # noqa: F811
    web.replies["serpapi.com"] = {"organic_results": [_amazon_item(i) for i in range(10)]}
    card = await card_of("search_amazon", query="earbuds")
    seen = data_of(await run("search_amazon", query="earbuds"))
    assert len(card["items"]) == 8
    assert [item["title"] for item in seen] == [item["title"] for item in card["items"]]


async def test_products_card_from_google_shopping(web):  # noqa: F811
    web.replies["google.serper.dev"] = {"shopping": [
        {"title": "Shoe", "source": "NIKE India", "link": "https://g/shop", "price": "₹15,295", "imageUrl": "https://img/s.jpg",
         "rating": 4.7, "ratingCount": 3600, "productId": "1", "position": 1},
    ]}
    card = await card_of("search_products", query="running shoes")
    assert card["kind"] == "products" and card["service"] == "Google Shopping"
    assert card["items"] == [{"title": "Shoe", "image": "https://img/s.jpg", "price": "₹15,295", "store": "NIKE India",
                              "rating": 4.7, "reviews": 3600, "link": "https://g/shop"}]


async def test_stays_card(web):  # noqa: F811
    web.replies["serpapi.com"] = {"organic_results": [
        {"title": "Apartment in Siolim", "name": "The Crimson", "description": "1BHK with a pool", "link": "https://air/1",
         "is_new_listing": True, "price": "₹9,097", "old_price": "₹11,246", "price_qualifier": "for 3 nights",
         "rating": 4.9, "reviews": 31, "bedrooms": 1, "beds": 2, "bathrooms": 1,
         "gps_coordinates": {"latitude": 15.6, "longitude": 73.8}, "thumbnail": "https://img/t.jpg",
         "images": [f"https://img/{i}.jpg" for i in range(9)]},
        {"title": "Room in Anjuna", "name": "Plain room", "price": "₹1,000", "link": "https://air/2", "thumbnail": "https://img/only.jpg"},
    ]}
    card = await card_of("search_stays", location="Goa")
    assert card["kind"] == "stays" and card["service"] == "Airbnb"
    assert card["items"][0] == {
        "name": "The Crimson", "title": "Apartment in Siolim", "description": "1BHK with a pool", "link": "https://air/1",
        "is_new": True, "price": "₹9,097", "old_price": "₹11,246", "price_qualifier": "for 3 nights", "rating": 4.9,
        "reviews": 31, "bedrooms": 1, "beds": 2, "bathrooms": 1, "latitude": 15.6, "longitude": 73.8,
        "images": [f"https://img/{i}.jpg" for i in range(6)],
    }
    assert card["items"][1] == {"name": "Plain room", "title": "Room in Anjuna", "price": "₹1,000", "link": "https://air/2",
                                "images": ["https://img/only.jpg"]}


def _leg(number, start, end, **extra):
    return {"airline": "IndiGo", "airline_logo": "https://logo/6E.png", "flight_number": number, "duration": 190,
            "airplane": "Airbus A321neo", "travel_class": "Economy", "legroom": "28 in",
            "departure_airport": {"name": f"{start[0]} Airport", "id": start[0], "time": f"2026-12-10 {start[1]}"},
            "arrival_airport": {"name": f"{end[0]} Airport", "id": end[0], "time": f"2026-12-10 {end[1]}"}, **extra}


async def test_flights_card(web):  # noqa: F811
    day = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    web.replies["serpapi.com"] = {
        "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?tfs=x"},
        "airports": [{"departure": [{"city": "Kochi"}], "arrival": [{"city": "New Delhi"}]}],
        "price_insights": {"lowest_price": 11519, "price_level": "typical", "typical_price_range": [8000, 12000], "price_history": [[1, 2]]},
        "best_flights": [{
            "price": 11519, "total_duration": 420, "type": "One way", "airline_logo": "https://logo/6E.png", "booking_token": "secret-token",
            "carbon_emissions": {"this_flight": 131000, "difference_percent": -18},
            "flights": [_leg("6E 2127", ("COK", "21:40"), ("BOM", "23:30"), overnight=True), _leg("6E 99", ("BOM", "01:10"), ("DEL", "03:20"))],
            "layovers": [{"duration": 100, "name": "Mumbai Airport", "id": "BOM", "overnight": True}],
        }],
        "other_flights": [{"price": 12000, "flights": []}],
    }
    card = await card_of("search_flights", origin="COK", destination="DEL", departure_date=day)
    assert {key: card[key] for key in card if key != "items"} == {
        "kind": "flights", "service": "Google Flights", "currency": "INR", "lowest_price": 11519, "price_level": "typical",
        "typical_price_range": [8000, 12000], "link": "https://www.google.com/travel/flights?tfs=x",
        "origin": "Kochi", "destination": "New Delhi", "origin_code": "COK", "destination_code": "DEL", "date": day,
    }
    first = card["items"][0]
    assert first["title"] == "IndiGo 6E 2127 · COK 21:40 → DEL 03:20"
    assert first["price"] == 11519 and first["duration_minutes"] == 420 and first["stops"] == 1 and first["trip"] == "One way"
    assert first["logo"] == "https://logo/6E.png" and first["emissions_percent"] == -18
    assert first["legs"][0] == {
        "airline": "IndiGo", "logo": "https://logo/6E.png", "flight": "6E 2127", "duration": 190, "airplane": "Airbus A321neo",
        "travel_class": "Economy", "legroom": "28 in", "overnight": True,
        "from": {"id": "COK", "name": "COK Airport", "time": "2026-12-10 21:40"},
        "to": {"id": "BOM", "name": "BOM Airport", "time": "2026-12-10 23:30"},
    }
    assert first["layovers"] == [{"name": "Mumbai Airport", "id": "BOM", "duration": 100, "overnight": True}]
    assert "secret-token" not in str(card)  # nothing a second paid call would need is sent to the browser
    assert card["items"][1] == {"title": "Flight", "price": 12000, "stops": 0, "legs": [], "layovers": []}


async def test_weather_and_forecast_cards(web):  # noqa: F811
    web.replies["geocoding-api.open-meteo.com"] = {
        "results": [{"name": "Kochi", "country": "India", "admin1": "Kerala", "latitude": 9.93, "longitude": 76.26}]
    }
    web.replies["api.open-meteo.com"] = {
        "current": {"time": "2026-11-18T10:00", "temperature_2m": 29.4, "relative_humidity_2m": 70, "wind_speed_10m": 9.1,
                    "weather_code": 61, "apparent_temperature": 33.0, "precipitation": 0, "is_day": 1},
        "daily": {"time": ["2026-11-18", "2026-11-19"], "weather_code": [61, 2], "temperature_2m_max": [31.0, 32.5],
                  "temperature_2m_min": [24.0, 24.5], "precipitation_probability_max": [80, 20], "precipitation_sum": [12.5, 0],
                  "wind_speed_10m_max": [18.0, 11.0], "uv_index_max": [7.5, None],
                  "sunrise": ["2026-11-18T06:15", "2026-11-19T06:15"], "sunset": ["2026-11-18T18:00", "2026-11-19T18:00"]},
    }
    assert await card_of("get_current_weather", location="Kochi") == {
        "kind": "weather", "service": "Open-Meteo", "place": "Kochi, Kerala, India", "time": "2026-11-18T10:00",
        "conditions": "Rain", "temperature_c": 29.4, "humidity_percent": 70, "wind_kmh": 9.1, "feels_like_c": 33.0,
        "precipitation_mm": 0, "is_day": 1,
    }
    assert set(web.params()["current"].split(",")) >= {"apparent_temperature", "precipitation", "is_day"}
    card = await card_of("get_weather_forecast", location="Kochi", days=2)
    assert card["kind"] == "forecast" and card["place"] == "Kochi, Kerala, India"
    assert card["days"][0] == {"date": "2026-11-18", "conditions": "Rain", "high_c": 31.0, "low_c": 24.0, "rain_chance_percent": 80,
                               "rain_mm": 12.5, "wind_kmh": 18.0, "uv_index": 7.5, "sunrise": "2026-11-18T06:15", "sunset": "2026-11-18T18:00"}
    assert "uv_index" not in card["days"][1] and card["days"][1]["rain_mm"] == 0
    assert set(web.params()["daily"].split(",")) >= {"precipitation_sum", "wind_speed_10m_max", "uv_index_max", "sunrise", "sunset"}


async def test_currency_cards(web):  # noqa: F811
    web.replies["api.frankfurter.dev"] = {"base": "USD", "rates": {"INR": 88.5}}
    assert await card_of("convert_currency", amount=200, from_currency="usd", to_currency="inr") == {
        "kind": "conversion", "service": "Frankfurter", "amount": 200, "from": "USD", "to": "INR", "rate": 88.5,
        "result": 17700.0, "source": "Frankfurter",
    }
    assert await card_of("get_exchange_rates", base_currency="usd", currencies=["inr"]) == {
        "kind": "rates", "service": "Frankfurter", "base": "USD", "rates": {"INR": 88.5}, "source": "Frankfurter",
    }


def _finnhub(profile):
    quote = {"c": 352.61, "d": 0.7, "dp": 0.1989, "h": 356.42, "l": 351.2, "o": 351.3, "pc": 351.91, "t": 1795029657}

    def reply(request):
        if request.url.path.endswith("/stock/profile2"):
            return profile(request) if callable(profile) else profile
        return quote

    return reply


async def test_quote_card_has_the_company_profile(web):  # noqa: F811
    web.replies["finnhub.io"] = _finnhub({
        "name": "Apple Inc.", "currency": "USD", "exchange": "NASDAQ", "logo": "https://logo/AAPL.png",
        "finnhubIndustry": "Technology", "weburl": "https://www.apple.com/", "marketCapitalization": 5114020.09, "phone": "1",
    })
    card = await card_of("get_stock_quote", symbol="aapl")
    assert card == {
        "kind": "quote", "service": "Finnhub", "symbol": "AAPL", "price": 352.61, "change": 0.7, "change_percent": 0.1989,
        "high": 356.42, "low": 351.2, "open": 351.3, "previous_close": 351.91, "name": "Apple Inc.", "currency": "USD",
        "exchange": "NASDAQ", "time": 1795029657, "logo": "https://logo/AAPL.png", "industry": "Technology",
        "website": "https://www.apple.com/", "market_cap_millions": 5114020.09,
    }
    assert "test-finnhub-key" not in str(card)


async def test_quote_card_without_a_profile(web):  # noqa: F811
    def broken(request):
        raise httpx.ReadTimeout("slow")

    web.replies["finnhub.io"] = _finnhub(broken)
    card = await card_of("get_stock_quote", symbol="AAPL")
    assert card["price"] == 352.61 and "name" not in card and "logo" not in card


async def test_symbols_and_company_news_cards(web):  # noqa: F811
    web.replies["finnhub.io"] = {"result": [{"description": "Apple Inc.", "symbol": "AAPL", "type": "Common Stock"}]}
    assert await card_of("find_stock_symbol", company="apple") == {
        "kind": "symbols", "service": "Finnhub", "items": [{"symbol": "AAPL", "name": "Apple Inc.", "type": "Common Stock"}],
    }
    web.replies["finnhub.io"] = lambda request: [
        {"headline": "Big news", "source": "Yahoo", "datetime": 1794900000, "url": "https://n/1", "summary": "s" * 500, "image": "https://img/n.png"},
        {"headline": "Bare news", "url": "https://n/2", "image": ""},
    ]
    card = await card_of("get_company_news", symbol="AAPL")
    assert card["kind"] == "links" and card["service"] == "Finnhub"
    day = dt.datetime.fromtimestamp(1794900000, dt.UTC).date().isoformat()
    assert card["items"][0] == {"title": "Big news", "link": "https://n/1", "snippet": "s" * 200, "source": "Yahoo",
                                "date": day, "image": "https://img/n.png"}
    assert card["items"][1] == {"title": "Bare news", "link": "https://n/2"}


async def test_links_cards_for_web_books_and_news(web):  # noqa: F811
    web.replies["serpapi.com"] = {
        "answer_box": {"answer": "Canberra"},
        "organic_results": [{"title": "T", "link": "https://x/1", "snippet": "S", "source": "Site", "date": "2 days ago",
                             "thumbnail": "https://img/t.jpg", "favicon": "https://img/f.png", "position": 1}],
    }
    assert await card_of("web_search", query="capital of australia") == {
        "kind": "links", "service": "Google Search", "answer": "Canberra",
        "items": [{"title": "T", "link": "https://x/1", "snippet": "S", "source": "Site", "date": "2 days ago",
                   "image": "https://img/t.jpg", "favicon": "https://img/f.png"}],
    }
    web.replies["serpapi.com"] = {"organic_results": [
        {"title": "Atomic Habits", "authors": [{"name": "James Clear", "link": "https://g"}], "date": "2018", "snippet": "s",
         "link": "https://b", "thumbnail": "https://img/b.jpg", "book_id": "1"},
    ]}
    assert await card_of("search_books", query="atomic habits") == {
        "kind": "links", "service": "Google Books",
        "items": [{"title": "Atomic Habits", "authors": ["James Clear"], "date": "2018", "snippet": "s", "link": "https://b", "image": "https://img/b.jpg"}],
    }
    web.replies["google.serper.dev"] = {"news": [{"title": "N", "source": "Wire", "date": "1 hour ago", "link": "https://n", "snippet": "s", "imageUrl": "https://img/n.jpg"}]}
    assert await card_of("search_news", query="isro") == {
        "kind": "links", "service": "Google News",
        "items": [{"title": "N", "source": "Wire", "date": "1 hour ago", "link": "https://n", "snippet": "s", "image": "https://img/n.jpg"}],
    }


async def test_images_and_places_cards(web):  # noqa: F811
    web.replies["google.serper.dev"] = {"images": [
        {"title": f"I{i}", "imageUrl": f"https://img/{i}.jpg", "thumbnailUrl": f"https://thumb/{i}.jpg", "source": "Site",
         "link": f"https://page/{i}", "imageWidth": 1200} for i in range(10)
    ]}
    card = await card_of("search_images", query="munnar")
    assert card["kind"] == "images" and len(card["items"]) == 8 and web.body()["num"] == 8
    assert card["items"][0] == {"title": "I0", "image": "https://img/0.jpg", "thumbnail": "https://thumb/0.jpg", "source": "Site", "link": "https://page/0"}
    web.replies["google.serper.dev"] = {"places": [
        {"title": "RD Cafe", "address": "NH66", "latitude": 9.9, "longitude": 76.2, "rating": 4.4, "ratingCount": 900,
         "priceLevel": "₹200–400", "category": "Cafe", "phoneNumber": "0484", "website": "https://rd", "cid": "8589049157029474615"},
        {"title": "No details"},
    ]}
    card = await card_of("find_places", query="cafes", location="Kochi")
    assert card["kind"] == "places"
    assert card["items"][0] == {
        "name": "RD Cafe", "title": "RD Cafe", "address": "NH66", "latitude": 9.9, "longitude": 76.2, "rating": 4.4,
        "reviews": 900, "price_level": "₹200–400", "category": "Cafe", "phone": "0484", "website": "https://rd",
        "link": "https://www.google.com/maps?cid=8589049157029474615",
    }
    assert card["items"][1] == {"name": "No details", "title": "No details"}


async def test_translation_card(web):  # noqa: F811
    web.replies["serpapi.com"] = {
        "search_metadata": {"google_translate_url": "https://translate.google.com/?sl=auto&tl=ml"},
        "translation": {"source": {"language": "English", "text": "good morning", "pronunciation": "gud"},
                        "target": {"language": "Malayalam", "text": "സുപ്രഭാതം", "pronunciation": "suprabhaatham"}},
    }
    assert await card_of("translate_text", text="good morning", target_language="ml") == {
        "kind": "translation", "service": "Google Translate", "text": "good morning", "translation": "സുപ്രഭാതം",
        "from": "English", "to": "Malayalam", "pronunciation": "suprabhaatham", "source_pronunciation": "gud",
        "link": "https://translate.google.com/?sl=auto&tl=ml",
    }


async def test_no_results_has_no_card(web):  # noqa: F811
    web.replies["serpapi.com"] = {"error": "Google hasn't returned any results for this query."}
    assert await card_of("web_search", query="asdfqwer") is None
    web.replies["google.serper.dev"] = {"news": []}
    assert await card_of("search_news", query="zzzz") is None
