"""Exact decimal arithmetic for the whole library.

Floats never enter: `to_decimal` refuses them. Every operation runs in one dedicated context,
so results do not depend on the caller's global `decimal` settings.

Each operation is correctly rounded to PREC (34) significant digits, round-half-even. Sums,
differences and products are therefore exact whenever the result has at most 34 digits, which
covers any realistic financial figure; division and powers (1/3 has no finite decimal form)
carry at most half a unit in the 34th digit of error per operation.
"""
from __future__ import annotations

from collections.abc import Iterable
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
)

PREC = 34
CTX = Context(prec=PREC, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999,
              traps=[InvalidOperation, DivisionByZero, Overflow])

Num = Decimal | int | str

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


def to_decimal(v: object) -> Decimal:
    """Coerce int / str / Decimal to a finite Decimal of at most PREC digits.
    float and bool raise TypeError; NaN, infinity and unparsable text raise ValueError."""
    if isinstance(v, bool) or isinstance(v, float):
        raise TypeError(f"{type(v).__name__} is not accepted (floats are inexact); "
                        "pass an int, a str such as '12.50', or a Decimal")
    if isinstance(v, Decimal):
        d = v
    elif isinstance(v, int):
        d = Decimal(v)
    elif isinstance(v, str):
        try:
            d = Decimal(v.strip())
        except InvalidOperation:
            raise ValueError(f"not a number: {v!r}") from None
    else:
        raise TypeError(f"cannot convert {type(v).__name__} to Decimal")
    if not d.is_finite():
        raise ValueError(f"not a finite number: {v!r}")
    if len(d.as_tuple().digits) > PREC:
        raise ValueError(f"more than {PREC} significant digits: {v!r}")
    return d


def add(a: Decimal, b: Decimal) -> Decimal:
    return CTX.add(a, b)


def sub(a: Decimal, b: Decimal) -> Decimal:
    return CTX.subtract(a, b)


def mul(a: Decimal, b: Decimal) -> Decimal:
    return CTX.multiply(a, b)


def div(a: Decimal, b: Decimal) -> Decimal:
    return CTX.divide(a, b)


def power(a: Decimal, b: Decimal) -> Decimal:
    return CTX.power(a, b)


def sqrt(a: Decimal) -> Decimal:
    return CTX.sqrt(a)


def dsum(values: Iterable[Decimal]) -> Decimal:
    """Sum in the library context (the built-in sum() would use the caller's global one)."""
    total = ZERO
    for v in values:
        total = add(total, v)
    return total


def to_text(d: Decimal) -> str:
    """Canonical plain-notation string (never an exponent); round-trips through to_decimal."""
    return format(d, "f")
