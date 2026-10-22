"""LangGraph entrypoint: route, fan out/in, generate with tools, verify and finish.

Two callers compile this graph:

* `Assistant.ask` builds it in-process and passes a `Run` as runtime context.
* The Agent Server calls `make_graph` per run and supplies no `Run`, so
  `coordinator` creates one and keeps it in graph state.

Routing lives in the nodes as `Command(goto=...)`; this module only wires nodes
and the static edges that converge the two retrieval branches.
"""

import asyncio
import atexit
import threading

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph_sdk.runtime import ServerRuntime

from adan.utils import nodes
from adan.utils.state import AgentState, InputState, OutputState, RunContext

# Every node in execution order, used to register them uniformly.
NODE_NAMES = ("coordinator", "documents", "database", "generate", "tools", "guard", "finalize")


def _with_services(function, services):
    """Give the node the services it needs to build a `Run`.

    `Runtime.override` returns a new runtime for this node only, so every node
    needs the wrapper rather than just the entry node.
    """

    async def node(state, runtime: Runtime):
        return await function(state, runtime.override(context={"services": services}))

    return node


def build_graph(*, services=None, external=False):
    """Compile the graph.

    `external=True` is the Agent Server path: the server supplies no `Run`, so
    `coordinator` creates one from the input and stores it in graph state. The
    in-process path passes `RunContext` in from `Assistant.ask` instead.
    """
    builder = StateGraph(
        AgentState,
        input_schema=InputState,
        output_schema=OutputState,
        context_schema=None if external else RunContext,
    )
    for name in NODE_NAMES:
        function = getattr(nodes, name)
        if external:
            builder.add_node(
                name, _with_services(function, services), destinations=nodes.ROUTES.get(name)
            )
        else:
            builder.add_node(name, function)

    builder.add_edge(START, "coordinator")
    # Both branches are one step and converge on `generate`. Keep them as separate
    # edges: a list-form edge would skip `generate` when only one branch is selected.
    builder.add_edge("documents", "generate")
    builder.add_edge("database", "generate")
    builder.add_edge("finalize", END)
    return builder.compile(name="cloudscale")


_studio_assistant = None
_studio_lock = threading.Lock()


def _get_studio_assistant():
    """Return the process-wide `Assistant`, creating it on first use.

    Building it loads the embedding model and opens the index, so it is created
    lazily and closed at interpreter exit. The lock keeps concurrent first runs
    from building two instances.
    """
    global _studio_assistant
    with _studio_lock:
        if _studio_assistant is None:
            from adan.service import Assistant

            _studio_assistant = Assistant.from_settings()
            atexit.register(_studio_assistant.close)
        return _studio_assistant


async def make_graph(runtime: ServerRuntime):
    """Agent Server factory, called once per run.

    Schema inspection must not need credentials or model downloads, so the
    assistant is only built when the server reports an execution runtime.
    """
    services = await asyncio.to_thread(_get_studio_assistant) if runtime.execution_runtime else None
    return build_graph(services=services, external=True)
