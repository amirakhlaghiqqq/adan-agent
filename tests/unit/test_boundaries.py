import pytest
from pydantic import ValidationError

from adan.calculator import calculate
from adan.schemas import Calculate


def test_calendar_tool_schema_does_not_convert_boolean_into_a_year():
    with pytest.raises(ValidationError):
        Calculate(operation="month_minutes", year=True, month=1)


def test_rational_representation_is_bounded_even_for_tiny_numbers():
    with pytest.raises(ValueError):
        calculate("evaluate", expression="(1 / 10**100)**100")


@pytest.mark.parametrize(
    "operation,required",
    [
        ("evaluate", "expression"),
        ("month_minutes", "year, month"),
        ("date_difference", "start_date, end_date"),
    ],
)
def test_calculator_reports_missing_operands(operation, required):
    with pytest.raises(ValidationError, match=required):
        Calculate(operation=operation)
