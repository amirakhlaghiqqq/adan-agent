"""LangGraph entrypoint: route, fan out/in, generate with tools, verify and finish."""

from langgraph.graph import END, START, StateGraph

from adan.utils import nodes
from adan.utils.state import AgentState, InputState, RunContext


def build_graph():
    builder = StateGraph(AgentState, input_schema=InputState, context_schema=RunContext)
    for name in ("coordinator", "documents", "database", "generate", "tools", "guard", "finalize"):
        builder.add_node(name, getattr(nodes, name))
    builder.add_edge(START, "coordinator")
    builder.add_conditional_edges(
        "coordinator", nodes.route_sources, ["documents", "database", "generate", "finalize"]
    )
    builder.add_edge("documents", "generate")
    builder.add_edge("database", "generate")
    for name in ("generate", "tools", "guard"):
        builder.add_conditional_edges(
            name, lambda state: state["next_step"], ["generate", "tools", "guard", "finalize"]
        )
    builder.add_edge("finalize", END)
    return builder.compile(name="cloudscale")
