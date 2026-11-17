"""The agent as a LangGraph graph: the model, and a tool node it can loop through."""
import uuid
from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage, messages_from_dict, messages_to_dict
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.prebuilt.tool_node import ToolInvocationError

from app.automations.describe import ASK_AUTOMATION_TOOL
from app.core import cache
from app.tools.forms import ASK_TOOL
from app.tools.http import ToolError

AGENT_NODE = "agent"
TOOLS_NODE = "tools"
MAX_TOOL_ROUNDS = 6
# LangGraph's own safety net, set loosely: the runner enforces MAX_TOOL_ROUNDS exactly.
RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 5
LLM_CACHE_SECONDS = 24 * 3600


def chunk_text(chunk) -> str:
    """The visible text of a streamed chunk. Content is a string or a list of parts;
    parts that are not text (such as a model's thinking) are left out."""
    content = chunk.content
    if isinstance(content, str):
        return content
    pieces = []
    for part in content:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, dict) and part.get("type") == "text":
            pieces.append(part.get("text", ""))
    return "".join(pieces)


def step_key(scope: str, tools: Sequence[BaseTool], messages: Sequence[BaseMessage]) -> str:
    """The cache key for one model step: everything the model is given, without the ids that
    differ between otherwise identical chats (message ids, tool-call ids)."""
    seen = [(m.type, m.content, [(c["name"], c["args"]) for c in getattr(m, "tool_calls", None) or []], m.name) for m in messages]
    return f"llm:{scope}:{cache.digest([convert_to_openai_tool(t) for t in tools], seen)}"


def _to_cache(reply: AIMessage) -> dict:
    return messages_to_dict([reply])[0]


def _from_cache(stored: dict) -> AIMessage:
    """A cached reply as a new message: its own id and fresh tool-call ids, so nothing that keys
    on them (tool activity, approvals) can mix this chat up with the one it was cached from."""
    reply = messages_from_dict([stored])[0]
    calls = [{**c, "id": f"cached_{uuid.uuid4().hex}"} for c in reply.tool_calls]
    return reply.model_copy(update={"id": None, "tool_calls": calls})


def _tool_error(error: Exception) -> str:
    """What the model is told when a tool fails. Argument problems are explained so it can
    retry; anything else stays generic, because exception text can carry internal detail."""
    if isinstance(error, ToolInvocationError):  # how the tool node reports arguments that don't fit
        problems = "; ".join(
            f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
            for detail in error.source.errors(include_url=False, include_input=False)
        )
        return f"The tool was called with the wrong arguments ({problems}). Correct them and try again."
    if isinstance(error, ToolError):  # already written for the model to pass on
        return str(error)
    return "The tool failed. Tell the user it could not be used right now."


def _after_tools(state: MessagesState) -> str:
    """Back to the model, unless it has just asked the user something (details for a search,
    or approval for an action): then the turn is over and the user's answer starts the next one."""
    for message in reversed(state["messages"]):
        if not isinstance(message, ToolMessage):
            break
        if message.name in (ASK_TOOL, ASK_AUTOMATION_TOOL) and message.status != "error":
            return END
        if isinstance(message.artifact, dict) and "approval" in message.artifact:
            return END
    return AGENT_NODE


def build_graph(model: BaseChatModel, tools: Sequence[BaseTool] = (), *, cache_scope: str | None = None) -> CompiledStateGraph:
    """`cache_scope` (agent and model) turns on the model-step cache; chat replies only."""
    tools = list(tools)
    bound = model.bind_tools(tools) if tools else model

    async def agent(state: MessagesState) -> dict:
        if cache_scope is None:
            return {"messages": [await bound.ainvoke(state["messages"])]}
        key = step_key(cache_scope, tools, state["messages"])
        if (stored := await cache.get_json(key)) is not None:
            return {"messages": [_from_cache(stored)]}
        reply = await bound.ainvoke(state["messages"])
        if chunk_text(reply).strip() or reply.tool_calls:  # a reply with nothing to show is a failure, never kept
            await cache.set_json(key, _to_cache(reply), LLM_CACHE_SECONDS)
        return {"messages": [reply]}

    graph = StateGraph(MessagesState)
    graph.add_node(AGENT_NODE, agent)
    graph.add_edge(START, AGENT_NODE)
    if tools:
        graph.add_node(TOOLS_NODE, ToolNode(tools, handle_tool_errors=_tool_error))
        graph.add_conditional_edges(AGENT_NODE, tools_condition, {"tools": TOOLS_NODE, END: END})
        graph.add_conditional_edges(TOOLS_NODE, _after_tools, {AGENT_NODE: AGENT_NODE, END: END})
    else:
        graph.add_edge(AGENT_NODE, END)
    return graph.compile()
