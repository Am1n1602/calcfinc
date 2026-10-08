"""Shared in-memory fixture: one USD company with a calendar fiscal year, two annual periods
and two quarters, using round numbers so every expected ratio can be checked by hand."""
from __future__ import annotations

from datetime import date
from typing import Any

from calcfinc import Basis, Entity, FinancialFact, StatementType
from calcfinc.engine import PeriodRecord

PL = StatementType.PROFIT_AND_LOSS
BS = StatementType.BALANCE_SHEET
CONS = Basis.CONSOLIDATED


def pl(eid: int, metric: str, value: Any, fy: int, q: int | None, start: date, end: date, *,
       annual: bool = False, basis: Basis = CONS) -> FinancialFact:
    return FinancialFact(entity_id=eid, metric=metric, value=value, statement_type=PL, basis=basis,
                         period_start=start, period_end=end, financial_year=fy, quarter=q, is_annual=annual)


def bs(eid: int, metric: str, value: Any, fy: int, end: date, *, basis: Basis = CONS) -> FinancialFact:
    return FinancialFact(entity_id=eid, metric=metric, value=value, statement_type=BS, basis=basis,
                         period_end=end, financial_year=fy, is_point_in_time=True)


def make_record(values: dict[str, Any], *, currency: str = "USD", period_type: str | None = "year",
                start: date | None = date(2026, 1, 1), end: date | None = date(2026, 12, 31)) -> PeriodRecord:
    """A bare PeriodRecord for testing formulas without a store. Amount metrics get `currency`."""
    from calcfinc.num import to_decimal
    from calcfinc.registry import metrics

    vals = {k: to_decimal(v) for k, v in values.items()}
    curs = {k: currency for k in vals if (s := metrics.get(k)) and s.kind in metrics.CURRENCY_KINDS}
    return PeriodRecord(basis="consolidated", period_start=start, period_end=end,
                        financial_year=end.year if end else None, quarter=None, is_annual=period_type == "year",
                        period_type=period_type, values=vals, currencies=curs)


def seed(repos: Any) -> int:
    eid = repos.entities.upsert(
        Entity(name="Testco", identifiers={"ticker": "TEST"}, currency="USD")).id
    facts: list[FinancialFact] = []
    # --- FY2025 annual: revenue 1000, net_profit 100, expenses 850, pbt 150 ---
    for m, v in [("revenue", 1000), ("net_profit", 100), ("total_expenses", 850), ("pbt", 150),
                 ("pbt_before_exceptional", 150), ("finance_costs", 10), ("depreciation", 40),
                 ("other_income", 0), ("tax_expense", 50), ("employee_expense", 500),
                 ("other_expenses", 310)]:
        facts.append(pl(eid, m, v, 2025, None, date(2025, 1, 1), date(2025, 12, 31), annual=True))
    for m, v in [("total_equity", 500), ("total_assets", 2000), ("current_liabilities", 300),
                 ("current_assets", 600), ("borrowings_noncurrent", 200), ("cash_and_equivalents", 150),
                 ("total_liabilities", 1500)]:
        facts.append(bs(eid, m, v, 2025, date(2025, 12, 31)))

    # --- FY2026 annual: revenue 1200 (+20%), net_profit 150, expenses 990 ---
    for m, v in [("revenue", 1200), ("net_profit", 150), ("total_expenses", 990), ("pbt", 210),
                 ("pbt_before_exceptional", 210), ("finance_costs", 12), ("depreciation", 48),
                 ("other_income", 0), ("tax_expense", 60), ("employee_expense", 600),
                 ("other_expenses", 342)]:
        facts.append(pl(eid, m, v, 2026, None, date(2026, 1, 1), date(2026, 12, 31), annual=True))
    for m, v in [("total_equity", 600), ("total_assets", 2400), ("current_liabilities", 360),
                 ("current_assets", 720), ("borrowings_noncurrent", 240), ("cash_and_equivalents", 180),
                 ("total_liabilities", 1800)]:
        facts.append(bs(eid, m, v, 2026, date(2026, 12, 31)))

    # --- two quarters of FY2026 for QoQ: Q1 revenue 280, Q2 revenue 300 ---
    facts.append(pl(eid, "revenue", 280, 2026, 1, date(2026, 1, 1), date(2026, 3, 31)))
    facts.append(pl(eid, "net_profit", 34, 2026, 1, date(2026, 1, 1), date(2026, 3, 31)))
    facts.append(pl(eid, "revenue", 300, 2026, 2, date(2026, 4, 1), date(2026, 6, 30)))
    facts.append(pl(eid, "net_profit", 36, 2026, 2, date(2026, 4, 1), date(2026, 6, 30)))

    repos.facts.add_many(facts)
    repos.commit()
    return int(eid)
