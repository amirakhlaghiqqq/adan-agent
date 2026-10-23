"""Graph nodes: route, retrieve, generate with tools, verify, and format the answer.

Each node returns a partial state update, or a `Command` when it also decides where
to go next. Nodes never raise for expected failures: they record the failure on the
`Run` and route to `finalize`, so a request always produces a response.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.runtime import Runtime
from langgraph.types import Command, Overwrite

from adan.calculator import calculate
from adan.prompts import CRITIC, GENERATOR, ROUTER
from adan.runtime import LimitReached, Run, visible_message
from adan.schemas import (
    Calculate,
    QueryDatabase,
    QueryRequest,
    RoutingDecision,
    SearchDocuments,
    SubmitAnswer,
    Verdict,
)
from adan.utils.state import RunContext

# Tool name to argument schema. `submit_answer` is the terminal tool, not a dispatchable one.
TOOL_MODELS = {
    "search_documents": SearchDocuments,
    "query_database": QueryDatabase,
    "calculate": Calculate,
    "submit_answer": SubmitAnswer,
}

# OpenAI-format tool definitions passed to the generator model.
TOOLS = []
for name, model in TOOL_MODELS.items():
    definition = convert_to_openai_tool(model)
    definition["function"]["name"] = name
    TOOLS.append(definition)

# Declared for graph rendering and validation; routing itself lives in each node's
# `Command(goto=...)`. Nodes that do not route are absent.
ROUTES = {
    "coordinator": ("documents", "database", "generate", "finalize"),
    "generate": ("generate", "tools", "guard", "finalize"),
    "tools": ("generate", "finalize"),
    "guard": ("generate", "finalize"),
}


def _run(state, runtime):
    """Return this request's `Run`.

    The in-process path supplies it as runtime context. The Agent Server path has
    no context, so `coordinator` creates it and stores it in graph state.
    """
    context = runtime.context or {}
    return context.get("run") or state["run"]


def _failure(run, stage, exc):
    """Record a failed stage on the run and return the failure payload.

    `LimitReached` also sets the stop reason, because a budget stop is a normal
    termination rather than an error. Exception text is only exposed for errors
    the application raises itself; provider errors could leak request details.
    """
    if isinstance(exc, LimitReached):
        run.stop_reason = str(exc)
    failure = {
        "stage": stage,
        "error_type": type(exc).__name__,
        "error": str(exc) if isinstance(exc, (ValueError, LimitReached)) else "Operation failed",
    }
    run.failures.append(failure)
    return failure


async def coordinator(
    state, runtime: Runtime[RunContext]
) -> Command[Literal["documents", "database", "generate", "finalize"]]:
    """Classify the question and fan out to the sources it needs.

    Returns `documents` and/or `database` together when both are required, which
    LangGraph runs concurrently in one superstep. Falls back to the configured
    router model once before giving up. On failure the request still finalizes,
    with the error recorded on the run.
    """
    context = runtime.context or {}
    run = context.get("run")
    if run is None:
        request = QueryRequest.model_validate(
            {"question": state["question"], "input_context": state.get("input_context", [])}
        )
        run = Run(context["services"], request.question, request.input_context)
    messages = [
        SystemMessage(ROUTER),
        HumanMessage(
            json.dumps(
                {"question": state["question"], "input_context": state.get("input_context", [])}
            )
        ),
    ]
    try:
        try:
            route = await run.model("coordinator", messages, schema=RoutingDecision)
        except LimitReached:
            raise
        except Exception:
            if not run.settings.router_fallback_model:
                raise
            route = await run.model("coordinator", messages, schema=RoutingDecision, fallback=True)
    except Exception as exc:
        _failure(run, "coordinator", exc)
        run.stop_reason = run.stop_reason if run.stop_reason != "completed" else "coordinator_error"
        return Command(update={"run": run, "route": {}}, goto="finalize")

    # The graph is the entry point for a request, so start from a clean slate.
    update = {
        "run": run,
        "route": route,
        "corrections": 0,
        "messages": Overwrite([]),
        "candidate": {},
        "feedback": "",
    }
    targets = (["documents"] if route["needs_docs"] else []) + (
        ["database"] if route["needs_db"] else []
    )
    return Command(update=update, goto=targets or "generate")


async def documents(state, runtime: Runtime[RunContext]):
    """Retrieve policy evidence for the question.

    Failures are recorded and swallowed so the database branch and the generator
    can still run with whatever evidence was gathered.
    """
    run = _run(state, runtime)
    try:
        await run.services.search_documents(state["question"], run)
    except Exception as exc:
        _failure(run, "documents", exc)
    return {}


async def database(state, runtime: Runtime[RunContext]):
    """Query the customer database for the question.

    Failures are recorded and swallowed so the document branch and the generator
    can still run with whatever evidence was gathered.
    """
    run = _run(state, runtime)
    try:
        await run.services.query_database(state["question"], run)
    except Exception as exc:
        _failure(run, "database", exc)
    return {}


async def generate(
    state, runtime: Runtime[RunContext]
) -> Command[Literal["generate", "tools", "guard", "finalize"]]:
    """Ask the generator for the next step: a tool call, a candidate answer, or a retry.

    `submit_answer` ends generation and hands the candidate to `guard`. Any other
    tool call goes to `tools`. A turn with no tool call is re-prompted, bounded by
    the same generator-turn budget. Every turn is recorded in `generator_contexts`
    so the critic can audit what the generator actually saw.
    """
    run = _run(state, runtime)
    try:
        if run.stop_reason != "completed":
            return Command(goto="finalize")
        await run.reserve("turns", run.settings.max_generator_turns, "max_generator_turns")
        system = SystemMessage(GENERATOR + "\nEvidence:\n" + run.serialized_evidence())
        history = state.get("messages") or [
            HumanMessage(
                json.dumps(
                    {"question": state["question"], "input_context": state.get("input_context", [])}
                )
            )
        ]
        if state.get("feedback"):
            history = [*history, HumanMessage("Verification feedback: " + state["feedback"])]
        messages = [system, *history]
        run.generator_contexts.append(
            {"turn": run.counts["turns"], "messages": [visible_message(m) for m in messages]}
        )
        ai = await run.model("generate", messages, tools=TOOLS)
        if ai.invalid_tool_calls:
            raise ValueError("Model returned malformed tool arguments")
        final_calls = [call for call in ai.tool_calls if call["name"] == "submit_answer"]
        if final_calls:
            if len(ai.tool_calls) != 1:
                raise ValueError("submit_answer must be the only tool call in its turn")
            candidate = SubmitAnswer.model_validate(final_calls[0]["args"]).model_dump()
            return Command(
                update={
                    "messages": [
                        *history,
                        ai,
                        ToolMessage(
                            "Candidate submitted for verification.",
                            tool_call_id=final_calls[0]["id"],
                        ),
                    ],
                    "candidate": candidate,
                    "feedback": "",
                },
                goto="guard",
            )
        if not ai.tool_calls:
            # Prompt correction is bounded by the same generator-turn limit.
            return Command(
                update={
                    "messages": [*history, ai],
                    "feedback": "Use tools or submit_answer to finish.",
                },
                goto="generate",
            )
        return Command(update={"messages": [*history, ai], "feedback": ""}, goto="tools")
    except Exception as exc:
        _failure(run, "generate", exc)
        if run.stop_reason == "completed":
            run.stop_reason = "generation_error"
        return Command(goto="finalize")


async def tools(state, runtime: Runtime[RunContext]) -> Command[Literal["generate", "finalize"]]:
    """Execute the tool calls from the generator's last message.

    Each call is traced with start/finish times and a parent id, and each failure
    becomes a `ToolMessage` the generator can react to rather than an exception.
    Follow-up retrieval is budgeted separately from the initial fan-out.
    """
    run = _run(state, runtime)
    messages = []
    for call in state["messages"][-1].tool_calls:
        event = run.event("dispatch." + call["name"], call["args"])
        started = time.monotonic()
        try:
            name = call["name"]
            if name not in TOOL_MODELS or name == "submit_answer":
                raise ValueError("Unknown tool")
            args = TOOL_MODELS[name].model_validate(call["args"]).model_dump(exclude_none=True)
            if name == "calculate":
                output = await run.execute(
                    "calculate",
                    args,
                    lambda a=args: asyncio.to_thread(calculate, **a),
                    tool=True,
                    parent_id=event["event_id"],
                )
            else:
                kind = "document" if name == "search_documents" else "database"
                await run.reserve(
                    kind + "_followups",
                    getattr(run.settings, "max_" + kind + "_followups"),
                    "max_" + kind + "_followups",
                )
                function = getattr(run.services, name)
                output = await function(next(iter(args.values())), run, parent_id=event["event_id"])
            event.update(status="ok", output=output)
        except Exception as exc:
            output = _failure(run, call["name"], exc)
            event.update(status="error", output=output)
        finally:
            event["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            event["finished_at"] = datetime.now(UTC).isoformat()
        messages.append(ToolMessage(json.dumps(output), tool_call_id=call["id"]))
    return Command(
        update={"messages": messages},
        goto="generate" if run.stop_reason == "completed" else "finalize",
    )


async def guard(state, runtime: Runtime[RunContext]) -> Command[Literal["generate", "finalize"]]:
    """Verify the candidate answer before it is returned.

    Citations that do not match retrieved chunks are rejected without a model
    call. Otherwise the critic model judges the candidate against the generator
    contexts and tool outputs. A rejection sends the feedback back to `generate`
    until `max_corrections` is exhausted.
    """
    run = _run(state, runtime)
    candidate = state["candidate"]
    visible_ids = {c["chunk_id"] for c in run.chunks}
    unknown = set(candidate["citation_ids"]) - visible_ids
    try:
        if unknown:
            verdict = {
                "passed": False,
                "feedback": "Remove unsupported citation IDs: " + ", ".join(unknown),
            }
        else:
            verdict = await run.model(
                "guard",
                [
                    SystemMessage(CRITIC),
                    HumanMessage(
                        json.dumps(
                            {
                                "candidate": candidate,
                                "generator_contexts": run.generator_contexts,
                                "tool_outputs": [
                                    {"name": c["name"], "output": c.get("output")}
                                    for c in run.tool_calls
                                ],
                            }
                        )
                    ),
                ],
                schema=Verdict,
            )
        run.guardrail_history.append({"candidate": candidate, **verdict})
        if verdict["passed"]:
            return Command(goto="finalize")
        if state.get("corrections", 0) < run.settings.max_corrections:
            return Command(
                update={
                    "corrections": state.get("corrections", 0) + 1,
                    "feedback": verdict["feedback"],
                },
                goto="generate",
            )
        run.stop_reason = "verification_exhausted"
    except Exception as exc:
        _failure(run, "guard", exc)
        run.stop_reason = str(exc) if isinstance(exc, LimitReached) else "verification_error"
    return Command(update={"candidate": {}}, goto="finalize")


def response(state, run):
    """Build the public response payload.

    A run that did not complete never returns its candidate: the answer is
    replaced with an explicit partial or insufficient-evidence message, so an
    unverified conclusion cannot be mistaken for a verified one. Citations are
    deduplicated and stripped of relevance scores.
    """
    candidate = state.get("candidate", {})
    if run.stop_reason != "completed":
        candidate = {}
    if not candidate:
        supported = bool(run.chunks or run.database_results)
        candidate = {
            "answer": "I could not finish a verified answer within this request. "
            "Available source evidence is included in the response; unresolved conclusions "
            "remain unverified. Stop reason: " + run.stop_reason + ".",
            "status": "partial" if supported else "insufficient_evidence",
            "missing_information": ["A completed, verified answer"],
            "citation_ids": [],
        }
    citations = {c["chunk_id"]: {k: v for k, v in c.items() if k != "score"} for c in run.chunks}
    return {
        "schema_version": "1.0",
        "mode": "end_to_end",
        "run_id": run.run_id,
        "question": run.question,
        "input_context": run.input_context,
        "answer": candidate["answer"],
        "status": candidate["status"],
        "stop_reason": run.stop_reason,
        "missing_information": candidate["missing_information"],
        "citations": [
            citations[c] for c in dict.fromkeys(candidate["citation_ids"]) if c in citations
        ],
        "route": state.get("route", {}),
        "retrieval_calls": run.retrieval_calls,
        "database_calls": run.database_calls,
        "retrieved_document_chunks": run.retrieved_document_chunks(),
        "database_results": run.database_results,
        "calculator_trace": [c for c in run.tool_calls if c["name"] == "calculate"],
        "tool_calls": run.tool_calls,
        "aggregation_artifacts": run.aggregation_artifacts,
        "generator_contexts": run.generator_contexts,
        "guardrail_history": run.guardrail_history,
        "execution_trace": run.trace,
        "failures": run.failures,
        "timings": {
            "started_at": run.started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((time.monotonic() - run.started) * 1000, 3),
        },
        "usage": run.usage_summary(),
        "effective_limits": run.settings.model_dump(
            mode="json", exclude={"openrouter_api_key", "qdrant_api_key"}
        ),
        "index_fingerprint": run.services.documents.fingerprint,
    }


async def finalize(state, runtime: Runtime[RunContext]):
    """Write the response into the graph's output schema and end the run."""
    return {"response": response(state, _run(state, runtime))}
