import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.runtime import Runtime

from adan.calculator import calculate
from adan.prompts import CRITIC, GENERATOR, ROUTER
from adan.runtime import LimitReached, visible_message
from adan.schemas import (
    Calculate,
    QueryDatabase,
    RoutingDecision,
    SearchDocuments,
    SubmitAnswer,
    Verdict,
)
from adan.utils.state import RunContext

TOOL_MODELS = {
    "search_documents": SearchDocuments,
    "query_database": QueryDatabase,
    "calculate": Calculate,
    "submit_answer": SubmitAnswer,
}
TOOLS = []
for name, model in TOOL_MODELS.items():
    definition = convert_to_openai_tool(model)
    definition["function"]["name"] = name
    TOOLS.append(definition)


def _failure(run, stage, exc):
    if isinstance(exc, LimitReached):
        run.stop_reason = str(exc)
    failure = {
        "stage": stage,
        "error_type": type(exc).__name__,
        "error": str(exc) if isinstance(exc, (ValueError, LimitReached)) else "Operation failed",
    }
    run.failures.append(failure)
    return failure


async def coordinator(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
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
        return {"route": route, "corrections": 0}
    except Exception as exc:
        _failure(run, "coordinator", exc)
        run.stop_reason = run.stop_reason if run.stop_reason != "completed" else "coordinator_error"
        return {"route": {}, "next_step": "finalize"}


def route_sources(state):
    if state.get("next_step") == "finalize":
        return "finalize"
    route = state["route"]
    nodes = (["documents"] if route["needs_docs"] else []) + (
        ["database"] if route["needs_db"] else []
    )
    return nodes or ["generate"]


async def documents(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
    try:
        await run.services.search_documents(state["question"], run)
    except Exception as exc:
        _failure(run, "documents", exc)
    return {}


async def database(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
    try:
        await run.services.query_database(state["question"], run)
    except Exception as exc:
        _failure(run, "database", exc)
    return {}


async def generate(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
    try:
        if run.stop_reason != "completed":
            return {"next_step": "finalize"}
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
            return {
                "messages": [
                    *history,
                    ai,
                    ToolMessage(
                        "Candidate submitted for verification.", tool_call_id=final_calls[0]["id"]
                    ),
                ],
                "candidate": candidate,
                "feedback": "",
                "next_step": "guard",
            }
        if not ai.tool_calls:
            # Prompt correction is bounded by the same generator-turn limit.
            return {
                "messages": [*history, ai],
                "feedback": "Use tools or submit_answer to finish.",
                "next_step": "generate",
            }
        return {"messages": [*history, ai], "feedback": "", "next_step": "tools"}
    except Exception as exc:
        _failure(run, "generate", exc)
        if run.stop_reason == "completed":
            run.stop_reason = "generation_error"
        return {"next_step": "finalize"}


async def tools(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
    messages = []
    for call in state["messages"][-1].tool_calls:
        event = run.event("dispatch." + call["name"], call["args"])
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
        messages.append(ToolMessage(json.dumps(output), tool_call_id=call["id"]))
    return {
        "messages": messages,
        "next_step": "generate" if run.stop_reason == "completed" else "finalize",
    }


async def guard(state, runtime: Runtime[RunContext]):
    run = runtime.context["run"]
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
            return {"next_step": "finalize"}
        if state.get("corrections", 0) < run.settings.max_corrections:
            return {
                "corrections": state.get("corrections", 0) + 1,
                "feedback": verdict["feedback"],
                "next_step": "generate",
            }
        run.stop_reason = "verification_exhausted"
    except Exception as exc:
        _failure(run, "guard", exc)
        run.stop_reason = str(exc) if isinstance(exc, LimitReached) else "verification_error"
    return {"candidate": {}, "next_step": "finalize"}


def response(state, run):
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
        "run_id": run.run_id,
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
        "tool_calls": run.tool_calls,
        "aggregation_artifacts": run.aggregation_artifacts,
        "generator_contexts": run.generator_contexts,
        "guardrail_history": run.guardrail_history,
        "execution_trace": run.trace,
        "effective_limits": run.settings.model_dump(exclude={"openrouter_api_key"}),
        "index_fingerprint": run.services.documents.fingerprint,
    }


def finalize(state, runtime: Runtime[RunContext]):
    return {"response": response(state, runtime.context["run"])}
