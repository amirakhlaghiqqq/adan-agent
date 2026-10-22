"""Bounded arithmetic without eval; preserve rational values for policy comparisons."""

import ast
import calendar
import math
import operator
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction

OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
MAX_VALUE = 10**100


def _evaluate(expression: str) -> Fraction:
    if not isinstance(expression, str) or not 0 < len(expression) <= 1000:
        raise ValueError("Expression must contain 1 to 1000 characters")
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 100:
            raise ValueError("Expression exceeds 100 AST nodes")

        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                if isinstance(node.value, float) and not math.isfinite(node.value):
                    raise ValueError("Non-finite operand")
                number = Decimal(ast.get_source_segment(expression, node).replace("_", ""))
                if abs(number) > MAX_VALUE:
                    raise ValueError("Operand magnitude exceeds 1e100")
                value = Fraction(number)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and (right.denominator != 1 or abs(right) > 100):
                    raise ValueError("Exponent must be an integer between -100 and 100")
                value = OPERATORS[type(node.op)](left, right)
            else:
                raise ValueError("Only numeric arithmetic is permitted")
            if abs(value) > MAX_VALUE:
                raise ValueError("Result magnitude exceeds 1e100")
            return value

        return visit(tree.body)
    except (SyntaxError, ArithmeticError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid or unbounded arithmetic expression") from exc


def calculate(operation: str, **inputs) -> dict:
    if operation == "evaluate":
        value = _evaluate(inputs["expression"])
        with localcontext() as context:
            context.prec = 220
            decimal = Decimal(value.numerator) / Decimal(value.denominator)
            return {
                "operation": operation,
                "inputs": inputs,
                "value": str(decimal),
                "numerator": value.numerator,
                "denominator": value.denominator,
                "money_display": str(decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                "units": "number",
                "status": "ok",
            }
    if operation == "month_minutes":
        year, month = inputs["year"], inputs["month"]
        if (
            type(year) is not int
            or type(month) is not int
            or not 1 <= year <= 9999
            or not 1 <= month <= 12
        ):
            raise ValueError("Expected year 1..9999 and month 1..12")
        value = calendar.monthrange(year, month)[1] * 24 * 60
        units = "minutes"
    elif operation == "date_difference":
        start, end = inputs["start_date"], inputs["end_date"]
        if len(start) != 10 or len(end) != 10:
            raise ValueError("Expected ISO YYYY-MM-DD calendar dates")
        value = (date.fromisoformat(end) - date.fromisoformat(start)).days
        units = "calendar_days"
    else:
        raise ValueError("Unknown calculator operation")
    return {
        "operation": operation,
        "inputs": inputs,
        "value": value,
        "units": units,
        "status": "ok",
    }
