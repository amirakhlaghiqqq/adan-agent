import pytest

from adan.service import _unrequested_monthly_cycle_filter


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(monthly_rate) FROM subscriptions WHERE billing_cycle = 'monthly'",
        "SELECT SUM(monthly_rate) FROM subscriptions WHERE billing_cycle IN ('monthly')",
    ],
)
def test_monthly_rate_does_not_imply_monthly_billing_cycle(sql):
    assert _unrequested_monthly_cycle_filter(sql, "Sum monthly_rate for active customers", [])


def test_explicit_monthly_cycle_filter_and_unrelated_sql_are_allowed():
    filtered = "SELECT monthly_rate FROM subscriptions WHERE billing_cycle = 'monthly'"
    unrelated = "SELECT COUNT(*) FROM subscriptions WHERE billing_cycle = 'monthly'"

    assert not _unrequested_monthly_cycle_filter(
        filtered, "Sum rates for monthly billing cycle subscriptions", []
    )
    assert not _unrequested_monthly_cycle_filter(unrelated, "Count monthly subscriptions", [])
