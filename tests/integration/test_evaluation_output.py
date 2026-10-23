import json
from datetime import datetime

import pytest
from conftest import final, tool
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from adan.api import create_app
from adan.runtime import Run
from adan.schemas import QueryResponse


def test_http_output_contains_hybrid_evaluation_evidence(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": True}],
            "rewrite": [{"queries": ["billing"]}],
            "formulate": [{"request": "Count customers"}],
            "sql": [{"sql": "SELECT COUNT(*) AS count FROM customers", "parameters": {}}],
            "generate": [
                tool("calculate", {"operation": "evaluate", "expression": "30/2"}),
                final("Half of 30 customers is 15. Billing policy retrieved.", ["billing-p1-s1"]),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        },
        openrouter_api_key="private-provider-key",
        qdrant_api_key="private-vector-key",
    )
    question, context = "Count customers, halve the count and cite billing.", ["Use stored facts."]
    with TestClient(create_app(assistant)) as client:
        result = client.post("/api/v1/query", json={"question": question, "input_context": context})
    assert result.status_code == 200
    data = result.json()
    QueryResponse.model_validate(data)
    assert data["schema_version"] == "1.0"
    assert data["mode"] == "end_to_end"
    assert data["question"] == question and data["input_context"] == context
    assert data["retrieved_document_chunks"] == data["retrieval_calls"][0]["output"]
    assert data["database_results"][0]["columns"] == ["count"]
    assert data["database_results"][0]["rows"] == [[30]]
    assert data["calculator_trace"][0]["status"] == "ok"
    assert data["calculator_trace"][0]["inputs"]["expression"] == "30/2"
    assert data["calculator_trace"][0] in data["execution_trace"]
    assert data["aggregation_artifacts"][0]["input_chunks"] == data["retrieved_document_chunks"]
    assert len(data["generator_contexts"]) == 2
    assert '"count"' in data["generator_contexts"][0]["messages"][0]["content"]
    assert data["failures"] == []
    assert data["usage"] == {
        "model_calls": 7,
        "tool_calls": 3,
        "generator_turns": 2,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "cost": None,
    }
    timing = data["timings"]
    assert datetime.fromisoformat(timing["finished_at"]) >= datetime.fromisoformat(
        timing["started_at"]
    )
    assert timing["duration_ms"] >= max(e["duration_ms"] for e in data["execution_trace"])
    assert "private-provider-key" not in result.text and "private-vector-key" not in result.text
    assert "qdrant_api_key" not in data["effective_limits"]


async def test_raw_ranking_survives_truncation_deduplication_and_mutating_aggregation(
    make_assistant,
):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["first", "second"]}],
            "generate": [final("Only aggregated evidence was supplied.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    base = assistant.documents.search("test")[0]

    def search(query):
        ids = range(6) if query == "first" else [0, 6]
        return [{**base, "chunk_id": f"chunk-{i}", "text": f"Raw {i}"} for i in ids]

    class MutatingAggregator:
        def build(self, question, input_context, chunks):
            chunks[0]["text"] = "Aggregated text"
            return {"version": "test", "chunks": chunks[:1]}

    assistant.documents.search = search
    assistant.aggregator = MutatingAggregator()
    data = await assistant.ask("Compare policies")
    assert [c["chunk_id"] for c in data["retrieved_document_chunks"]] == [
        f"chunk-{i}" for i in range(7)
    ]
    assert data["retrieved_document_chunks"][0]["text"] == "Raw 0"
    assert len(data["retrieval_calls"][0]["output"]) == 6
    artifact = data["aggregation_artifacts"][0]
    assert len(artifact["input_chunks"]) == 6  # Five from first query, one new from second.
    assert artifact["input_chunks"][0]["text"] == "Raw 0"
    assert artifact["chunks"][0]["text"] == "Aggregated text"
    assert "Raw 5" not in json.dumps(data["generator_contexts"])


async def test_failed_search_and_calculator_remain_explicit(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["billing"]}],
            "generate": [
                tool("calculate", {"operation": "evaluate", "expression": "1/0"}),
                final("Required evidence is unavailable.", status="insufficient_evidence"),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        },
        transient_retries=0,
    )

    def unavailable(query):
        raise TimeoutError("Unavailable")

    assistant.documents.search = unavailable
    data = await assistant.ask("Find billing and calculate 1/0")
    QueryResponse.model_validate(data)
    assert data["retrieved_document_chunks"] == []
    assert data["retrieval_calls"][0]["status"] == "error"
    assert data["calculator_trace"][0]["status"] == "error"
    assert {f["stage"] for f in data["failures"]} == {"documents", "calculate"}
    assert data["database_results"] == []


@pytest.mark.parametrize("missing_cost", [False, True])
async def test_usage_totals_include_every_model_attempt(make_assistant, missing_cost):
    usage = {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}
    route = AIMessage(
        content=json.dumps({"needs_docs": False, "needs_db": False}),
        usage_metadata=usage,
        response_metadata={"token_usage": {"cost": 0.01}},
    )
    answer = final("Hello")
    answer.usage_metadata = usage
    answer.response_metadata = {} if missing_cost else {"cost": 0.02}
    guard = AIMessage(
        content=json.dumps({"passed": True, "feedback": ""}),
        usage_metadata=usage,
        response_metadata={"cost": 0.0},
    )
    assistant, _ = make_assistant({"coordinator": [route], "generate": [answer], "guard": [guard]})
    data = await assistant.ask("Hello")
    assert data["usage"]["model_calls"] == 3
    assert data["usage"]["input_tokens"] == 30
    assert data["usage"]["output_tokens"] == 6
    assert data["usage"]["total_tokens"] == 36
    if missing_cost:
        assert data["usage"]["cost"] is None
    else:
        assert data["usage"]["cost"] == pytest.approx(0.03)


async def test_routing_failure_still_has_complete_response_contract(make_assistant):
    assistant, _ = make_assistant(
        {"coordinator": [RuntimeError("Unavailable")]}, router_fallback_model=""
    )
    data = await assistant.ask("Hello")
    QueryResponse.model_validate(data)
    assert data["stop_reason"] == "coordinator_error"
    assert data["usage"]["model_calls"] == 1
    assert data["usage"]["total_tokens"] is None
    assert (
        data["retrieved_document_chunks"]
        == data["database_results"]
        == data["calculator_trace"]
        == []
    )
    assert data["failures"][0]["stage"] == "coordinator"


def test_cumulative_ranking_uses_dispatch_order_not_completion_order(make_assistant):
    assistant, _ = make_assistant({})
    run = Run(assistant, "question", [])
    first = {"chunk_id": "first", "score": 0.1}
    second = {"chunk_id": "second", "score": 0.9}
    run.retrieval_calls = [
        {"dispatch_sequence": 2, "status": "ok", "output": [second, first]},
        {"dispatch_sequence": 1, "status": "ok", "output": [first]},
        {"dispatch_sequence": 0, "status": "error", "output": {"error": "failed"}},
    ]
    assert run.retrieved_document_chunks() == [first, second]
