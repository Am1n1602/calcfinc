"""Example 4: monthly management accounts for a small business, with a ratio the user defines.

DSCR (debt service coverage) has no single universal definition, so it is registered here
instead of being built in. The formula string is the definition and what the result shows.
"""
from decimal import Decimal
from pathlib import Path

from calcfinc import FinancialEngine, RatioSpec, StatementType, register_metric, register_ratio

register_metric("principal_repayment", "currency", StatementType.PROFIT_AND_LOSS, label="Loan principal repaid")
register_metric("interest_paid", "currency", StatementType.PROFIT_AND_LOSS, label="Interest paid")
register_ratio(RatioSpec("dscr", "x", "ebitda / (principal_repayment + interest_paid)",
                         label="Debt service coverage ratio"))

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "monthly_sme.csv", entity="Corner Bakery",
                               currency="GBP")

for month in eng.periods("Corner Bakery"):
    r = eng.get_ratio("Corner Bakery", "dscr", period=month)
    print(f"{month} dscr: {r.value:.4f}")
print("leverage:", eng.get_ratio("Corner Bakery", "debt_to_equity", period="latest_month").value.quantize(
    Decimal("0.0001")))
print("revenue growth:", eng.get_growth("Corner Bakery", "revenue", kind="mom").value, "% month on month")
