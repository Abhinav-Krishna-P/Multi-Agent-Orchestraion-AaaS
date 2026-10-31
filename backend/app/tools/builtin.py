"""Tools that need no outside service."""
import ast
import math
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

NOT_ARITHMETIC = "I can only do arithmetic."
TOO_LARGE = "That number is too large for me to work out."
# Whole numbers are capped at about 300 digits. The cap is checked BEFORE a power is
# computed and after every other step, because Python would otherwise happily spend
# minutes and gigabytes building a number like ((10**1000)**1000)**1000.
MAX_BITS = 1000

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


def _checked(value):
    if isinstance(value, int) and value.bit_length() > MAX_BITS:
        raise OverflowError
    return value


def _power(base, exponent):
    if isinstance(base, int) and isinstance(exponent, int) and exponent > 0:
        # The result has at least (bit_length(base) - 1) * exponent bits: refuse before
        # computing it. What gets through is at most about twice the cap, which is cheap,
        # and _checked() then refuses it.
        if (abs(base).bit_length() - 1) * exponent > MAX_BITS:
            raise OverflowError
    elif abs(exponent) > MAX_BITS:
        raise OverflowError
    return operator.pow(base, exponent)


def _evaluate(node: ast.AST):
    """Walks the parsed expression and allows only numbers, arithmetic and a few functions.
    The text is never executed, so it cannot reach files, imports or attributes."""
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _checked(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            return _checked(_power(left, right))
        return _checked(_BINARY[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and not node.keywords
    ):
        return _checked(_FUNCTIONS[node.func.id](*[_evaluate(arg) for arg in node.args]))
    raise ValueError("not arithmetic")


def _calculate(expression: str) -> tuple[str, bool]:
    """The answer in words, and whether it is a result (rather than a refusal)."""
    try:
        result = _evaluate(ast.parse(expression.strip(), mode="eval").body)
        if isinstance(result, float):
            if math.isinf(result) or math.isnan(result):
                return TOO_LARGE, False
            return str(float(f"{result:.12g}")), True  # hide float noise such as 0.30000000000000004
        if isinstance(result, int) and not isinstance(result, bool):
            return str(result), True
        return NOT_ARITHMETIC, False
    except ZeroDivisionError:
        return "That divides by zero.", False
    except OverflowError:
        return TOO_LARGE, False
    except Exception:
        return NOT_ARITHMETIC, False


# Each tool returns its text for the model and, when it worked, a card for the chat.
@tool(response_format="content_and_artifact")
def calculator(expression: str) -> tuple[str, dict | None]:
    """Work out an arithmetic expression exactly. Use this for any calculation instead of
    doing it in your head. Supports + - * / // % **, parentheses, and sqrt, abs, round,
    min, max. Example: "(1250 * 3) / 4"."""
    text, worked = _calculate(expression)
    card = {"kind": "calculation", "service": "Calculator", "expression": expression.strip(), "result": text}
    return text, {"card": card} if worked else None


@tool(response_format="content_and_artifact")
def get_current_datetime(timezone: str = "UTC") -> tuple[str, dict | None]:
    """Get the current date, time and weekday. Use this whenever the answer depends on
    today's date or the time now; you do not know them otherwise. `timezone` is an IANA
    name such as "Asia/Kolkata" or "Europe/London"."""
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        return f"I don't know the time zone '{timezone}'.", None
    offset = now.strftime("%z")
    offset = f"UTC{offset[:3]}:{offset[3:]}"
    card = {"kind": "clock", "service": "Clock", "weekday": f"{now:%A}", "date": f"{now:%d %B %Y}",
            "time": f"{now:%H:%M}", "timezone": timezone, "offset": offset}
    return f"{now:%A, %d %B %Y, %H:%M:%S} ({timezone}, {offset})", {"card": card}
