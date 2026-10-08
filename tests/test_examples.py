"""The shipped examples must keep running and keep printing the numbers worked out by hand."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

EXPECTED = {
    "01_usd_company.py": ["roe: 25 pct", "net_profit_margin: 12.5 pct", "ebitda_margin: 22.5 pct",
                          "interest_coverage: 18.5 x", "revenue_yoy: 20 pct", "revenue_cagr: 20 pct"],
    "02_inr_consolidated_vs_standalone.py": ["consolidated: revenue 1000 INR [FY2026], roe 20 pct",
                                             "standalone: revenue 700 INR [FY2026], roe 22.5 pct"],
    "03_bank_and_insurer.py": ["Bankco bank.net_interest_margin: 5 pct", "Bankco bank.cost_to_income: 45 pct",
                               "Safeco insurance.combined_ratio: 95 pct", "Safeco net_profit_margin: 2 pct"],
    "04_monthly_sme_dscr.py": ["2026-03 dscr: 2.3333", "2026-02 dscr: 1.8889", "leverage: 0.3636",
                               "revenue growth: 20 % month on month"],
    "05_cross_currency.py": ["revenue ranked: False", "#1 InCo: roe 30%", "#2 UsCo: roe 20%"],
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
