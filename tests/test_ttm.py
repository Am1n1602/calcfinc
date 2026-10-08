"""Trailing twelve months: ttm(x) sums the latest adjacent periods that make a year, and refuses
(None plus a reason) when any of them is missing. Expected values are worked out by hand."""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from calcfinc import FinancialEngine, RatioSpec, register_ratio

Q10 = D("1e-10")

# five calendar quarters; flows per quarter
FLOWS = {
    "net_profit": [30, 34, 36, 40, 38],
    "revenue": [280, 300, 320, 330, 340],
    "pbt_before_exceptional": [40, 44, 46, 50, 48],
    "finance_costs": [3, 3, 3, 3, 3],
    "dividends": [-5, -5, -5, -5, -5],          # cash-flow sign: outflows are negative
    "eps_basic": [3.0, 3.4, 3.6, 4.0, 3.8],
}
QUARTERS = ["FY2025Q1", "FY2025Q2", "FY2025Q3", "FY2025Q4", "FY2026Q1"]


def rows(skip=()):
    out = []
    for q, label in enumerate(QUARTERS):
        if label in skip:
            continue
        for metric, values in FLOWS.items():
            out.append({"entity": "Acme", "metric": metric, "period": label, "value": str(values[q]),
                        "currency": "USD"})
    for metric, value in (("total_equity", 650), ("total_assets", 2600), ("current_liabilities", 400),
                          ("shares_outstanding", 10)):
        out.append({"entity": "Acme", "metric": metric, "period": "FY2026Q1", "value": str(value),
                    "currency": "USD"})
    return out


def engine(**kw):
    eng = FinancialEngine.from_records(rows(**kw))
    from datetime import date

    from calcfinc import SharePrice
    eng.repos.prices.add_prices([SharePrice(1, date(2026, 3, 31), 100, "USD")])
    return eng


class TestTrailingTwelveMonths(unittest.TestCase):
    def setUp(self):
        self.eng = engine()
        self.addCleanup(self.eng.repos.close)

    def ratio(self, name, **kw):
        r = self.eng.get_ratio("Acme", name, **kw)
        self.assertIsNotNone(r.value, r.limitations)
        return r

    def test_amounts_sum_the_latest_four_quarters(self):
        # the window is FY2025Q2..FY2026Q1; the oldest quarter is left out
        self.assertEqual(self.ratio("net_profit_ttm").value, 148)             # 34 + 36 + 40 + 38
        self.assertEqual(self.ratio("revenue_ttm").value, 1290)               # 300 + 320 + 330 + 340
        self.assertEqual(self.ratio("ebit_ttm").value, 200)                   # 47 + 49 + 53 + 51
        self.assertEqual(self.ratio("net_profit_ttm").unit, "USD")

    def test_ratios_divide_ttm_flows_by_period_end_balances(self):
        self.assertEqual(self.ratio("roe_ttm").value.quantize(Q10), D("22.7692307692"))      # 148 / 650
        self.assertEqual(self.ratio("roce_ttm").value.quantize(Q10), D("9.0909090909"))      # 200 / (2600 - 400)
        self.assertEqual(self.ratio("net_profit_margin_ttm").value.quantize(Q10),
                         D("11.4728682171"))                                                 # 148 / 1290
        self.assertEqual(self.ratio("interest_coverage_ttm").value.quantize(Q10),
                         D("16.6666666667"))                                                 # 200 / 12

    def test_ttm_ratios_carry_no_not_annualised_warning(self):
        self.assertFalse(any("annualised" in x for x in self.ratio("roe_ttm").limitations))

    def test_every_quarter_used_is_listed_with_its_own_period(self):
        r = self.ratio("roe_ttm")
        periods = {i.period for i in r.inputs if i.metric == "net_profit"}
        self.assertEqual(periods, {"FY2025 Q2", "FY2025 Q3", "FY2025 Q4", "FY2026 Q1"})

    def test_valuation_on_ttm_is_priced_at_the_latest_quarter_end(self):
        pe = self.ratio("pe_ttm")                                              # EPS 3.4 + 3.6 + 4.0 + 3.8 = 14.8
        self.assertEqual(pe.value.quantize(Q10), D("6.7567567568"))            # 100 / 14.8
        self.assertEqual(pe.period, "FY2026 Q1")
        self.assertEqual(pe.kind, "valuation")
        self.assertEqual(self.ratio("dividend_yield_ttm").value, 2)            # |-20| / 10 shares / 100 x 100

    def test_dividend_sign_does_not_matter_for_the_ttm_yield(self):
        flipped = FinancialEngine.from_records(
            [dict(r, value="5") if r["metric"] == "dividends" else r for r in rows()])
        self.addCleanup(flipped.repos.close)
        from datetime import date

        from calcfinc import SharePrice
        flipped.repos.prices.add_prices([SharePrice(1, date(2026, 3, 31), 100, "USD")])
        self.assertEqual(flipped.get_ratio("Acme", "dividend_yield_ttm").value, 2)

    def test_too_few_quarters_gives_none_with_a_reason(self):
        r = self.eng.get_ratio("Acme", "net_profit_ttm", period="FY2025Q3")
        self.assertIsNone(r.value)
        self.assertIn("needs 4 adjacent quarter periods", r.limitations[0])
        self.assertIn("found 3", r.limitations[0])

    def test_a_missing_quarter_breaks_the_window_rather_than_stretching_it(self):
        eng = engine(skip=("FY2025Q4",))
        self.addCleanup(eng.repos.close)
        r = eng.get_ratio("Acme", "net_profit_ttm")
        self.assertIsNone(r.value)                         # Q3 2025 is not adjacent to Q1 2026
        self.assertIn("found 1", r.limitations[0])

    def test_a_year_is_its_own_trailing_twelve_months(self):
        eng = FinancialEngine.from_records([
            {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1200", "currency": "USD"}])
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_ratio("A", "revenue_ttm").value, 1200)

    def test_twelve_months_make_a_year(self):
        months = [{"entity": "B", "metric": "revenue", "period": f"2026-{m:02d}", "value": "100",
                   "currency": "GBP"} for m in range(1, 13)]
        eng = FinancialEngine.from_records(months)
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_ratio("B", "revenue_ttm", period="latest_month").value, 1200)
        self.assertIsNone(eng.get_ratio("B", "revenue_ttm", period="2026-11").value)      # only 11 months so far

        gap = FinancialEngine.from_records([r for r in months if r["period"] != "2026-06"])
        self.addCleanup(gap.repos.close)
        self.assertIsNone(gap.get_ratio("B", "revenue_ttm", period="latest_month").value)

    def test_growth_of_a_ttm_figure_compares_whole_years(self):
        eng = FinancialEngine.from_records(
            [{"entity": "C", "metric": "revenue", "period": f"FY{y}Q{q}", "value": str(100 + 10 * i),
              "currency": "USD"} for i, (y, q) in enumerate((y, q) for y in (2025, 2026) for q in (1, 2, 3, 4))])
        self.addCleanup(eng.repos.close)
        # revenue 100..170 over eight quarters: TTM at 2026Q4 = 140+150+160+170 = 620, at 2025Q4 = 100+110+120+130 = 460
        self.assertEqual(eng.get_ratio("C", "revenue_ttm").value, 620)
        self.assertEqual(eng.get_ratio("C", "revenue_ttm", period="FY2025Q4").value, 460)

    def test_ttm_of_a_balance_sheet_item_is_rejected_at_registration(self):
        with self.assertRaises(ValueError) as ctx:
            register_ratio(RatioSpec("bad_ttm_assets", "currency", "ttm(total_assets)"))
        self.assertIn("balance-sheet", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
