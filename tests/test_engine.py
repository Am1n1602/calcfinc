"""FinancialEngine facade end to end on the in-memory fixture (acceptance test 1: a USD
company on a calendar fiscal year; every expected figure is worked out by hand)."""
from __future__ import annotations

import unittest
from decimal import Decimal as D

from calcfinc import Entity, FinancialEngine, SqliteRepositories
from calcfinc.engine import EngineError
from tests._fixture import seed

Q12 = D("1e-12")


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = seed(self.repos)
        self.eng = FinancialEngine(self.repos)

    # --- get_metric ---
    def test_get_metric_raw_latest(self):
        r = self.eng.get_metric("TEST", "revenue")
        self.assertTrue(r.ok)
        self.assertEqual(r.value, 1200)
        self.assertEqual(r.unit, "USD")
        self.assertEqual(r.currency, "USD")
        self.assertEqual(r.period, "FY2026")
        self.assertEqual(r.inputs[0].metric, "revenue")

    def test_get_metric_derived(self):
        self.assertEqual(self.eng.get_metric("TEST", "ebitda").value, 270)
        self.assertEqual(self.eng.get_metric("TEST", "total_debt").value, 240)
        self.assertEqual(self.eng.get_metric("TEST", "net_debt").value, 60)

    def test_derived_result_inherits_the_currency_and_lists_its_facts(self):
        r = self.eng.get_metric("TEST", "net_debt")
        self.assertEqual((r.unit, r.currency), ("USD", "USD"))
        self.assertEqual({i.metric for i in r.inputs}, {"borrowings_noncurrent", "cash_and_equivalents"})
        self.assertTrue(all(i.period == "FY2026" for i in r.inputs))

    def test_get_metric_specific_period(self):
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period="FY2025").value, 1000)
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period="FY2026Q1").value, 280)
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period=2025).value, 1000)
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period=(2026, 2)).value, 300)
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period="latest_quarter").value, 300)

    def test_get_metric_missing_is_none_with_limitation(self):
        r = self.eng.get_metric("TEST", "shares_outstanding")
        self.assertIsNone(r.value)
        self.assertTrue(r.limitations)

    # --- get_ratio ---
    def test_get_ratio(self):
        self.assertEqual(self.eng.get_ratio("TEST", "roe").value, 25)
        self.assertEqual(self.eng.get_ratio("TEST", "ebitda_margin").value, D("22.5"))
        self.assertEqual(self.eng.get_ratio("TEST", "leverage").value, D("0.4"))   # alias -> debt_to_equity
        r = self.eng.get_ratio("TEST", "roe")
        self.assertEqual(r.unit, "pct")
        self.assertIsNone(r.currency)                                              # a ratio has no currency
        self.assertIn("net_profit", [i.metric for i in r.inputs])
        self.assertEqual(r.formula, "100 * net_profit / total_equity")
        self.assertEqual(r.definition_version, 2)        # 2: refuses non-positive equity

    def test_unknown_ratio(self):
        r = self.eng.get_ratio("TEST", "sharpe_ratio")
        self.assertIsNone(r.value)
        self.assertIn("unknown ratio", r.limitations[0])

    def test_unavailable_ratio_says_which_input_is_missing(self):
        r = self.eng.get_ratio("TEST", "free_cash_flow")
        self.assertIsNone(r.value)
        self.assertIn("operating_cash_flow not reported", r.limitations[0])

    # --- growth / cagr ---
    def test_growth_yoy(self):
        r = self.eng.get_growth("TEST", "revenue", kind="yoy")
        self.assertEqual(r.value, 20)
        self.assertEqual(r.components["abs_change"], 200)

    def test_growth_qoq(self):
        r = self.eng.get_growth("TEST", "revenue", kind="qoq")       # (300 - 280) / 280 = 7.142857...%
        self.assertEqual(r.value.quantize(Q12), D("7.142857142857"))

    def test_growth_yoy_on_a_ratio_not_just_a_raw_metric(self):
        # roe: 100/500 = 20% (FY2025) -> 150/600 = 25% (FY2026), a 25% relative increase
        r = self.eng.get_growth("TEST", "roe", kind="yoy")
        self.assertEqual(r.value, 25)
        self.assertEqual(r.components["from_value"], 20)
        self.assertEqual(r.components["to_value"], 25)

    def test_cagr(self):
        r = self.eng.get_cagr("TEST", "revenue")
        self.assertEqual(r.value, 20)
        self.assertEqual(r.components["years"], 1)
        self.assertEqual(self.eng.get_cagr("TEST", "revenue", years=2).value.quantize(Q12),
                         D("9.544511501033"))                            # 1.2 ** 0.5 - 1

    def test_cagr_on_a_ratio(self):
        self.assertEqual(self.eng.get_cagr("TEST", "roe").value, 25)

    # --- compare ---
    def test_compare_periods(self):
        r = self.eng.compare_periods("TEST", ["revenue", "net_profit"], a="FY2025", b="FY2026")
        self.assertEqual(r.components["revenue"]["pct_change"], 20)
        self.assertEqual(r.components["net_profit"]["abs_change"], 50)

    def test_compare_periods_ok_reflects_the_real_comparison_not_just_value(self):
        # compare_periods never sets `value` (a multi-metric result has no single scalar), so
        # `ok` has to look at `components`, or every successful comparison reports as failed.
        r = self.eng.compare_periods("TEST", ["revenue"], a="FY2025", b="FY2026")
        self.assertIsNone(r.value)
        self.assertTrue(r.ok)

    def test_compare_periods_ok_false_when_a_period_cannot_resolve(self):
        r = self.eng.compare_periods("TEST", ["revenue"], a="FY2025", b="FY1999")
        self.assertFalse(r.ok)
        self.assertTrue(r.limitations)

    def test_compare_companies(self):
        out = self.eng.compare_companies("roe", ["TEST", "NOPE"])    # one real entity, one unknown
        self.assertEqual(out["results"][0]["entity"], "Testco")
        self.assertEqual(out["results"][0]["rank"], 1)
        self.assertTrue(any(m["entity"] == "NOPE" for m in out["missing"]))

    # --- decompose ---
    def test_decompose_roe(self):
        r = self.eng.decompose_metric("TEST", "roe")
        self.assertEqual(r.value, 25)
        c = r.components
        self.assertEqual(c["components"]["net_profit_margin"], D("12.5"))
        self.assertEqual(c["components"]["asset_turnover"], D("0.5"))
        self.assertEqual(c["components"]["equity_multiplier"], 4)
        self.assertTrue(c["reconciles"])

    def test_decompose_dupont_five_step(self):
        # tax burden 150/210, interest burden 210/222, EBIT margin 222/1200, turnover 0.5, multiplier 4
        r = self.eng.decompose_metric("TEST", "dupont5")
        c = r.components
        self.assertEqual(c["components"]["ebit_margin"], D("18.5"))
        self.assertEqual(c["components"]["tax_burden"].quantize(Q12), D("0.714285714286"))
        self.assertEqual(c["components"]["interest_burden"].quantize(Q12), D("0.945945945946"))
        self.assertTrue(c["reconciles"])
        self.assertEqual(r.value, 25)

    def test_decompose_net_margin_bridge(self):
        r = self.eng.decompose_metric("TEST", "net_margin")
        c = r.components
        self.assertTrue(c["available"])
        self.assertEqual(c["net_margin_prev_pct"], 10)                 # 100 / 1000
        self.assertEqual(c["net_margin_curr_pct"], D("12.5"))          # 150 / 1200
        self.assertEqual(c["revenue_effect_pp"] + c["expense_effect_pp"], c["net_margin_change_pp"])

    # --- calculate / check ---
    def test_calculate(self):
        r = self.eng.calculate("(a - b) / b * 100", a=1200, b=1000)
        self.assertEqual(r.value, 20)
        self.assertFalse(self.eng.calculate("a +").ok)
        self.assertFalse(self.eng.calculate("a + 1", a=0.1).ok)         # floats are refused, not coerced

    def test_check_reports_identity_failures_without_correcting_them(self):
        self.assertEqual([c.failed for c in self.eng.check("TEST")], [[], [], [], []])
        from datetime import date

        from tests._fixture import bs
        self.repos.facts.add_many([bs(self.eid, "total_assets", 2500, 2026, date(2026, 12, 31))])   # 2500 != 1800 + 600
        self.eng.refresh()
        bad = self.eng.check("TEST", period="FY2026")[0]
        self.assertEqual(bad.failed, ["assets_eq_liabilities_plus_equity"])
        self.assertTrue(bad.needs_review)

    # --- guards ---
    def test_segment_data_empty_for_single_segment_entity(self):
        r = self.eng.get_segment_data("TEST")
        self.assertFalse(r.ok)
        self.assertEqual(r.rows, ())
        self.assertTrue(r.limitations)

    def test_unknown_entity_raises(self):
        with self.assertRaises(EngineError):
            self.eng.get_metric("DOESNOTEXIST", "revenue")

    def test_ambiguous_key_raises_instead_of_picking_one(self):
        self.repos.entities.upsert(Entity(name="Other", identifiers={"isin": "TEST"}))
        with self.assertRaises(EngineError):
            self.eng.get_metric("TEST", "revenue")

    def test_entity_object_and_alias_resolve(self):
        ent = self.repos.entities.get(self.eid)
        self.assertEqual(self.eng.get_metric(ent, "revenue").value, 1200)
        self.repos.entities.add_alias(self.eid, "Testco Inc")
        self.assertEqual(self.eng.get_metric("testco inc", "revenue").value, 1200)

    def test_introspection(self):
        self.assertEqual(self.eng.periods("TEST"), ["FY2025", "FY2026 Q1", "FY2026 Q2", "FY2026"])
        self.assertIn("total_equity", self.eng.available_metrics("TEST"))


