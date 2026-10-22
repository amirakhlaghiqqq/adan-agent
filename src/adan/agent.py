"""LangGraph entrypoint: route, fan out/in, generate with tools, verify and finish."""

import asyncio
import atexit
import inspect
import threading

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Overwrite
from langgraph_sdk.runtime import ServerRuntime

from adan.runtime import Run
from adan.schemas import QueryRequest
from adan.utils import nodes
from adan.utils.state import AgentState, InputState, OutputState, RunContext


def build_graph(*, services=None, external=False):
    builder = StateGraph(
        AgentState,
        input_schema=InputState,
        output_schema=OutputState,
        context_schema=None if external else RunContext,
    )
    request_run = None

    def bind(function, name):
        async def invoke(state, runtime: Runtime):
            nonlocal request_run
            if name == "coordinator":
                request = QueryRequest.model_validate(
                    {"question": state["question"], "input_context": state.get("input_context", [])}
                )
                request_run = Run(services, request.question, request.input_context)
            result = function(state, runtime.override(context={"run": request_run}))
            update = await result if inspect.isawaitable(result) else result
            if name == "coordinator":
                update.update(
                    messages=Overwrite([]),
                    candidate={},
                    feedback="",
                    next_step=update.get("next_step", ""),
                )
            return update

        return invoke

    for name in ("coordinator", "documents", "database", "generate", "tools", "guard", "finalize"):
        function = getattr(nodes, name)
        builder.add_node(name, bind(function, name) if external else function)
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


_studio_assistant = None
_studio_lock = threading.Lock()


def _get_studio_assistant():
    global _studio_assistant
    with _studio_lock:
        if _studio_assistant is None:
            from adan.service import Assistant

            _studio_assistant = Assistant.from_settings()
            atexit.register(_studio_assistant.close)
        return _studio_assistant


async def make_graph(runtime: ServerRuntime):
    """Agent Server calls this factory per run; inspection needs no keys or model downloads."""
    services = await asyncio.to_thread(_get_studio_assistant) if runtime.execution_runtime else None
    return build_graph(services=services, external=True)
