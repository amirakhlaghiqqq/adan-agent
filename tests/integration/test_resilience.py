import asyncio
import json

from conftest import final, tool


async def test_coordinator_fallback_is_explicit_and_credentials_are_absent(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [
                ValueError("Model is unavailable"),
                {"needs_docs": False, "needs_db": False},
            ],
            "generate": [final("I can help with CloudScale.")],
            "guard": [{"passed": True, "feedback": ""}],
        },
        openrouter_api_key="test-private-value",
    )
    result = await assistant.ask("Hello")
    routing = [e for e in result["execution_trace"] if e["name"] == "model.coordinator"]
    assert [e["inputs"]["fallback"] for e in routing] == [False, True]
    assert "test-private-value" not in json.dumps(result, default=str)


async def test_transient_tool_retry_is_traced_without_inventing_absence(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["support"]}],
            "generate": [
                final(
                    "I could not retrieve support policy information.",
                    status="insufficient_evidence",
                )
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )

    def unavailable(query):
        raise TimeoutError("Search unavailable")

    assistant.documents.search = unavailable
    result = await assistant.ask("What support is available?")
    assert [c["attempt"] for c in result["retrieval_calls"]] == [1, 2]
    assert all(c["status"] == "error" for c in result["retrieval_calls"])
    assert result["status"] == "insufficient_evidence"


async def test_unverified_answer_is_never_delivered_after_correction_limit(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [final("Unverified claim.") for _ in range(3)],
            "guard": [{"passed": False, "feedback": "Unsupported claim."} for _ in range(3)],
        }
    )
    result = await assistant.ask("Hello")
    assert result["stop_reason"] == "verification_exhausted"
    assert result["answer"] != "Unverified claim."
    assert len(result["guardrail_history"]) == 3


async def test_request_deadline_returns_a_finished_trace(make_assistant):
    assistant, models = make_assistant(
        {}, request_timeout_seconds=0.01, model_timeout_seconds=0.01, transient_retries=0
    )

    async def stalled(*args, **kwargs):
        await asyncio.sleep(1)

    models.call = stalled
    result = await assistant.ask("Hello")
    assert result["stop_reason"] == "request_timeout"
    assert all(e["status"] != "running" for e in result["execution_trace"])


async def test_parallel_requests_cannot_share_evidence(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False} for _ in range(2)],
            "generate": [final("First"), final("Second")],
            "guard": [{"passed": True, "feedback": ""} for _ in range(2)],
        }
    )
    a, b = await asyncio.gather(assistant.ask("Hello A"), assistant.ask("Hello B"))
    assert a["run_id"] != b["run_id"]
    assert "Hello B" not in json.dumps(a["generator_contexts"])
    assert "Hello A" not in json.dumps(b["generator_contexts"])


async def test_followup_limit_blocks_more_searches(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [tool("search_documents", {"query": "billing"})],
        },
        max_document_followups=0,
    )
    result = await assistant.ask("Hello")
    assert result["stop_reason"] == "max_document_followups"
    assert result["retrieval_calls"] == []


def test_graph_factory_supports_introspection_without_credentials():
    from adan.agent import build_graph

    graph = build_graph()
    assert "question" in graph.get_input_jsonschema()["properties"]
    assert "coordinator" in graph.get_graph().nodes


async def test_tool_dispatch_trace_includes_completion_times(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [
                tool("calculate", {"operation": "evaluate", "expression": "1+1"}),
                final("The result is 2."),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Calculate 1+1")
    assert all("finished_at" in e and "duration_ms" in e for e in result["execution_trace"])


async def test_successful_evidence_is_kept_when_second_search_fails(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["first", "second"]}],
            "generate": [
                final(
                    "Some policy text was retrieved; the second search failed.",
                    ["billing-p1-s1"],
                    status="partial",
                )
            ],
            "guard": [{"passed": True, "feedback": ""}],
        },
        transient_retries=0,
    )
    original = assistant.documents.search

    def search(query):
        if query == "second":
            raise TimeoutError("Unavailable")
        return original(query)

    assistant.documents.search = search
    result = await assistant.ask("Compare these policies")
    assert result["status"] == "partial"
    assert result["citations"][0]["chunk_id"] == "billing-p1-s1"
