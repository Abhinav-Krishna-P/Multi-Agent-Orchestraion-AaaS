"""The agent as a LangGraph graph: the model, and a tool node it can loop through."""
from collections.abc import Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import ValidationError

AGENT_NODE = "agent"
TOOLS_NODE = "tools"
MAX_TOOL_ROUNDS = 6
# LangGraph's own safety net, set loosely: the runner enforces MAX_TOOL_ROUNDS exactly.
RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 5


def _tool_error(error: Exception) -> str:
    """What the model is told when a tool fails. Argument problems are explained so it can
    retry; anything else stays generic, because exception text can carry internal detail."""
    if isinstance(error, ValidationError):
        return f"The tool was called with the wrong arguments: {error.errors(include_url=False, include_input=False)}"
    return "The tool failed. Tell the user it could not be used right now."


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
        graph.add_edge(TOOLS_NODE, AGENT_NODE)
    else:
        graph.add_edge(AGENT_NODE, END)
    return graph.compile()
