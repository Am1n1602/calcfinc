"""Growth maths: absolute change, % change, CAGR. A zero or negative base gives no % (report
the absolute change instead)."""
from __future__ import annotations

from decimal import Decimal

from calcfinc.num import HUNDRED, ONE, ZERO, div, mul, power, sub


def abs_change(prev: Decimal | None, curr: Decimal | None) -> Decimal | None:
    if prev is None or curr is None:
        return None
    return sub(curr, prev)


def pct_change(prev: Decimal | None, curr: Decimal | None) -> Decimal | None:
    if prev is None or curr is None or prev <= ZERO:
        return None                      # % is not meaningful off a zero / negative base
    return div(mul(sub(curr, prev), HUNDRED), prev)


def cagr(start: Decimal | None, end: Decimal | None, years: Decimal | None) -> Decimal | None:
    """Compound annual growth rate in percent. Needs start > 0, end > 0 and years > 0."""
    if start is None or end is None or years is None:
        return None
    if start <= ZERO or end <= ZERO or years <= ZERO:
        return None
    return mul(sub(power(div(end, start), div(ONE, years)), ONE), HUNDRED)