class TestBanks(unittest.TestCase):
    """One year of a small bank. Interest cover would be (100 + 250) / 250 = 1.4 if it applied."""
    GENERIC = {"revenue": 650, "pbt_before_exceptional": 100, "pbt": 100, "finance_costs": 250,
               "net_profit": 80, "total_equity": 400, "total_assets": 8000, "borrowings_noncurrent": 200}
    BANK = {"bank.deposits": 6000, "bank.gross_advances": 4500, "bank.provisions": 45,
            "bank.interest_earned": 650, "bank.interest_expended": 250}

    def engine(self, name, facts, **options):
        rows = [{"entity": name, "metric": m, "period": "FY2026", "value": v, "currency": "USD"}
                for m, v in facts.items()]
        eng = FinancialEngine.from_records(rows, **options)
        self.addCleanup(eng.repos.close)
        return eng

    def test_a_bank_is_recognised_by_reporting_deposits_and_loans(self):
        eng = self.engine("Bnk", {**self.GENERIC, **self.BANK})
        for ratio in ("interest_coverage", "ebit_margin", "debt_to_equity", "roce"):
            r = eng.get_ratio("Bnk", ratio)
            self.assertIsNone(r.value, ratio)
            self.assertIn("does not apply to a bank", r.limitations[0], ratio)

    def test_the_same_figures_for_a_company_without_bank_lines_are_computed(self):
        eng = self.engine("Corp", self.GENERIC)
        self.assertEqual(eng.get_ratio("Corp", "interest_coverage").value, D("1.4"))     # 350 / 250
        self.assertEqual(eng.get_ratio("Corp", "debt_to_equity").value, D("0.5"))        # 200 / 400

    def test_deposits_and_loans_alone_do_not_make_a_bank_but_interest_lines_and_loans_do(self):
        no_interest = self.engine("Insurer", {**self.GENERIC, "bank.deposits": 6000, "bank.gross_advances": 4500})
        self.assertEqual(no_interest.get_ratio("Insurer", "interest_coverage").value, D("1.4"))
        no_deposits = self.engine("Indian", {**self.GENERIC, "bank.advances": 4500, "bank.interest_earned": 650,
                                             "bank.interest_expended": 250})
        self.assertIsNone(no_deposits.get_ratio("Indian", "interest_coverage").value)

    def test_a_declared_sector_overrides_the_inference_both_ways(self):
        corp = self.engine("Fin", {**self.GENERIC, **self.BANK}, sector="corporate")
        self.assertEqual(corp.get_ratio("Fin", "interest_coverage").value, D("1.4"))
        declared = self.engine("Solo", self.GENERIC, sector="Bank")                      # no bank.* lines at all
        self.assertIsNone(declared.get_ratio("Solo", "interest_coverage").value)
        self.assertEqual(declared.repos.entities.resolve("Solo").sector, "bank")         # normalised and stored
        declared.repos.entities.upsert(Entity(name="Solo"))                              # an update without a sector
        self.assertEqual(declared.repos.entities.resolve("Solo").sector, "bank")         # does not clear it

    def test_ratios_that_do_apply_to_a_bank_are_untouched(self):
        eng = self.engine("Bnk", {**self.GENERIC, **self.BANK})
        self.assertEqual(eng.get_ratio("Bnk", "roe").value, 20)                          # 80 / 400
        self.assertEqual(eng.get_ratio("Bnk", "bank.net_interest_income").value, 400)
        self.assertEqual(eng.get_ratio("Bnk", "bank.loan_to_deposit").value, 75)         # 4500 / 6000
        credit = eng.get_ratio("Bnk", "bank.credit_cost")                                # 45 / 4500
        self.assertEqual(credit.value, 1)
        self.assertIn("gross advances used", credit.limitations[0])
        nim = eng.get_ratio("Bnk", "bank.net_interest_margin")                           # 400 / 8000
        self.assertEqual(nim.value, 5)
        self.assertIn("total assets used", nim.limitations[0])

    def test_the_indian_counterparts_are_held_back_too(self):
        from calcfinc.adapters import ind_as_xbrl

        ind_as_xbrl.register()
        eng = self.engine("Bnk", {**self.GENERIC, **self.BANK})
        for ratio in ("india.roa", "india.dscr", "india.quick_ratio", "india.roce"):
            r = eng.get_ratio("Bnk", ratio)
            self.assertIsNone(r.value, ratio)
            self.assertIn("does not apply to a bank", r.limitations[0], ratio)


