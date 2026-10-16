"""Tools that need no outside service."""
import ast
import math
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

NOT_ARITHMETIC = "I can only do arithmetic."
TOO_LARGE = "That number is too large for me to work out."
MAX_EXPONENT = 1000
MAX_DIGITS = 300

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCTIONS = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max}


def _evaluate(node: ast.AST):
    """Walks the parsed expression and allows only numbers, arithmetic and a few functions.
    The text is never executed, so it cannot reach files, imports or attributes."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise OverflowError
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](*[_evaluate(arg) for arg in node.args])
    raise ValueError("not arithmetic")


@tool
def calculator(expression: str) -> str:
    """Work out an arithmetic expression exactly. Use this for any calculation instead of
    doing it in your head. Supports + - * / // % **, parentheses, and sqrt, abs, round,
    min, max. Example: "(1250 * 3) / 4"."""
    try:
        result = _evaluate(ast.parse(expression.strip(), mode="eval").body)
        if isinstance(result, float):
            if math.isinf(result) or math.isnan(result):
                return TOO_LARGE
            return str(float(f"{result:.12g}"))  # hide float noise such as 0.30000000000000004
        if isinstance(result, int) and not isinstance(result, bool):
            return TOO_LARGE if abs(result) >= 10**MAX_DIGITS else str(result)
        return NOT_ARITHMETIC
    except ZeroDivisionError:
        return "That divides by zero."
    except OverflowError:
        return TOO_LARGE
    except Exception:
        return NOT_ARITHMETIC


@tool
def get_current_datetime(timezone: str = "UTC") -> str:
    """Get the current date, time and weekday. Use this whenever the answer depends on
    today's date or the time now; you do not know them otherwise. `timezone` is an IANA
    name such as "Asia/Kolkata" or "Europe/London"."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        return f"I don't know the time zone '{timezone}'."
    offset = now.strftime("%z")
    return f"{now:%A, %d %B %Y, %H:%M:%S} ({timezone}, UTC{offset[:3]}:{offset[3:]})"
