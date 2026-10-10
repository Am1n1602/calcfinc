"""Example 3: a bank and an insurer, using namespaced metrics (bank.*, insurance.*).
An insurer without a `revenue` line falls back to total income, and says so."""
from pathlib import Path

from calcfinc import FinancialEngine, RatioSpec, StatementType, register_metric, register_ratio

# Commissions are in the CSV but not a built-in input, so register them, and a ratio over them.
register_metric("insurance.commissions_paid", "currency", StatementType.PROFIT_AND_LOSS,
                label="Commissions paid to intermediaries")
register_ratio(RatioSpec("insurance.commission_ratio", "pct",
                         "100 * insurance.commissions_paid / insurance.net_earned_premium",
                         label="Commissions as a share of net earned premium"))

eng = FinancialEngine.from_csv(Path(__file__).parent / "data" / "bank_and_insurer.csv", currency="EUR")

for ratio in ("bank.net_interest_margin", "bank.credit_cost", "bank.cost_to_income", "bank.loan_to_deposit",
              "bank.casa_ratio", "bank.provision_coverage"):
    r = eng.get_ratio("Bankco", ratio)
    print(f"Bankco {r.name}: {r.value:.2f} {r.unit} [{r.period}]")

for ratio in ("insurance.loss_ratio", "insurance.expense_ratio", "insurance.combined_ratio",
              "insurance.commission_ratio", "net_profit_margin"):
    r = eng.get_ratio("Safeco", ratio)
    print(f"Safeco {r.name}: {r.value:.2f} {r.unit} [{r.period}]  {' '.join(r.limitations)}".rstrip())
