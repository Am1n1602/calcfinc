"""Example 3: a bank and an insurer, using namespaced metrics (bank.*, insurance.*).
An insurer without a `revenue` line falls back to total income, and says so."""
from pathlib import Path

from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "bank_and_insurer.csv", currency="EUR")

for ratio in ("bank.net_interest_margin", "bank.credit_cost", "bank.cost_to_income", "bank.loan_to_deposit",
              "bank.casa_ratio", "bank.provision_coverage"):
    r = eng.get_ratio("Bankco", ratio)
    print(f"Bankco {r.name}: {r.value.normalize():f} {r.unit}")

for ratio in ("insurance.loss_ratio", "insurance.expense_ratio", "insurance.combined_ratio", "net_profit_margin"):
    r = eng.get_ratio("Safeco", ratio)
    print(f"Safeco {r.name}: {r.value.normalize():f} {r.unit}  {' '.join(r.limitations)}".rstrip())
