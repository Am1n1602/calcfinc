"""Metric decomposition: DuPont ROE (3- and 5-step) and a net-margin bridge between periods."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from calcfinc.engine.evaluate import Evaluator
from calcfinc.num import HUNDRED, ZERO, add, div, mul, sub

_TOLERANCE = Decimal("1e-20")       # the identity must hold to rounding noise, nothing looser


def _reconciles(reconstructed: Decimal | None, actual: Decimal | None) -> bool:
    if reconstructed is None or actual is None:
        return False
    return abs(sub(reconstructed, actual)) <= mul(_TOLERANCE, max(Decimal(1), abs(actual)))


def dupont_roe(ev: Evaluator) -> dict[str, Any]:
    """ROE = net_profit_margin x asset_turnover x equity_multiplier
           = (net_profit / top_line) x (top_line / total_assets) x (total_assets / total_equity)"""
    comps = {n: ev.value(n).value for n in ("net_profit_margin", "asset_turnover", "equity_multiplier")}
    actual = ev.value("roe").value
    npm, at, em = comps["net_profit_margin"], comps["asset_turnover"], comps["equity_multiplier"]
    # npm is already a percent; turnover and multiplier are plain ratios, so the product is
    # the ROE percent directly.
    reconstructed = None if None in (npm, at, em) else mul(mul(npm, at), em)  # type: ignore[arg-type]
    return {"components": comps, "reconstructed_roe_pct": reconstructed, "actual_roe_pct": actual,
            "reconciles": _reconciles(reconstructed, actual)}


def dupont_roe_5(ev: Evaluator) -> dict[str, Any]:
    """ROE = tax_burden x interest_burden x ebit_margin x asset_turnover x equity_multiplier
           = (NI/PBT) x (PBT/EBIT) x (EBIT/top_line) x (top_line/assets) x (assets/equity),
    with EBIT taken as PBT + finance costs so the chain telescopes (this differs from the
    `ebit` quantity, which starts from profit before exceptional items)."""
    np_, pbt, top = (ev.value(n).value for n in ("net_profit", "pbt", "top_line"))
    ta, te = (ev.value(n).value for n in ("total_assets", "total_equity"))
    fc = ev.value("finance_costs").value
    notes = ["finance_costs not reported; treated as 0 in EBIT"] if fc is None else []
    ebit = None if pbt is None else add(pbt, fc if fc is not None else ZERO)
    comps: dict[str, Decimal | None] = {
        "tax_burden": None if None in (np_, pbt) or pbt == 0 else div(np_, pbt),  # type: ignore[arg-type]
        "interest_burden": None if None in (pbt, ebit) or ebit == 0 else div(pbt, ebit),  # type: ignore[arg-type]
        "ebit_margin": None if None in (ebit, top) or top == 0 else div(mul(HUNDRED, ebit), top),  # type: ignore[arg-type]
        "asset_turnover": None if None in (top, ta) or ta == 0 else div(top, ta),  # type: ignore[arg-type]
        "equity_multiplier": None if None in (ta, te) or te == 0 else div(ta, te),  # type: ignore[arg-type]
    }
    actual = None if None in (np_, te) or te == 0 else div(mul(HUNDRED, np_), te)  # type: ignore[arg-type]
    reconstructed: Decimal | None = None
    if all(v is not None for v in comps.values()):
        reconstructed = Decimal(1)
        for v in comps.values():
            reconstructed = mul(reconstructed, v)  # type: ignore[arg-type]
    return {"components": comps, "reconstructed_roe_pct": reconstructed, "actual_roe_pct": actual,
            "reconciles": _reconciles(reconstructed, actual), "notes": notes}


def net_margin_bridge(prev: Evaluator, curr: Evaluator) -> dict[str, Any]:
    """Change in net margin (pp) split into a revenue-growth effect and an expense-growth
    effect, holding the other side at the prior period."""
    rp, rc = prev.value("top_line").value, curr.value("top_line").value
    ep, ec = prev.rec.get("total_expenses"), curr.rec.get("total_expenses")
    npp, npc = prev.rec.get("net_profit"), curr.rec.get("net_profit")
    if None in (rp, rc, ep, ec, npp, npc) or not rp or not rc:
        return {"available": False}
    margin_prev = div(mul(HUNDRED, npp), rp)
    margin_curr = div(mul(HUNDRED, npc), rc)
    margin_rev_only = div(mul(HUNDRED, sub(rc, ep)), rc)     # revenue moved, expenses held at prior
    return {
        "available": True,
        "net_margin_prev_pct": margin_prev,
        "net_margin_curr_pct": margin_curr,
        "net_margin_change_pp": sub(margin_curr, margin_prev),
        "revenue_effect_pp": sub(margin_rev_only, margin_prev),
        "expense_effect_pp": sub(margin_curr, margin_rev_only),
    }


DECOMPOSITIONS = {"roe", "dupont", "dupont5", "dupont_5", "net_margin", "net_profit_margin", "margin"}
