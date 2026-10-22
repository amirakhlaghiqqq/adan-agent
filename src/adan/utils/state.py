"""Graph state schemas.

`InputState` and `OutputState` are the public contract: the Agent Server exposes
them as the graph's input and output JSON schemas. `AgentState` is the internal
working state, and `RunContext` carries the per-request `Run` on the in-process
path.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from adan.runtime import Run


class InputState(TypedDict):
    """What a caller supplies to start a run."""

    question: str
    input_context: list[str]


class OutputState(TypedDict):
    """What a completed run returns. Only `response` is public."""

    response: dict


class AgentState(InputState, total=False):
    """Internal working state shared by all nodes.

    `messages` uses the `add_messages` reducer so tool turns accumulate; every
    other field is last-write-wins.
    """

    messages: Annotated[list[AnyMessage], add_messages]
    route: dict
    candidate: dict
    feedback: str
    corrections: int
    response: dict
    # Set by `coordinator` on the Agent Server path, where no `Run` is supplied.
    # Safe in state because the graph is compiled without a checkpointer.
    run: Run


class RunContext(TypedDict):
    """Runtime context for the in-process path, where the caller owns the `Run`."""

    run: Run
