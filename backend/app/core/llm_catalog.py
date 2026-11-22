"""The fixed list of providers and models a user can pick for an agent.

Model IDs were checked against the providers' documentation on 2026-11-16.
The platform is Gemini-only (owner's decision, 2026-11-17): the cheapest fast model,
the balanced one, the most capable one. Add a provider here and in app/agent/llm.py to offer another.
"""

CATALOG: dict = {
    "providers": [
        {
            "key": "gemini",
            "name": "Gemini",
            "models": [
                {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite (fastest, lowest cost)"},
                {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash (balanced)"},
                {"id": "gemini-4-argon", "name": "Gemini 4 Argon (most capable)"},
            ],
        },
    ]
}

_BY_KEY = {p["key"]: p for p in CATALOG["providers"]}


def is_provider(provider: str) -> bool:
    return provider in _BY_KEY


def provider_name(provider: str) -> str:
    return _BY_KEY[provider]["name"]


def is_valid_model(provider: str, model: str) -> bool:
    return provider in _BY_KEY and any(m["id"] == model for m in _BY_KEY[provider]["models"])
