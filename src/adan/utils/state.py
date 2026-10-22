from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from adan.runtime import Run


class InputState(TypedDict):
    question: str
    input_context: list[str]


class AgentState(InputState, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    route: dict
    candidate: dict
    feedback: str
    corrections: int
    next_step: str
    response: dict


class RunContext(TypedDict):
    run: Run
