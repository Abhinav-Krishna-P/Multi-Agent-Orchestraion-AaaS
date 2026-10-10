"""The agent as a LangGraph graph. Stage 1 has one node; stage 2 adds a tool node beside it."""
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

AGENT_NODE = "agent"


def build_graph(model: BaseChatModel) -> CompiledStateGraph:
    async def agent(state: MessagesState) -> dict:
        return {"messages": [await model.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node(AGENT_NODE, agent)
    graph.add_edge(START, AGENT_NODE)
    graph.add_edge(AGENT_NODE, END)
    return graph.compile()
