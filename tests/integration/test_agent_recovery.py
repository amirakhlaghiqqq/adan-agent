import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from conftest import final, tool
from langchain_core.messages import AIMessage
from openai import RateLimitError


@pytest.mark.parametrize("bad_sql", ["SELECT s.tier FROM subscriptions s", "SELECT FROM"])
async def test_sql_repairs_schema_or_syntax_error_with_actual_feedback(make_assistant, bad_sql):
    assistant, models = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": True}],
            "formulate": [{"request": "Count customers"}],
            "sql": [{"sql": bad_sql}, {"sql": "SELECT COUNT(*) AS n FROM customers"}],
            "generate": [final("There are 30 customers.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Count customers")
    assert result["status"] == "complete"
    assert [c["status"] for c in result["database_calls"]] == ["error", "ok"]
    assert result["database_results"][0]["rows"] == [[30]]
    assert len(models.calls["formulate"]) == 1
    assert len(models.calls["sql"]) == 2
    repair = models.calls["sql"][1][-1]["content"]
    assert bad_sql in repair and "error" in repair
    assert "CREATE TABLE customers" in models.calls["sql"][1][1]["content"]


async def test_sql_repair_is_bounded(make_assistant):
    assistant, models = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": True}],
            "formulate": [{"request": "Fetch customer tier"}],
            "sql": [{"sql": "SELECT missing FROM customers"}] * 2,
            "generate": [
                final("I could not acquire customer facts.", status="insufficient_evidence")
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Fetch customer tier")
    assert len(models.calls["sql"]) == 2
    assert len(result["database_calls"]) == 2
    assert result["database_results"] == []
    assert result["failures"][0]["stage"] == "database"


@pytest.mark.parametrize("malformed_json", [False, True])
async def test_generator_repairs_invalid_submission_instead_of_terminating(
    make_assistant, malformed_json
):
    invalid = (
        AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "id": "bad",
                    "name": "submit_answer",
                    "args": "{bad",
                    "error": "Invalid JSON",
                }
            ],
        )
        if malformed_json
        else tool(
            "submit_answer",
            {
                "answer": "I can help with CloudScale.",
                "status": "complete",
                "missing_information": [],
            },
        )
    )
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [invalid, final("I can help with CloudScale.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Hello")
    assert result["status"] == "complete" and result["stop_reason"] == "completed"
    assert len(result["generator_contexts"]) == 2
    assert "citation_ids" in json.dumps(result["generator_contexts"][1])
    if malformed_json:
        assert result["execution_trace"][1]["output"]["message"]["invalid_tool_calls"]
        assert all(
            not m.get("invalid_tool_calls") for m in result["generator_contexts"][1]["messages"]
        )
    else:
        assert any(m["role"] == "tool" for m in result["generator_contexts"][1]["messages"])
    assert len(result["guardrail_history"]) == 1


async def test_repeated_invalid_submission_still_obeys_turn_limit(make_assistant):
    assistant, models = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [tool("submit_answer", {"answer": "Unverified"})] * 2,
        },
        max_generator_turns=2,
    )
    result = await assistant.ask("Hello")
    assert len(models.calls["generate"]) == 2
    assert result["stop_reason"] == "max_generator_turns"
    assert result["answer"] != "Unverified"


