import json
import sys
from pathlib import Path

import pytest
from conftest import final

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evals.agent_assessment import (  # noqa: E402
    base_assessment,
    calculator_checks,
    exact_arithmetic,
    guard_inputs,
    projected_database_check,
    resolve_citations,
)


def test_independent_arithmetic_accepts_equivalents_and_rejects_code():
    assert exact_arithmetic("(41760 - 140) / 41760 * 100") == exact_arithmetic("100 - 14000/41760")
    with pytest.raises(ValueError):
        exact_arithmetic("__import__('os').system('false')")
    with pytest.raises(ValueError):
        exact_arithmetic("10**10000")


def test_calculator_verifier_detects_wrong_and_missing_results():
    case = {"expected_calculations": [{"calculation_id": "C1", "expected_result": 2}]}
    call = {
        "event_id": "one",
        "status": "ok",
        "inputs": {"operation": "evaluate", "expression": "4/2"},
        "output": {"value": "2", "numerator": 2, "denominator": 1},
    }
    good = calculator_checks({"calculator_trace": [call]}, case)
    assert good["execution_accuracy"] == good["reference_value_coverage"] == 1
    call["output"]["numerator"] = 3
    bad = calculator_checks({"calculator_trace": [call]}, case)
    assert bad["execution_accuracy"] == bad["reference_value_coverage"] == 0
    missing = calculator_checks({"calculator_trace": []}, case)
    assert missing["execution_accuracy"] is None
    assert missing["reference_value_coverage"] == 0


def test_database_comparator_accepts_column_and_row_reordering_but_not_duplicates():
    expected = {"columns": ["name", "value"], "rows": [["A", 1], ["B", 2]]}
    actual = {"columns": ["value", "name"], "rows": [[2, "B"], [1, "A"]]}
    assert projected_database_check(expected, [actual])[0]["exact_multiset_match"]
    actual["rows"].append([1, "A"])
    assert not projected_database_check(expected, [actual])[0]["exact_multiset_match"]


async def test_reference_route_check_rejects_a_plausible_wrong_route(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [final("Hello")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    response = await assistant.ask("Hello")
    record = {"response": response, "request": {"question": "Hello", "input_context": []}}
    case = {
        "question_id": "one",
        "question": "Hello",
        "expected_needs_docs": True,
        "expected_needs_db": False,
    }
    row, _ = base_assessment("coordinator", case, record, {})
    assert row["coordinator_score"] == 0
    assert row["generate_score"] == "NO_REFERENCE"
    assert row["finalize_score"] == 1
    candidates = guard_inputs(response)
    assert len(candidates) == 1
    assert "Hello" in json.dumps(candidates[0]["messages"])
    # The independent guard judge never sees the agent critic's decision.
    assert "passed" not in candidates[0]


def test_missing_response_is_an_evaluation_error_not_a_zero():
    row, _ = base_assessment(
        "coordinator",
        {"question_id": "one", "question": "Hello"},
        {"error": "ReadTimeout", "response": None},
        {},
    )
    assert row["coordinator_score"] == "EVALUATION_ERROR"


def test_citations_are_resolved_from_the_real_source_not_agent_text():
    root = Path(__file__).resolve().parents[2]
    response = {
        "citations": [
            {
                "chunk_id": "one",
                "source_file": "enterprise_billing_and_refund_policy.pdf",
                "page_number": 1,
                "text": "Fabricated source text",
            }
        ]
    }
    passages, errors = resolve_citations(response, root)
    assert not errors
    assert "Fabricated source text" not in passages[0]["text"]
    assert "CloudScale" in passages[0]["text"]
    response["citations"][0]["page_number"] = 999
    passages, errors = resolve_citations(response, root)
    assert not passages and errors
