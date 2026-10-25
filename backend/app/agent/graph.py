"""The agent as a LangGraph graph: the model, and a tool node it can loop through."""
from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.prebuilt.tool_node import ToolInvocationError

from app.tools.forms import ASK_TOOL
from app.tools.http import ToolError

AGENT_NODE = "agent"
TOOLS_NODE = "tools"
MAX_TOOL_ROUNDS = 6
# LangGraph's own safety net, set loosely: the runner enforces MAX_TOOL_ROUNDS exactly.
RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 5


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
    """Back to the model, unless it has just asked the user for details: then the turn is
    over and the user's reply starts the next one."""
    for message in reversed(state["messages"]):
        if not isinstance(message, ToolMessage):
            break
        if message.name == ASK_TOOL and message.status != "error":
            return END
    return AGENT_NODE


def build_graph(model: BaseChatModel, tools: Sequence[BaseTool] = ()) -> CompiledStateGraph:
    tools = list(tools)
    bound = model.bind_tools(tools) if tools else model

    async def agent(state: MessagesState) -> dict:
        return {"messages": [await bound.ainvoke(state["messages"])]}

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