async def test_citation_repair_supplies_exact_chunk_ids(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["billing"]}],
            "generate": [
                final("Policy fact.", ["DOC-BIL-2024-V3 s.1"]),
                final("Policy fact.", ["billing-p1-s1"]),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Find billing policy")
    assert result["status"] == "complete"
    assert "billing-p1-s1" in result["guardrail_history"][0]["feedback"]
    assert result["citations"][0]["chunk_id"] == "billing-p1-s1"
    definitions = result["generator_contexts"][0]["tools"]
    submit = next(t["function"] for t in definitions if t["function"]["name"] == "submit_answer")
    assert submit["parameters"]["properties"]["citation_ids"]["items"]["enum"] == ["billing-p1-s1"]


async def test_exhausted_search_budget_allows_a_verified_missing_information_answer(make_assistant):
    assistant, models = make_assistant(
        {
            "coordinator": [{"needs_docs": True, "needs_db": False}],
            "rewrite": [{"queries": ["policy"]}, {"queries": ["extra pricing"]}],
            "generate": [
                tool("search_documents", {"query": "extra pricing"}),
                tool("search_documents", {"query": "extra pricing again"}),
                final(
                    "The retrieved policy does not establish an exact price.",
                    ["billing-p1-s1"],
                    status="insufficient_evidence",
                ),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        },
        max_document_followups=1,
    )
    result = await assistant.ask("What is the exact overage price?")
    assert result["stop_reason"] == "completed"
    assert result["status"] == "insufficient_evidence"
    assert result["answer"].startswith("The retrieved policy")
    assert len(result["retrieval_calls"]) == 2
    assert len(models.calls["rewrite"]) == 2
    restrictions = [e for e in result["execution_trace"] if e["status"] == "restricted"]
    assert restrictions[0]["output"]["reason"] == "max_document_followups"
    assert "search_documents" not in {
        t["function"]["name"] for t in result["generator_contexts"][-1]["tools"]
    }


async def test_calendar_tool_error_can_be_corrected(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [
                tool(
                    "calculate",
                    {
                        "operation": "date_difference",
                        "start_date": "2024-04-01T00:00:00Z",
                        "end_date": "2024-04-30",
                    },
                ),
                tool(
                    "calculate",
                    {
                        "operation": "date_difference",
                        "start_date": "2024-04-01",
                        "end_date": "2024-04-30",
                    },
                ),
                final("The calendar difference is 29 days."),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("How many days from April 1 to April 30, 2024?")
    assert result["status"] == "complete"
    assert result["calculator_trace"][0]["output"]["value"] == 29
    assert result["failures"][0]["stage"] == "calculate"
    assert "YYYY-MM-DD" in json.dumps(result["generator_contexts"][1])


def rate_limit(retry_after):
    response = httpx.Response(
        429,
        headers={"retry-after": retry_after},
        request=httpx.Request("POST", "https://provider.invalid"),
    )
    return RateLimitError("Rate limited", response=response, body=None)


@pytest.mark.parametrize("header", ["3", "http-date", "invalid"])
async def test_rate_limit_waits_before_a_bounded_retry(make_assistant, monkeypatch, header):
    if header == "http-date":
        header = format_datetime(datetime.now(UTC) + timedelta(seconds=5), usegmt=True)
    pause = AsyncMock()
    monkeypatch.setattr("adan.runtime.asyncio.sleep", pause)
    assistant, models = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [rate_limit(header), final("CloudScale account assistance is available.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Hello")
    assert result["status"] == "complete"
    assert len(models.calls["generate"]) == 2
    pause.assert_awaited_once()
    attempts = [e for e in result["execution_trace"] if e["name"] == "model.generate"]
    assert [e["status"] for e in attempts] == ["error", "ok"]
    delay = attempts[0]["retry_delay_seconds"]
    assert delay == pause.await_args.args[0]
    assert 1 <= delay <= 5
    if header == "3":
        assert delay == 3


async def test_long_rate_limit_skips_retry_and_preserves_router_fallback(
    make_assistant, monkeypatch
):
    pause = AsyncMock()
    monkeypatch.setattr("adan.runtime.asyncio.sleep", pause)
    assistant, models = make_assistant(
        {
            "coordinator": [rate_limit("86400"), {"needs_docs": False, "needs_db": False}],
            "generate": [final("CloudScale account assistance is available.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    result = await assistant.ask("Hello")
    assert result["status"] == "complete"
    pause.assert_not_awaited()
    assert len(models.calls["coordinator"]) == 2
    attempt = result["execution_trace"][0]
    assert attempt["retry_skipped"] == "insufficient_request_time"
    assert attempt["output"]["http_status"] == 429
    assert all("finished_at" in e for e in result["execution_trace"])
