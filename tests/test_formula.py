"""Formula evaluator, derived quantities, ratios and growth maths (no store involved).
Expected values are worked out by hand from the inputs, not read back from the code."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc.engine import growth
from calcfinc.engine.evaluate import Evaluator
from calcfinc.formula import CalcError, calculate, evaluate
from calcfinc.registry import ratios
from tests._fixture import make_record

Q10 = D("1e-10")


def val(values, name):
    return Evaluator(make_record(values)).value(name)


class TestCalculator(unittest.TestCase):
    def test_literals_are_exact_decimals(self):
        self.assertEqual(calculate("0.1 + 0.2"), D("0.3"))          # 0.30000000000000004 in floats

    def test_arithmetic(self):
        self.assertEqual(calculate("2 + 3 * 4"), 14)
        self.assertEqual(calculate("(a - b) / b * 100", a=120, b=100), 20)
        self.assertEqual(calculate("max(1, 2, 3) + abs(-4)"), 7)
        self.assertEqual(calculate("2 ** 10"), 1024)
        self.assertEqual(calculate("sqrt(2.25)"), D("1.5"))

    def test_rounding_is_half_even_on_exact_decimals(self):
        self.assertEqual(calculate("round(2.5)"), 2)
        self.assertEqual(calculate("round(3.5)"), 4)
        self.assertEqual(calculate("round(1.005, 2)"), D("1.00"))   # exactly half, rounds to even

    def test_rejects_unsafe_or_ambiguous_syntax(self):
        for bad in ("__import__('os')", "a.b", "open('x')", "[i for i in range(3)]", "lambda: 1",
                    "unknown_var + 1", "1 // 2", "7 % 2", "a.__class__", "'text'"):
            with self.assertRaises(ValueError, msg=bad):
                calculate(bad, a=1)

    def test_none_and_float_variables_are_refused(self):
        with self.assertRaises(ValueError):
            calculate("x + 1", x=None)
        with self.assertRaises(CalcError):
            calculate("x + 1", x=0.1)

    def test_division_by_zero_and_runaway_powers_are_errors_not_hangs(self):
        with self.assertRaises(CalcError):
            calculate("1 / x", x=0)
        with self.assertRaises(CalcError):
            calculate("9 ** 9 ** 9")

    def test_dotted_names_are_looked_up_as_plain_strings(self):
        self.assertEqual(evaluate("bank.x + 1", {"bank.x": "2"}), 3)
        with self.assertRaises(CalcError):
            evaluate("bank.x", {})


class TestDerived(unittest.TestCase):
    R = {"pbt_before_exceptional": 210, "finance_costs": 12, "depreciation": 48, "other_income": 0,
         "revenue": 1200, "employee_expense": 600, "other_expenses": 342, "borrowings_noncurrent": 240,
         "cash_and_equivalents": 180, "capex_ppe": 30, "capex_intangibles": 5}

    def test_ebit_and_ebitda(self):
        self.assertEqual(val(self.R, "ebit").value, 222)                 # 210 + 12
        self.assertEqual(val(self.R, "ebitda").value, 270)               # 210 + 48 + 12 - 0
        self.assertIsNone(val({"finance_costs": 1}, "ebit").value)

    def test_operating_ebit(self):
        self.assertEqual(val(self.R, "operating_ebit").value, 210)       # 1200 - 600 - 48 - 342

    def test_debt_defaults_to_zero_only_where_declared_and_says_so(self):
        out = val(self.R, "total_debt")
        self.assertEqual(out.value, 240)
        self.assertTrue(any("treated as 0" in n for n in out.notes))
        self.assertEqual(val(self.R, "net_debt").value, 60)
        self.assertIsNone(val({"borrowings_noncurrent": 100}, "net_debt").value)   # cash missing: no default

    def test_capex_uses_what_is_reported_and_names_the_gap(self):
        self.assertEqual(val(self.R, "capex").value, 35)
        only = val({"capex_ppe": 30}, "capex")
        self.assertEqual(only.value, 30)
        self.assertTrue(any("intangibles not reported" in n for n in only.notes))
        self.assertIsNone(val({}, "capex").value)

    def test_top_line_falls_back_to_total_income_with_a_note(self):
        out = val({"total_income": 2500}, "top_line")
        self.assertEqual(out.value, 2500)
        self.assertTrue(any("total_income used" in n for n in out.notes))
        self.assertEqual(val({"revenue": 7, "total_income": 9}, "top_line").value, 7)


class TestRatios(unittest.TestCase):
    FY26 = {"revenue": 1200, "net_profit": 150, "total_equity": 600, "total_assets": 2400,
            "current_liabilities": 360, "current_assets": 720, "pbt": 210, "pbt_before_exceptional": 210,
            "finance_costs": 12, "depreciation": 48, "other_income": 0, "tax_expense": 60,
            "borrowings_noncurrent": 240, "cash_and_equivalents": 180}

    def _r(self, name):
        return val(self.FY26, name).value

    def test_headline_ratios(self):
        self.assertEqual(self._r("roe"), 25)
        self.assertEqual(self._r("roa"), D("6.25"))
        self.assertEqual(self._r("ebitda_margin"), D("22.5"))
        self.assertEqual(self._r("ebit_margin"), D("18.5"))
        self.assertEqual(self._r("net_profit_margin"), D("12.5"))
        self.assertEqual(self._r("debt_to_equity"), D("0.4"))
        self.assertEqual(self._r("current_ratio"), 2)
        self.assertEqual(self._r("asset_turnover"), D("0.5"))
        self.assertEqual(self._r("equity_multiplier"), 4)

    def test_non_terminating_ratios_are_correct_to_the_digit(self):
        self.assertEqual(self._r("roce").quantize(Q10), D("10.8823529412"))             # 222 / 2040
        self.assertEqual(self._r("effective_tax_rate").quantize(Q10), D("28.5714285714"))  # 60 / 210

    def test_interest_coverage_is_ebit_over_interest(self):
        # EBIT 222 / 12 = 18.5. The pre-port definition divided profit *after* interest (210)
        # by interest, giving 17.5, i.e. true coverage minus one.
        self.assertEqual(self._r("interest_coverage"), D("18.5"))

    def test_roic(self):
        # NOPAT = 222 x (1 - 60/210) = 158.571428...; invested capital = 240 + 600 - 180 = 660
        self.assertEqual(self._r("roic").quantize(Q10), D("24.0259740260"))

    def test_missing_input_is_none_with_a_reason_not_zero(self):
        out = val({"net_profit": 100}, "roe")
        self.assertIsNone(out.value)
        self.assertIn("total_equity not reported", out.reason)

    def test_zero_denominator_is_none_with_a_reason(self):
        out = val({"net_profit": 100, "total_equity": 0}, "roe")
        self.assertIsNone(out.value)
        self.assertIn("division by zero", out.reason)

    def test_non_positive_denominators_where_meaningless(self):
        out = val({"net_debt": 5, "pbt_before_exceptional": -10, "depreciation": 1, "other_income": 0,
                   "borrowings_noncurrent": 10, "cash_and_equivalents": 5}, "net_debt_to_ebitda")
        self.assertIsNone(out.value)
        self.assertIn("not positive", out.reason)

    def test_alias_resolution(self):
        self.assertEqual(ratios.resolve("Return_On_Equity"), "roe")
        self.assertEqual(ratios.resolve("D/E"), "debt_to_equity")
        self.assertEqual(ratios.resolve("nim"), "bank.net_interest_margin")
        self.assertEqual(ratios.resolve("P/E"), "pe")
        self.assertIsNone(ratios.resolve("made_up_ratio"))

    def test_registering_a_ratio_with_an_unknown_input_fails_loudly(self):
        with self.assertRaises(ValueError):
            ratios.register_ratio(ratios.RatioSpec("typo_ratio", "x", "net_profit / totl_equity"))


class TestBankDefinitions(unittest.TestCase):
    """Bank ratios on the RBI forms: average earning assets, gross advances, provisions held."""

    PRIOR = {"bank.earning_assets": 6000, "total_assets": 8000}
    CUR = {"bank.interest_earned": 1000, "bank.interest_expended": 600,        # net interest income 400
           "bank.earning_assets": 8000, "total_assets": 10000}

    def _ev(self, cur, prior=None):
        p = make_record(prior, start=date(2025, 1, 1), end=date(2025, 12, 31)) if prior else None
        return Evaluator(make_record(cur), prior=p)

    def test_nim_uses_average_interest_earning_assets(self):
        out = self._ev(self.CUR, self.PRIOR).value("bank.net_interest_margin")
        self.assertEqual(out.value.quantize(Q10), D("5.7142857143"))           # 400 / ((8000 + 6000) / 2)
        self.assertEqual(out.notes, ())

    def test_nim_without_a_prior_period_uses_period_end_and_says_so(self):
        out = self._ev(self.CUR).value("bank.net_interest_margin")
        self.assertEqual(out.value, 5)                                         # 400 / 8000
        self.assertTrue(any("period-end interest-earning assets" in n for n in out.notes))

    def test_nim_without_earning_assets_falls_back_to_total_assets_and_says_so(self):
        cur = {k: v for k, v in self.CUR.items() if k != "bank.earning_assets"}
        out = self._ev(cur).value("bank.net_interest_margin")
        self.assertEqual(out.value, 4)                                         # 400 / 10000
        self.assertTrue(any("understates" in n for n in out.notes))

    def test_nim_on_average_total_assets(self):
        out = self._ev(self.CUR, self.PRIOR).value("bank.net_interest_margin_avg_assets")
        self.assertEqual(out.value.quantize(Q10), D("4.4444444444"))           # 400 / ((10000 + 8000) / 2)

    def test_gross_npa_ratio_uses_gross_advances_when_reported(self):
        rec = {"bank.gross_npa": 300, "bank.advances": 6000, "bank.gross_advances": 6400}
        out = self._ev(rec).value("bank.gross_npa_to_advances")
        self.assertEqual(out.value, D("4.6875"))                               # 300 / 6400
        self.assertEqual(out.notes, ())

    def test_gross_npa_ratio_falls_back_to_balance_sheet_advances_and_says_so(self):
        out = self._ev({"bank.gross_npa": 300, "bank.advances": 6000}).value("bank.gross_npa_to_advances")
        self.assertEqual(out.value, 5)
        self.assertTrue(any("gross advances not reported" in n for n in out.notes))

    def test_net_npa_ratio_is_on_net_advances(self):
        out = self._ev({"bank.net_npa": 120, "bank.advances": 6000}).value("bank.net_npa_to_advances")
        self.assertEqual(out.value, 2)

    def test_provision_coverage_uses_provisions_held_when_reported(self):
        rec = {"bank.gross_npa": 300, "bank.net_npa": 120, "bank.npa_provisions": 190}
        out = self._ev(rec).value("bank.provision_coverage")
        self.assertEqual(out.value.quantize(Q10), D("63.3333333333"))          # 190 / 300, not (300 - 120) / 300
        self.assertEqual(out.notes, ())

    def test_provision_coverage_proxy_is_labelled_as_an_estimate(self):
        out = self._ev({"bank.gross_npa": 300, "bank.net_npa": 120}).value("bank.provision_coverage")
        self.assertEqual(out.value, 60)
        self.assertTrue(any("may overstate" in n for n in out.notes))


class TestOutflowSignConvention(unittest.TestCase):
    """Cash-flow sources disagree on the sign of dividends and capex (some report outflows as
    negatives). The ratios must give the same answer either way."""

    def test_payout_and_retention_ignore_the_sign_of_dividends(self):
        for dividends in (45, -45):
            with self.subTest(dividends=dividends):
                rec = {"net_profit": 150, "dividends": dividends, "total_equity": 600}
                self.assertEqual(val(rec, "payout_ratio").value, 30)           # 45 / 150
                self.assertEqual(val(rec, "retention_ratio").value, 70)
                self.assertEqual(val(rec, "sustainable_growth").value, D("17.5"))   # ROE 25% x 70%

    def test_dividend_yield_ignores_the_sign_of_dividends(self):
        from calcfinc import SharePrice
        for dividends in (40, -40):
            with self.subTest(dividends=dividends):
                ev = Evaluator(make_record({"dividends": dividends, "shares_outstanding": 10}),
                               price=SharePrice(1, date(2026, 12, 31), 200, "USD"))
                self.assertEqual(ev.value("dividend_yield").value, 2)          # (40 / 10) / 200

    def test_capex_and_free_cash_flow_ignore_the_sign_of_each_component(self):
        for ppe, intangibles in ((30, 5), (-30, -5), (-30, 5), (30, -5)):
            with self.subTest(ppe=ppe, intangibles=intangibles):
                rec = {"operating_cash_flow": 100, "capex_ppe": ppe, "capex_intangibles": intangibles,
                       "revenue": 1000, "depreciation": 35}
                self.assertEqual(val(rec, "capex").value, 35)
                self.assertEqual(val(rec, "free_cash_flow").value, 65)
                self.assertEqual(val(rec, "capex_to_depreciation").value, 1)    # 35 / 35
                self.assertEqual(val(rec, "capex_to_revenue").value, D("3.5"))

    def test_single_component_fallbacks_also_ignore_sign(self):
        self.assertEqual(val({"capex_ppe": -30}, "capex").value, 30)
        self.assertEqual(val({"capex_intangibles": -5}, "capex").value, 5)


class TestWorkingCapitalEfficiency(unittest.TestCase):
    R = {"revenue": 1000, "cost_of_revenue": 600, "gross_profit": 400, "trade_receivables": 100,
         "inventory": 80, "trade_payables": 60, "current_assets": 400, "current_liabilities": 200}

    def _r(self, name, values=None, **kw):
        return Evaluator(make_record(values or self.R, **kw)).value(name)

    def test_turnover_and_liquidity(self):
        self.assertEqual(self._r("inventory_turnover").value, D("7.5"))       # 600 / 80
        self.assertEqual(self._r("receivables_turnover").value, 10)           # 1000 / 100
        self.assertEqual(self._r("payables_turnover").value, 10)              # 600 / 60
        self.assertEqual(self._r("quick_ratio").value, D("1.6"))              # (400 - 80) / 200

    def test_days_use_the_real_length_of_a_365_day_year(self):
        self.assertEqual(self._r("dso").value, D("36.5"))                     # 365 x 100 / 1000
        self.assertEqual(self._r("dpo").value, D("36.5"))                     # 365 x 60 / 600
        self.assertEqual(self._r("dio").value.quantize(Q10), D("48.6666666667"))   # 365 x 80 / 600
        self.assertEqual(self._r("cash_conversion_cycle").value.quantize(Q10), D("48.6666666667"))

    def test_days_scale_with_the_period_not_a_fixed_365(self):
        q1 = self._r("dso", period_type="quarter", start=date(2026, 1, 1), end=date(2026, 3, 31))
        self.assertEqual(q1.value, 9)                                         # 90 days x 100 / 1000
        leap = self._r("dso", start=date(2028, 1, 1), end=date(2028, 12, 31))
        self.assertEqual(leap.value, D("36.6"))                               # 366 days in 2028

    def test_days_need_a_known_period_length(self):
        out = self._r("dso", start=None)
        self.assertIsNone(out.value)
        self.assertIn("no start date", out.reason)

    def test_gross_margin_uses_reported_gross_profit_or_derives_it_and_says_so(self):
        self.assertEqual(self._r("gross_margin").value, 40)
        derived = self._r("gross_margin", {k: v for k, v in self.R.items() if k != "gross_profit"})
        self.assertEqual(derived.value, 40)
        self.assertTrue(any("derived as revenue - cost_of_revenue" in n for n in derived.notes))
        self.assertIsNone(self._r("gross_margin", {"revenue": 1000}).value)


class TestGrowth(unittest.TestCase):
    def test_pct_and_abs(self):
        self.assertEqual(growth.pct_change(D(1000), D(1200)), 20)
        self.assertEqual(growth.abs_change(D(1000), D(1200)), 200)
        self.assertIsNone(growth.pct_change(None, D(5)))

    def test_non_positive_base_gives_no_percent(self):
        self.assertIsNone(growth.pct_change(D(-50), D(20)))
        self.assertIsNone(growth.pct_change(D(0), D(20)))
        self.assertEqual(growth.abs_change(D(-50), D(20)), 70)

    def test_cagr(self):
        self.assertEqual(growth.cagr(D(100), D(200), D(1)), 100)
        self.assertEqual(growth.cagr(D(100), D(400), D(2)), 100)                         # 100 -> 200 -> 400
        self.assertEqual(growth.cagr(D(100), D("133.1"), D(3)).quantize(D("1e-25")), 10)  # 1.1 ** 3 = 1.331
        self.assertIsNone(growth.cagr(D(0), D(400), D(2)))
        self.assertIsNone(growth.cagr(D(100), D(400), D(0)))
        self.assertIsNone(growth.cagr(D(100), D(-1), D(2)))


if __name__ == "__main__":
    unittest.main()
