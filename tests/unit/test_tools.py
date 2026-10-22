from fractions import Fraction
from pathlib import Path

import pytest

from adan.calculator import calculate
from adan.database import Database, UnsafeSQL


def test_exact_arithmetic_and_calendar_operations():
    result = calculate("evaluate", expression="(1 - 140 / 41760) * 100")
    assert Fraction(result["numerator"], result["denominator"]) == (1 - Fraction(140, 41760)) * 100
    assert calculate("month_minutes", year=2024, month=2)["value"] == 41760
    assert calculate("month_minutes", year=2025, month=2)["value"] == 40320
    assert (
        calculate("date_difference", start_date="2024-02-28", end_date="2024-03-01")["value"] == 2
    )
    assert calculate("evaluate", expression="2.675")["money_display"] == "2.68"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "True+1",
        "1/0",
        "2**101",
        "1e101",
        "[1]",
        "1e999",
        "9**9**9",
        "1+" * 600,
        "x",
        "(1).__class__",
    ],
)
def test_calculator_rejects_unsafe_or_unbounded_expressions(expression):
    with pytest.raises(ValueError):
        calculate("evaluate", expression=expression)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation": "month_minutes", "year": 2024, "month": 13},
        {"operation": "month_minutes", "year": True, "month": 1},
        {"operation": "date_difference", "start_date": "2024-02-30", "end_date": "2024-03-01"},
    ],
)
def test_invalid_calendar_inputs(kwargs):
    with pytest.raises(ValueError):
        calculate(**kwargs)


def test_database_supports_parameters_joins_and_aggregation():
    db = Database(Path("data/database/app.db"))
    result = db.query(
        "SELECT COUNT(*) AS n FROM customers WHERE tier = :tier", {"tier": "Enterprise"}
    )
    assert result["columns"] == ["n"]
    assert result["rows"][0][0] > 0
    joined = db.query(
        "SELECT c.company_name, s.monthly_rate "
        "FROM customers c JOIN subscriptions s USING(customer_id)"
    )
    assert len(joined["rows"]) == 30
    assert "incident_tickets" in db.schema


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM customers",
        "SELECT 1; DROP TABLE customers",
        "PRAGMA writable_schema=1",
        "ATTACH DATABASE '/tmp/evil.db' AS evil",
        "SELECT load_extension('evil')",
        "WITH a AS (SELECT 1) DELETE FROM customers",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM readfile('/etc/passwd')",
        "SELECT randomblob(1000000000)",
    ],
)
def test_database_guard_blocks_unsafe_sql_and_preserves_source(sql):
    path = Path("data/database/app.db")
    original = path.read_bytes()
    with pytest.raises(UnsafeSQL):
        Database(path).query(sql)
    assert path.read_bytes() == original
