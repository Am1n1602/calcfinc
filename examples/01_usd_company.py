"""Example 1: a USD company on a calendar fiscal year, loaded from a long CSV.

The CSV holds two companies and two years; the entity, period and currency come from its columns. Every
result carries its value, unit, formula and the exact facts it was computed from.
"""
from pathlib import Path

from calcfinc import FinancialEngine, StatementType, register_metric

# The CSV reports two lines calcfinc has no built-in input for, so they are registered before loading.
register_metric("operating_expenses", "currency", StatementType.PROFIT_AND_LOSS, label="Operating expenses")
register_metric("operating_profit", "currency", StatementType.PROFIT_AND_LOSS, label="Operating profit")

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "usd_company.csv")


def show(r):
    value = "n/a" if r.value is None else f"{r.value:.2f}"
    print(f"{r.name}: {value} {r.unit} [{r.period}]  {r.formula or ''}  {' '.join(r.limitations)}".rstrip())


for ratio in ("roe", "net_profit_margin", "gross_margin", "current_ratio", "asset_turnover"):
    show(eng.get_ratio("UsCo", ratio))
show(eng.get_growth("UsCo", "revenue"))
show(eng.get_growth("UsCo", "net_profit"))
show(eng.get_cagr("UsCo", "revenue"))

# EBIT-based ratios need pre-tax profit before exceptional items, which this CSV does not report.
# They come back as n/a with the reason, never as a guess.
show(eng.get_ratio("UsCo", "interest_coverage"))

roe = eng.get_ratio("UsCo", "roe")
print("inputs:", [(i.metric, str(i.value), i.period) for i in roe.inputs])