class TestInsurers(unittest.TestCase):
    FACTS = {"revenue": 650, "pbt_before_exceptional": 100, "pbt": 100, "finance_costs": 250, "net_profit": 80,
             "total_equity": 400, "total_assets": 8000, "borrowings_noncurrent": 200,
             "current_assets": 500, "current_liabilities": 400, "insurance.net_earned_premium": 600}

    def engine(self, facts, **options):
        rows = [{"entity": "Ins", "metric": m, "period": "FY2026", "value": v, "currency": "USD"}
                for m, v in facts.items()]
        eng = FinancialEngine.from_records(rows, **options)
        self.addCleanup(eng.repos.close)
        return eng

    def test_net_premium_marks_an_insurer_and_holds_back_the_ratios_that_do_not_fit(self):
        eng = self.engine(self.FACTS)
        r = eng.get_ratio("Ins", "current_ratio")
        self.assertIsNone(r.value)
        self.assertIn("does not apply to an insurer", r.limitations[0])
        self.assertIsNone(eng.get_ratio("Ins", "free_cash_flow").value)

    def test_an_insurer_keeps_its_debt_and_interest_cover_ratios(self):
        eng = self.engine(self.FACTS)
        self.assertEqual(eng.get_ratio("Ins", "debt_to_equity").value, D("0.5"))          # 200 / 400
        self.assertEqual(eng.get_ratio("Ins", "interest_coverage").value, D("1.4"))       # 350 / 250

    def test_without_premium_the_same_figures_give_a_current_ratio(self):
        plain = {k: v for k, v in self.FACTS.items() if k != "insurance.net_earned_premium"}
        self.assertEqual(self.engine(plain).get_ratio("Ins", "current_ratio").value, D("1.25"))   # 500 / 400


