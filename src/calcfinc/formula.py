"""Restricted Decimal formula evaluator -- the one place ratio maths is defined.

Allowed: number literals (read from the source text, so `0.1` is exactly Decimal("0.1")),
+ - * / **, unary +/-, parentheses, names bound in the environment (dotted names such as
`bank.advances` are looked up as strings, never as attributes), and the functions
abs, min, max, round, sqrt, prior(name) and ttm(name). `ttm(x)` is the sum of `x` over the latest
adjacent periods that make up a year (4 quarters, 12 months...). `prior(x)` is the value of `x` one comparable
period earlier. Everything else raises CalcError (a ValueError).
"""
from __future__ import annotations

import ast
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException
from typing import Any

from calcfinc.num import CTX, add, div, mul, power, sqrt, sub, to_decimal


class CalcError(ValueError):
    pass


class MissingInput(CalcError):
    def __init__(self, name: str) -> None:
        super().__init__(f"missing input: {name}")
        self.name = name


WINDOWED = ("prior", "ttm")          # functions that read other periods; they take one metric name
_FUNCS = {"abs", "min", "max", "round", "sqrt", *WINDOWED}


def _parse(expr: str) -> ast.Expression:
    try:
        return ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise CalcError(f"cannot parse expression: {e}") from e


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def names_in(expr: str) -> tuple[str, ...]:
    """Input names in first-appearance order. A name inside prior(...) is returned as
    'prior(name)' so callers can tell it apart from the current-period value."""
    out: dict[str, None] = {}

    def walk(node: ast.AST, in_prior: bool) -> None:
        if isinstance(node, ast.Call):
            fn = node.func.id if isinstance(node.func, ast.Name) else None
            if fn in WINDOWED and len(node.args) == 1:
                inner = _dotted(node.args[0])
                if inner is None:
                    raise CalcError(f"{fn}() takes a single metric name")
                out[f"{fn}({inner})"] = None
                return
            for a in node.args:
                walk(a, in_prior)
            return
        name = _dotted(node)
        if name is not None:
            out[name] = None
            return
        for child in ast.iter_child_nodes(node):
            walk(child, in_prior)

    walk(_parse(expr).body, False)
    return tuple(out)


def evaluate(expr: str, env: Mapping[str, Any]) -> Decimal:
    tree = _parse(expr)

    def lookup(name: str) -> Decimal:
        if name not in env:
            raise CalcError(f"unknown variable: {name!r}")
        v = env[name]
        if v is None:
            raise MissingInput(name)
        try:
            return to_decimal(v)
        except (TypeError, ValueError) as e:
            raise CalcError(f"variable {name!r}: {e}") from e

    def ev(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                text = ast.get_source_segment(expr, node) or ""
                try:
                    return to_decimal(text.replace("_", ""))
                except ValueError:
                    raise CalcError(f"unsupported number literal: {text!r}") from None
            raise CalcError(f"disallowed constant: {node.value!r}")
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Add):
                return add(a, b)
            if isinstance(node.op, ast.Sub):
                return sub(a, b)
            if isinstance(node.op, ast.Mult):
                return mul(a, b)
            if isinstance(node.op, ast.Div):
                if b == 0:
                    raise CalcError("division by zero")
                return div(a, b)
            if isinstance(node.op, ast.Pow):
                if a == 0 and b < 0:
                    raise CalcError("division by zero")
                return power(a, b)
            raise CalcError(f"disallowed operator: {type(node.op).__name__}")
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            if isinstance(node.op, ast.USub):
                return v.copy_negate()
            if isinstance(node.op, ast.UAdd):
                return v
            raise CalcError(f"disallowed operator: {type(node.op).__name__}")
        if isinstance(node, (ast.Name, ast.Attribute)):
            name = _dotted(node)
            if name is None:
                raise CalcError("disallowed attribute access")
            return lookup(name)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise CalcError(f"only {', '.join(sorted(_FUNCS))} calls are allowed")
            if node.keywords:
                raise CalcError("keyword arguments are not allowed")
            fn = node.func.id
            if fn in WINDOWED:
                inner = _dotted(node.args[0]) if len(node.args) == 1 else None
                if inner is None:
                    raise CalcError(f"{fn}() takes a single metric name")
                return lookup(f"{fn}({inner})")
            args = [ev(a) for a in node.args]
            if fn == "abs" and len(args) == 1:
                return args[0].copy_abs()
            if fn in ("min", "max") and args:
                return min(args) if fn == "min" else max(args)
            if fn == "sqrt" and len(args) == 1:
                if args[0] < 0:
                    raise CalcError("sqrt of a negative number")
                return sqrt(args[0])
            if fn == "round" and len(args) in (1, 2):
                places = 0 if len(args) == 1 else int(args[1])
                if len(args) == 2 and args[1] != places:
                    raise CalcError("round() places must be a whole number")
                return args[0].quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN, context=CTX)
            raise CalcError(f"wrong arguments for {fn}()")
        raise CalcError(f"disallowed syntax: {type(node).__name__}")

    try:
        return ev(tree)
    except DecimalException as e:
        raise CalcError(f"arithmetic error: {type(e).__name__}") from e


def calculate(expr: str, **vars: Any) -> Decimal:
    """Evaluate `expr` over the keyword variables. Values must be int, str or Decimal."""
    return evaluate(expr, vars)
