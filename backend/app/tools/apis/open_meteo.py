"""Weather from Open-Meteo. No key. Free for non-commercial use."""
from langchain_core.tools import tool

from app.core.config import get_settings
from app.tools.http import ToolError, fetch_json, wrap

SERVICE = "Open-Meteo"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes, grouped into plain words.
_CONDITIONS = (
    ((0,), "Clear sky"), ((1, 2), "Partly cloudy"), ((3,), "Overcast"), ((45, 48), "Fog"),
    ((51, 53, 55, 56, 57), "Drizzle"), ((61, 63, 65, 66, 67), "Rain"), ((71, 73, 75, 77), "Snow"),
    ((80, 81, 82), "Rain showers"), ((85, 86), "Snow showers"), ((95, 96, 99), "Thunderstorm"),
)


def _conditions(code) -> str:
    return next((words for codes, words in _CONDITIONS if code in codes), "Unknown")


async def _locate(place: str) -> tuple[dict, str]:
    """Coordinates for a place name, and its full name.

    Many places share a name (Kochi is in India and in Japan). "Kochi, Japan" picks the one
    whose region or country matches what follows the comma; a bare name prefers the
    platform's default country; otherwise the best-known match wins.
    """
    name, _, hint = (part.strip() for part in place.partition(","))
    data = await fetch_json(SERVICE, GEOCODE_URL, params={"name": name, "count": 10})
    results = data.get("results") or []
    if not results:
        raise ToolError(f"I couldn't find a place called '{place}'.")
    hint = hint.lower()
    home = get_settings().default_country.upper()
    found = next(
        (r for r in results if hint and hint in f"{r.get('admin1', '')} {r.get('country', '')}".lower()),
        None,
    ) or next((r for r in results if not hint and r.get("country_code") == home), results[0])
    name = ", ".join(part for part in (found.get("name"), found.get("admin1"), found.get("country")) if part)
    return found, name


@tool
async def get_current_weather(location: str) -> str:
    """Get the weather right now in a city or place: temperature, humidity, wind and conditions.
    Add the region or country after a comma when the name is ambiguous, as in "Kochi, India"."""
    found, name = await _locate(location)
    data = await fetch_json(SERVICE, FORECAST_URL, params={
        "latitude": found["latitude"], "longitude": found["longitude"], "timezone": "auto",
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
    })
    current = data["current"]
    return wrap(SERVICE, {
        "place": name, "time": current.get("time"), "conditions": _conditions(current.get("weather_code")),
        "temperature_c": current.get("temperature_2m"), "humidity_percent": current.get("relative_humidity_2m"),
        "wind_kmh": current.get("wind_speed_10m"),
    })


@tool
async def get_weather_forecast(location: str, days: int = 3) -> str:
    """Get the daily weather forecast for a city or place, for the next 1 to 7 days:
    conditions, high and low temperature, and chance of rain. Add the region or country
    after a comma when the name is ambiguous, as in "Kochi, India"."""
    if not 1 <= days <= 7:
        raise ToolError("Choose between 1 and 7 days for a forecast.")
    found, name = await _locate(location)
    data = await fetch_json(SERVICE, FORECAST_URL, params={
        "latitude": found["latitude"], "longitude": found["longitude"], "timezone": "auto", "forecast_days": days,
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
    })
    daily = data["daily"]
    return wrap(SERVICE, {"place": name, "days": [
        {"date": date, "conditions": _conditions(code), "high_c": high, "low_c": low, "rain_chance_percent": rain}
        for date, code, high, low, rain in zip(
            daily["time"], daily["weather_code"], daily["temperature_2m_max"],
            daily["temperature_2m_min"], daily["precipitation_probability_max"],
        )
    ]})