class TestEquityMethodIdentity(unittest.TestCase):
    def test_equity_method_income_after_pre_tax_profit_is_part_of_the_identity(self):
        from calcfinc.engine.check import check_values
        # pre-tax 100, tax 25, equity-method income 10 after tax: continuing profit is 85
        base = {"pbt": D(100), "tax_expense": D(25), "profit_continuing_ops": D(85)}
        self.assertEqual(check_values({**base, "equity_method_income": D(10)}),
                         {"pbt_minus_tax_eq_profit_continuing_ops": True})              # 100 - 25 + 10 = 85
        self.assertEqual(check_values(base), {"pbt_minus_tax_eq_profit_continuing_ops": False})   # 100 - 25 = 75
        # equity-method income already inside pre-tax profit: 100 - 25 = 75 reconciles on its own
        inside = {"pbt": D(100), "tax_expense": D(25), "profit_continuing_ops": D(75), "equity_method_income": D(10)}
        self.assertEqual(check_values(inside), {"pbt_minus_tax_eq_profit_continuing_ops": True})


class TestCheckPeriods(unittest.TestCase):
    def engine(self, year, quarters=(100, 110, 120, 130)):
        rows = [{"entity": "Q", "metric": "revenue", "period": f"FY2026Q{n}", "value": v, "currency": "USD"}
                for n, v in enumerate(quarters, 1)]
        rows += [{"entity": "Q", "metric": "revenue", "period": "FY2026", "value": year, "currency": "USD"},
                 {"entity": "Q", "metric": "eps_basic", "period": "FY2026", "value": "3", "currency": "USD"}]
        eng = FinancialEngine.from_records(rows)
        self.addCleanup(eng.repos.close)
        return eng

    def test_quarters_that_sum_to_the_year_pass(self):
        (res,) = self.engine(460).check_periods("Q")
        self.assertEqual((res.period, res.checks), ("FY2026", {"quarters_sum_eq_year:revenue": True}))

    def test_a_year_from_another_vintage_fails(self):
        (res,) = self.engine(470).check_periods("Q")
        self.assertEqual(res.failed, ["quarters_sum_eq_year:revenue"])
        self.assertTrue(res.needs_review)

    def test_a_year_without_four_quarters_is_not_checked(self):
        (res,) = self.engine(460, quarters=(100, 110, 120)).check_periods("Q")
        self.assertFalse(res.ran)


if __name__ == "__main__":
    unittest.main()
