from types import SimpleNamespace

import pytest

from adan.utils.nodes import _database_rate_currency_feedback


@pytest.fixture
def run_with_monthly_rate():
    return SimpleNamespace(
        question="List the highest monthly rates.",
        input_context=[],
        database_results=[
            {
                "sql": "SELECT monthly_rate FROM subscriptions ORDER BY monthly_rate DESC",
                "columns": ["monthly_rate"],
                "rows": [[4800.0], [4200.0]],
            }
        ],
    )


@pytest.mark.parametrize(
    "answer",
    [
        "The rate is $4800.0.",
        "The rate is $4,800.00.",
        "The rate is 4,800.0 USD.",
    ],
)
def test_currency_labels_for_database_rates_are_rejected(run_with_monthly_rate, answer):
    feedback = _database_rate_currency_feedback({"answer": answer}, run_with_monthly_rate)

    assert feedback and "currency units" in feedback


def test_unlabelled_rate_and_explicit_user_assumption_are_allowed(run_with_monthly_rate):
    candidate = {"answer": "The stored rate is 4,800 currency units."}
    assert _database_rate_currency_feedback(candidate, run_with_monthly_rate) is None

    run_with_monthly_rate.question = "Assume the stored rates are USD. List the highest rate."
    candidate["answer"] = "The stored rate is $4,800."
    assert _database_rate_currency_feedback(candidate, run_with_monthly_rate) is None


def test_currency_labels_without_monthly_rate_evidence_are_not_rejected(run_with_monthly_rate):
    run_with_monthly_rate.database_results[0]["sql"] = "SELECT customer_id FROM subscriptions"

    assert (
        _database_rate_currency_feedback({"answer": "Customer id is $4800."}, run_with_monthly_rate)
        is None
    )
