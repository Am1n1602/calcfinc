"""Accounting-identity checks on a period record. 

Filings are rounded, so a check passes when the mismatch is within
max(abs_tol, rel_tol x largest operand). A failed check never drops a record; it is reported
so a caller can route the period to review.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from calcfinc.num import add, dsum, mul, sub

ABS_TOL = Decimal(1)               # one unit of the reporting currency (base units)
REL_TOL = Decimal("0.0005")        # 0.05 % of the largest operand


@dataclass(frozen=True, slots=True)
class CheckResult:
    entity: str
    basis: str
    period: str
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return bool(self.checks)

    @property
    def failed(self) -> list[str]:
        return [k for k, ok in self.checks.items() if not ok]

    @property
    def needs_review(self) -> bool:
        return self.ran and bool(self.failed)


def quarters_add_up(year: Mapping[str, Decimal], quarters: Sequence[Mapping[str, Decimal]],
                    names: Iterable[str], abs_tol: Decimal = ABS_TOL, rel_tol: Decimal = REL_TOL) -> dict[str, bool]:
    """For each amount in `names` that the year and every quarter report: do the quarters sum to the year?"""
    out: dict[str, bool] = {}
    for name in names:
        if name in year and all(name in q for q in quarters):
            total = dsum(q[name] for q in quarters)
            out[f"quarters_sum_eq_year:{name}"] = (
                abs(sub(total, year[name])) <= max(abs_tol, mul(rel_tol, max(abs(total), abs(year[name])))))
    return out


def check_values(v: Mapping[str, Decimal], abs_tol: Decimal = ABS_TOL,
                 rel_tol: Decimal = REL_TOL) -> dict[str, bool]:
    def have(*keys: str) -> bool:
        return all(v.get(k) is not None for k in keys)

    def close(lhs: Decimal, rhs: Decimal, *operands: Decimal) -> bool:
        scale = max(abs(x) for x in operands)
        return abs(sub(lhs, rhs)) <= max(abs_tol, mul(rel_tol, scale))

    c: dict[str, bool] = {}
    if have("total_income", "total_expenses", "pbt_before_exceptional"):
        ti, te, pbe = v["total_income"], v["total_expenses"], v["pbt_before_exceptional"]
        c["income_minus_expenses_eq_pbt_before_exceptional"] = close(sub(ti, te), pbe, ti, te)
    if have("pbt_before_exceptional", "exceptional_items", "pbt"):
        pbe, ex, pbt = v["pbt_before_exceptional"], v["exceptional_items"], v["pbt"]
        c["pbt_before_exceptional_plus_exceptional_eq_pbt"] = close(add(pbe, ex), pbt, pbe, pbt)
    if have("current_tax", "deferred_tax", "tax_expense"):
        ct, dt, tx = v["current_tax"], v["deferred_tax"], v["tax_expense"]
        c["current_plus_deferred_tax_eq_tax_expense"] = close(add(ct, dt), tx, ct, dt, tx)
    if have("pbt", "tax_expense"):
        pbt, tx, eq = v["pbt"], v["tax_expense"], v.get("equity_method_income")

        def after_tax(profit: Decimal) -> bool:
            # Some statements show the share of equity-method investees inside pre-tax profit, others
            # after tax; the identity holds if either presentation reconciles.
            return close(sub(pbt, tx), profit, pbt, profit) or (
                eq is not None and close(add(sub(pbt, tx), eq), profit, pbt, profit))

        if v.get("profit_continuing_ops") is not None:
            c["pbt_minus_tax_eq_profit_continuing_ops"] = after_tax(v["profit_continuing_ops"])
        elif v.get("net_profit") is not None:
            c["pbt_minus_tax_eq_net_profit"] = after_tax(v["net_profit"])
    if have("net_profit", "oci", "total_comprehensive_income"):
        np_, oci, tci = v["net_profit"], v["oci"], v["total_comprehensive_income"]
        c["net_profit_plus_oci_eq_total_comprehensive_income"] = close(add(np_, oci), tci, np_, tci)
    if have("total_assets", "total_liabilities", "total_equity"):
        ta, tl, te = v["total_assets"], v["total_liabilities"], v["total_equity"]
        c["assets_eq_liabilities_plus_equity"] = close(ta, add(tl, te), ta, tl, te)
    if have("current_assets", "noncurrent_assets", "total_assets"):
        ca, nca, ta = v["current_assets"], v["noncurrent_assets"], v["total_assets"]
        c["current_plus_noncurrent_assets_eq_total_assets"] = close(add(ca, nca), ta, ca, nca, ta)
    if have("current_liabilities", "noncurrent_liabilities", "total_liabilities"):
        cl, ncl, tl = v["current_liabilities"], v["noncurrent_liabilities"], v["total_liabilities"]
        c["current_plus_noncurrent_liabilities_eq_total_liabilities"] = close(add(cl, ncl), tl, cl, ncl, tl)
    return c
