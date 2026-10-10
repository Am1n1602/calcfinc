"""Example 2: an INR company with an April-March year. Consolidated and standalone figures
are separate bases and are never substituted for each other."""
from pathlib import Path

from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "inr_company.csv", currency="INR",
                               fiscal_year_end_month=3)

for basis in ("consolidated", "standalone"):
    rev = eng.get_metric("Bharat Ltd", "revenue", basis=basis)
    roe = eng.get_ratio("Bharat Ltd", "roe", basis=basis)
    margin = eng.get_ratio("Bharat Ltd", "gross_margin", basis=basis)
    fcf = eng.get_ratio("Bharat Ltd", "free_cash_flow", basis=basis)
    print(f"{basis}: revenue {rev.value:,} {rev.unit} [{rev.period}], roe {roe.value:.2f} {roe.unit}, "
          f"gross margin {margin.value:.2f} {margin.unit}")
    print(f"  free cash flow {fcf.value:,} {fcf.unit} ({fcf.formula}); {' '.join(fcf.limitations)}")

# FY2026 here is April 2025 - March 2026, taken from the entity's fiscal year end.
print("periods:", eng.periods("Bharat Ltd"))
