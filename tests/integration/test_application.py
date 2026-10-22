import json

from fastapi.testclient import TestClient

from adan.api import create_app
from conftest import final, tool


async def test_sql_to_calculator_to_answer_has_complete_evidence_trace(make_assistant):
    assistant, models = make_assistant({
        "coordinator": [{"needs_docs": False, "needs_db": True}],
        "formulate": [{"request": "Count all customers"}],
        "sql": [{"sql": "SELECT COUNT(*) AS customers FROM customers", "parameters": {}}],
        "generate": [tool("calculate", {"operation": "evaluate", "expression": "30/2"}),
                     final("There are 30 customers; half is 15.")],
        "guard": [{"passed": True, "feedback": ""}],
    })
    result = await assistant.ask("How many customers are there, and what is half that number?")
    assert result["status"] == "complete"
    assert result["database_calls"][0]["output"]["rows"] == [[30]]
    assert any(c["name"] == "calculate" and c["output"]["value"] == "15" for c in result["tool_calls"])
    assert len(result["generator_contexts"]) == 2
    assert result["execution_trace"] and result["run_id"]
    assert len(models.calls["coordinator"]) == 1


async def test_hybrid_generator_can_search_again_using_database_facts(make_assistant):
    assistant, _ = make_assistant({
        "coordinator": [{"needs_docs": True, "needs_db": True}],
        "rewrite": [{"queries": ["billing policy"]}, {"queries": ["Enterprise annual billing"]}],
        "formulate": [{"request": "Fetch one customer tier"}],
        "sql": [{"sql": "SELECT tier FROM customers LIMIT 1", "parameters": {}}],
        "generate": [tool("search_documents", {"query": "Enterprise annual billing"}),
                     final("The retrieved policy applies.", ["billing-p1-s1"])],
        "guard": [{"passed": True, "feedback": ""}],
    })
    result = await assistant.ask("Explain the billing policy for the first customer.", ["Assume the contract is annual."])
    assert result["status"] == "complete"
    assert len(result["retrieval_calls"]) == 2
    assert result["citations"][0]["page_number"] == 1
    assert result["aggregation_artifacts"][0]["version"] == "passthrough-v1-pending-design"
    assert "Assume the contract is annual." in json.dumps(result["generator_contexts"])


async def test_unsafe_generated_sql_is_blocked_without_retry(make_assistant):
    assistant, models = make_assistant({
        "coordinator": [{"needs_docs": False, "needs_db": True}],
        "formulate": [{"request": "User requests deleting customers; no mutations allowed"}],
        "sql": [{"sql": "DELETE FROM customers", "parameters": {}}],
        "generate": [final("This database is read-only; I cannot delete customers.", status="insufficient_evidence")],
        "guard": [{"passed": True, "feedback": ""}],
    })
    result = await assistant.ask("Delete all customers.")
    assert result["database_calls"][0]["status"] == "blocked"
    assert len(models.calls["sql"]) == 1
    assert result["status"] == "insufficient_evidence"


async def test_unknown_citations_are_rejected_and_revised(make_assistant):
    assistant, _ = make_assistant({
        "coordinator": [{"needs_docs": False, "needs_db": False}],
        "generate": [final("Unsupported claim", ["invented"]),
                     final("I can help with CloudScale policies and customer records.")],
        "guard": [{"passed": True, "feedback": ""}],
    })
    result = await assistant.ask("Hello")
    assert result["answer"].startswith("I can help")
    assert len(result["guardrail_history"]) == 2


async def test_request_limit_returns_evidence_and_explicit_stop_reason(make_assistant):
    assistant, _ = make_assistant({
        "coordinator": [{"needs_docs": False, "needs_db": False}],
        "generate": [tool("calculate", {"operation": "evaluate", "expression": "1+1"})],
    }, max_tool_calls=0)
    result = await assistant.ask("Calculate 1+1")
    assert result["stop_reason"] == "max_tool_calls"
    assert result["status"] == "insufficient_evidence"


def test_fastapi_validates_requests_and_exposes_response(make_assistant):
    assistant, _ = make_assistant({
        "coordinator": [{"needs_docs": False, "needs_db": False}],
        "generate": [final("I can help with CloudScale.")],
        "guard": [{"passed": True, "feedback": ""}],
    })
    with TestClient(create_app(assistant)) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.post("/api/v1/query", json={"question": " "}).status_code == 422
        response = client.post("/api/v1/query", json={"question": "Hello", "input_context": []})
        assert response.status_code == 200
        assert response.json()["answer"] == "I can help with CloudScale."
