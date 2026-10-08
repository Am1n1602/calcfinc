"""Example 1: a USD company on a calendar fiscal year, loaded from a wide CSV.

Every result carries its value, unit, formula and the exact facts it was computed from.
"""
from pathlib import Path

from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "usd_company.csv", entity="Acme Inc", currency="USD")


def show(r):
    value = "n/a" if r.value is None else f"{r.value.normalize():f}"
    print(f"{r.name}: {value} {r.unit} [{r.period}]  {r.formula or ''}  {' '.join(r.limitations)}".rstrip())


for ratio in ("roe", "net_profit_margin", "ebitda_margin", "debt_to_equity", "interest_coverage"):
    show(eng.get_ratio("Acme Inc", ratio))
show(eng.get_growth("Acme Inc", "revenue"))
show(eng.get_cagr("Acme Inc", "revenue"))

roe = eng.get_ratio("Acme Inc", "roe")
print("inputs:", [(i.metric, str(i.value), i.period) for i in roe.inputs])
