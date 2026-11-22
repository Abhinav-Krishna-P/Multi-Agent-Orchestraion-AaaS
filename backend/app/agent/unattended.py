"""Playing an agent's graph with nobody there to answer, shared by automations and API calls."""
import time

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.graph import MAX_TOOL_ROUNDS, RECURSION_LIMIT, build_graph
from app.agent.runner import chunk_text
from app.analytics import posthog


async def play(
    model, toolset, messages, *, user_id, track: dict, source: str, used: dict, reply: dict, sources: list,
    cache_scope: str | None = None,
) -> str | None:
    """Streams the run, filling in `used` (tool call id -> {name, label, ok, card?, overridden?}),
    `reply["text"]` and `sources`. Returns the name of the first tool that failed, if any. It
    neither times out nor catches errors: the caller does."""
    failed_tool = None
    calls: dict[str, float] = {}  # tool call id -> when asked
    rounds = 0
    graph = build_graph(model, toolset.tools, cache_scope=cache_scope)
    async for update in graph.astream({"messages": messages}, stream_mode="updates", config={"recursion_limit": RECURSION_LIMIT}):
        for change in update.values():
            for message in (change or {}).get("messages", []):
                if isinstance(message, AIMessage):
                    reply["text"] = chunk_text(message)
                    rounds += bool(message.tool_calls)
                    if rounds > MAX_TOOL_ROUNDS:
                        raise RuntimeError("too many tool rounds")
                    for call in message.tool_calls:
                        used[call["id"]] = {"name": call["name"], "label": toolset.labels.get(call["name"], call["name"]), "ok": True}
                        calls[call["id"]] = time.monotonic()
                elif isinstance(message, ToolMessage) and message.tool_call_id in used:
                    entry = used[message.tool_call_id]
                    name = entry["name"]
                    entry["ok"] = message.status != "error"
                    if not entry["ok"]:
                        failed_tool = failed_tool or name
                    if isinstance(message.artifact, list):
                        sources.extend(message.artifact)
                    artifact = message.artifact if isinstance(message.artifact, dict) else {}
                    entry |= {key: artifact[key] for key in ("card", "overridden") if artifact.get(key)}
                    if name in toolset.kinds:
                        kind, app = toolset.kinds[name]
                        posthog.capture(
                            "tool_called", user_id, **track, tool_name=name, tool_type=kind, app=app, success=entry["ok"],
                            duration_ms=int((time.monotonic() - calls[message.tool_call_id]) * 1000), source=source,
                        )
    return failed_tool
