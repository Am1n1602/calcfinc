"""Example 4: monthly management accounts for a small business, with a ratio the user defines.

DSCR (debt service coverage) has no single universal definition, so it is registered here
instead of being built in. The formula string is the definition and what the result shows.
"""
from decimal import Decimal
from pathlib import Path

from calcfinc import FinancialEngine, RatioSpec, StatementType, register_metric, register_ratio

PL, BS = StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET
# The monthly CSV has lines calcfinc has no built-in input for; register them before loading.
register_metric("cost_of_goods_sold", "currency", PL, label="Cost of goods sold")
register_metric("operating_expenses", "currency", PL, label="Operating expenses")
register_metric("amortization", "currency", PL, label="Amortization")
register_metric("principal_repayment", "currency", PL, label="Loan principal repaid")
register_metric("interest_paid", "currency", PL, label="Interest paid")
register_metric("accounts_receivable", "currency", BS, point_in_time=True, label="Accounts receivable")

# EBITDA here is pre-tax profit with interest, depreciation and amortization added back.
register_ratio(RatioSpec("dscr", "x", "(pbt_before_exceptional + finance_costs + depreciation + amortization)"
                                      " / (principal_repayment + interest_paid)",
                         label="Debt service coverage ratio"))

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "monthly_sme.csv", entity="Corner Bakery",
                               currency="GBP")

for month in eng.periods("Corner Bakery"):
    r = eng.get_ratio("Corner Bakery", "dscr", period=month)
    print(f"{month} dscr: {r.value:.4f}")
print("leverage:", eng.get_ratio("Corner Bakery", "debt_to_equity", period="latest_month").value.quantize(
    Decimal("0.0001")))
print("revenue growth:", f"{eng.get_growth('Corner Bakery', 'revenue', kind='mom').value:.2f}",
      "% month on month")
