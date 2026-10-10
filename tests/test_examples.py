"""The shipped examples must keep running and keep printing the numbers worked out by hand."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

EXPECTED = {
    # UsCo FY2026: 23.1 / 180 equity, 23.1 / 150 revenue, 63 / 150, 112.5 / 75, 150 / 450; revenue 125 -> 150
    "01_usd_company.py": ["roe: 12.83 pct", "net_profit_margin: 15.40 pct", "gross_margin: 42.00 pct",
                          "current_ratio: 1.50 x", "asset_turnover: 0.33 x", "revenue_yoy: 20.00 pct",
                          "net_profit_yoy: 38.95 pct",                      # 16.625 -> 23.1
                          "revenue_cagr: 20.00 pct",
                          "interest_coverage: n/a x [None]", "pbt_before_exceptional not reported"],
    # Bharat FY2026: 10,102.5 / 57,500 and 7,071.75 / 46,000; free cash flow 8,470 - 3,450 and 5,652 - 2,300 (millions)
    "02_inr_consolidated_vs_standalone.py": [
        "consolidated: revenue 112,250,000,000 INR [FY2026], roe 17.57 pct, gross margin 25.00 pct",
        "free cash flow 5,020,000,000 INR",
        "standalone: revenue 78,687,500,000 INR [FY2026], roe 15.37 pct, gross margin 25.00 pct",
        "free cash flow 3,352,000,000 INR", "periods: ['FY2025', 'FY2026']"],
    # Bankco FY2026: NII 465.3 over average earning assets (9,070.3 + 7,892) / 2; 97.2 / 6,852.225;
    # costs 204.678 over income 492.4; 6,852.225 / 9,050.4; 3,620.16 / 9,050.4; (339.75 - 135.9) / 339.75.
    # Safeco: 771.75, 275.8125 and 98.2275 over premium 1,102.5; profit 58.590625 over total income 2,775.625
    "03_bank_and_insurer.py": ["Bankco bank.net_interest_margin: 5.49 pct", "Bankco bank.credit_cost: 1.42 pct",
                               "Bankco bank.cost_to_income: 41.57 pct", "Bankco bank.loan_to_deposit: 75.71 pct",
                               "Bankco bank.casa_ratio: 40.00 pct", "Bankco bank.provision_coverage: 60.00 pct",
                               "Safeco insurance.loss_ratio: 70.00 pct", "Safeco insurance.expense_ratio: 25.02 pct",
                               "Safeco insurance.combined_ratio: 95.02 pct",
                               "Safeco insurance.commission_ratio: 8.91 pct", "Safeco net_profit_margin: 2.11 pct"],
    # (pre-tax profit + 5,250 interest + 10,500 + 2,100 amortization) / (42,000 + 5,250): 131,250, 176,970, 224,655
    "04_monthly_sme_dscr.py": ["2026-01 dscr: 2.7778", "2026-03 dscr: 3.7454", "2026-06 dscr: 4.7546",
                               "leverage: 0.1604",                        # (210,000 + 52,500) / 1,636,408
                               "revenue growth: 10.00 % month on month"],  # 831,075 -> 914,183
    # UsCo 23.1 / 180, InCo 1,330.56 / 11,040
    "05_cross_currency.py": ["revenue ranked: False", "(INR, USD)", "#1 UsCo: roe 12.83%", "#2 InCo: roe 12.05%"],
    "06_sec_companyfacts.py": ["6 quarters derived", "Q4 revenue: 120 USD (single quarter derived: 12M year-to-date "
                               "less 9M (the SEC reports no stand-alone fourth quarter))",
                               "revenue TTM (four quarters to 2025-12-31): 450",
                               "80 (2026-02-20) -> 78 (2027-02-19)", "ROE FY2025: 19.5 pct",
                               "10-K 0000123456-26-000004"],
    "07_ind_as_xbrl.py": ["periods: ['FY2026 Q1']", "roe: 10", "shares outstanding: 100", "india.roce: 12.5 pct",
                          "the ratio is not annualised"],
}


class TestExamples(unittest.TestCase):
    def test_every_example_is_covered_here(self):
        self.assertEqual(sorted(p.name for p in EXAMPLES.glob("0*.py")), sorted(EXPECTED))

    def test_each_example_runs_standalone_and_prints_the_expected_numbers(self):
        for name, lines in EXPECTED.items():
            with self.subTest(example=name):
                done = subprocess.run([sys.executable, "-I", str(EXAMPLES / name)], capture_output=True,
                                      text=True, timeout=60)
                self.assertEqual(done.returncode, 0, done.stderr)
                for line in lines:
                    self.assertIn(line, done.stdout)


if __name__ == "__main__":
    unittest.main()
