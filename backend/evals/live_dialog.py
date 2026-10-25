"""Does the real model open the details dialog at the right moments? Run by hand:

    python -m evals.live_dialog           (from the backend directory)

Each line shows a request and the tools the model chose. It spends Gemini and search quota.
"""
import asyncio
from types import SimpleNamespace

from app.agent.context import build_messages
from app.agent.graph import RECURSION_LIMIT, build_graph
from app.agent.llm import build_chat_model
from app.core.config import get_settings
from app.tools import forms
from app.tools.registry import REGISTRY

# (request, should the dialog open?)
CASES = [
    ("rooms in Goa", False),
    ("Find me a place to stay in Goa next month", True),
    ("latest news about ISRO", False),
    ("cafes in Kochi", False),
    ("I need running shoes within my budget", True),
    ("Flights from Kochi to Delhi", True),
    ("wireless mouse on amazon", False),
    ("What's the weather in Kochi and what is 100 USD in INR?", False),
]


async def main() -> None:
    specs = list(REGISTRY.values())
    form_specs = {spec.name: spec for spec in specs if spec.form}
    model = build_chat_model("gemini", "gemini-3.5-flash-lite", get_settings().platform_gemini_api_key)
    graph = build_graph(model, [spec.tool for spec in specs] + [forms.build_ask_tool(form_specs)])
    right = 0
    for request, should_ask in CASES:
        question = SimpleNamespace(role="user", content=request)
        messages = build_messages("You are a helpful assistant.", None, [question], forms.details_instruction(form_specs))
        state = await graph.ainvoke({"messages": messages}, config={"recursion_limit": RECURSION_LIMIT})
        calls = [call["name"] for m in state["messages"] for call in (getattr(m, "tool_calls", None) or [])]
        asked = forms.ASK_TOOL in calls
        right += asked == should_ask
        print(f"{'ok  ' if asked == should_ask else 'MISS'} {request!r} -> {calls}")
    print(f"dialog decision right for {right}/{len(CASES)} requests")


if __name__ == "__main__":
    asyncio.run(main())
