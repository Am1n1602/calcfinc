"""Acceptance tests 2-5: the engine works for any currency, fiscal calendar, statement format
and reporting frequency without India-specific names in the core."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import (
    Basis,
    Entity,
    FinancialEngine,
    FinancialFact,
    RatioSpec,
    SqliteRepositories,
    StatementType,
    register_metric,
    register_ratio,
)

PL, BS = StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET
Q10 = D("1e-10")


def fact(eid, metric, value, start, end, *, basis=Basis.CONSOLIDATED, fy=None, annual=False, instant=False,
         stmt=None):
    return FinancialFact(
        entity_id=eid, metric=metric, value=value, statement_type=stmt or (BS if instant else PL), basis=basis,
        period_start=None if instant else start, period_end=end, financial_year=fy or end.year,
        is_annual=annual, is_point_in_time=instant)


class TestIndianStyleYearAndBasis(unittest.TestCase):
    """Acceptance 2: INR, April-March year, consolidated and standalone kept apart."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = self.repos.entities.upsert(
            Entity(name="Bharat Ltd", identifiers={"ticker": "BHARAT"}, currency="INR",
                   fiscal_year_end_month=3)).id
        s, e = date(2025, 4, 1), date(2026, 3, 31)
        self.repos.facts.add_many([
            fact(self.eid, "revenue", 1000, s, e, fy=2026, annual=True),
            fact(self.eid, "net_profit", 100, s, e, fy=2026, annual=True),
            fact(self.eid, "total_equity", 500, s, e, fy=2026, instant=True),
            fact(self.eid, "revenue", 700, s, e, fy=2026, annual=True, basis=Basis.STANDALONE),
            fact(self.eid, "net_profit", 90, s, e, fy=2026, annual=True, basis=Basis.STANDALONE),
            # the standalone balance sheet has equity; the consolidated one is missing it below
            fact(self.eid, "total_equity", 400, s, e, fy=2026, instant=True, basis=Basis.STANDALONE),
            fact(self.eid, "other_income", 5, s, e, fy=2026, annual=True, basis=Basis.STANDALONE),
        ])
        self.eng = FinancialEngine(self.repos)

    def test_bases_do_not_leak_into_each_other(self):
        self.assertEqual(self.eng.get_metric("BHARAT", "revenue").value, 1000)
        self.assertEqual(self.eng.get_metric("BHARAT", "revenue", basis="standalone").value, 700)
        self.assertEqual(self.eng.get_ratio("BHARAT", "roe").value, 20)                        # 100 / 500
        self.assertEqual(self.eng.get_ratio("BHARAT", "roe", basis="standalone").value,
                         D("22.5"))                                                            # 90 / 400

    def test_a_metric_reported_on_one_basis_only_is_not_borrowed_by_the_other(self):
        r = self.eng.get_metric("BHARAT", "other_income")          # consolidated has none
        self.assertIsNone(r.value)
        self.assertEqual(self.eng.get_metric("BHARAT", "other_income", basis="standalone").value, 5)

    def test_amounts_carry_the_entity_currency_and_the_fiscal_label(self):
        r = self.eng.get_metric("BHARAT", "revenue")
        self.assertEqual((r.unit, r.period), ("INR", "FY2026"))
        self.assertEqual(self.eng.get_metric("BHARAT", "revenue", period="FY2026").value, 1000)


class TestBankAndInsurerRatios(unittest.TestCase):
    """Acceptance 3: bank and insurer ratios through namespaced metrics, nothing country-specific."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        s, e = date(2026, 1, 1), date(2026, 12, 31)
        bank = self.repos.entities.upsert(
            Entity(name="Bankco", identifiers={"ticker": "BNK"}, currency="EUR")).id
        self.repos.facts.add_many(
            [fact(bank, m, v, s, e, annual=True) for m, v in [
                ("bank.interest_earned", 1000), ("bank.interest_expended", 600), ("bank.provisions", 60),
                ("bank.employee_cost", 100), ("bank.other_operating_expenses", 80),
                ("bank.operating_profit", 220)]]
            + [fact(bank, m, v, s, e, instant=True) for m, v in [
                ("bank.earning_assets", 8000), ("total_assets", 10000), ("bank.advances", 6000),
                ("bank.deposits", 8000), ("bank.casa_deposits", 3200), ("bank.gross_npa", 300),
                ("bank.net_npa", 120)]])
        ins = self.repos.entities.upsert(
            Entity(name="Safeco", identifiers={"ticker": "SAFE"}, currency="EUR")).id
        self.repos.facts.add_many([fact(ins, m, v, s, e, annual=True) for m, v in [
            ("insurance.net_earned_premium", 1000), ("insurance.claims_incurred", 700),
            ("insurance.underwriting_expenses", 250), ("insurance.net_investment_income", 80)]])
        self.eng = FinancialEngine(self.repos)

    def ratio(self, who, name):
        r = self.eng.get_ratio(who, name)
        self.assertIsNotNone(r.value, r.limitations)
        return r

    def test_bank_ratios(self):
        self.assertEqual(self.ratio("BNK", "bank.net_interest_margin").value, 5)     # (1000-600) / 8000
        self.assertEqual(self.ratio("BNK", "bank.credit_cost").value, 1)             # 60 / 6000
        self.assertEqual(self.ratio("BNK", "bank.cost_to_income").value, 45)         # 180 / (220 + 180)
        self.assertEqual(self.ratio("BNK", "bank.loan_to_deposit").value, 75)        # 6000 / 8000
        self.assertEqual(self.ratio("BNK", "bank.casa_ratio").value, 40)             # 3200 / 8000
        self.assertEqual(self.ratio("BNK", "bank.provision_coverage").value, 60)     # (300-120) / 300
        self.assertEqual(self.ratio("BNK", "bank.gross_npa_to_advances").value, 5)   # 300 / 6000
        self.assertEqual(self.ratio("BNK", "bank.net_npa_to_advances").value, 2)     # 120 / 6000

    def test_old_short_names_still_resolve(self):
        self.assertEqual(self.ratio("BNK", "nim").value, 5)
        self.assertEqual(self.ratio("BNK", "credit_cost").value, 1)

    def test_nim_falls_back_to_total_assets_and_says_so(self):
        self.repos.connection.execute("DELETE FROM facts WHERE metric = 'bank.earning_assets'")
        self.eng.refresh()
        r = self.ratio("BNK", "bank.net_interest_margin")
        self.assertEqual(r.value, 4)                                                 # 400 / 10000
        self.assertTrue(any("understates" in x for x in r.limitations))

    def test_insurance_ratios(self):
        self.assertEqual(self.ratio("SAFE", "insurance.loss_ratio").value, 70)
        self.assertEqual(self.ratio("SAFE", "insurance.expense_ratio").value, 25)
        self.assertEqual(self.ratio("SAFE", "insurance.combined_ratio").value, 95)   # below 100: underwriting profit
        self.assertEqual(self.ratio("SAFE", "insurance.investment_income_ratio").value, 8)
        self.assertEqual(self.ratio("SAFE", "insurance.operating_ratio").value, 87)


class TestMonthlySmeWithCustomRatio(unittest.TestCase):
    """Acceptance 4: monthly management accounts, leverage and coverage, and a ratio the user
    registers themselves (DSCR)."""

    @classmethod
    def setUpClass(cls):
        register_metric("principal_repayment", "currency", PL, label="Loan principal repaid")
        register_metric("interest_paid", "currency", PL, label="Interest paid")
        register_ratio(RatioSpec("dscr", "x", "ebitda / (principal_repayment + interest_paid)",
                                 label="Debt service coverage ratio"))

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = self.repos.entities.upsert(Entity(name="Corner Bakery", kind="unit", currency="GBP")).id
        months = [(date(2026, 1, 1), date(2026, 1, 31), 80, 500, 1000),
                  (date(2026, 2, 1), date(2026, 2, 28), 70, 550, 1000),
                  (date(2026, 3, 1), date(2026, 3, 31), 90, 660, 1100)]
        rows = []
        for s, e, pbe, rev, equity in months:
            rows += [fact(self.eid, m, v, s, e) for m, v in [
                ("revenue", rev), ("pbt_before_exceptional", pbe), ("depreciation", 10), ("finance_costs", 5),
                ("other_income", 0), ("principal_repayment", 40), ("interest_paid", 5), ("net_profit", pbe - 20)]]
            rows += [fact(self.eid, m, v, s, e, instant=True) for m, v in [
                ("total_equity", equity), ("borrowings_noncurrent", 400), ("cash_and_equivalents", 100)]]
        self.repos.facts.add_many(rows)
        self.eng = FinancialEngine(self.repos)

    def test_months_are_recognised_and_labelled(self):
        self.assertEqual(self.eng.periods("Corner Bakery"), ["2026-01", "2026-02", "2026-03"])

    def test_custom_registered_ratio(self):
        r = self.eng.get_ratio("Corner Bakery", "dscr", period="2026-03")      # EBITDA 90+10+5 = 105; 105 / 45
        self.assertEqual(r.value.quantize(Q10), D("2.3333333333"))
        self.assertEqual(r.unit, "x")
        self.assertEqual(self.eng.get_ratio("Corner Bakery", "dscr", period="2026-02").value.quantize(Q10),
                         D("1.8888888889"))                                     # (70 + 10 + 5) / 45

    def test_leverage_and_coverage_on_monthly_data(self):
        self.assertEqual(self.eng.get_ratio("Corner Bakery", "debt_to_equity", period="latest_month").value,
                         D("0.3636363636363636363636363636363636"))             # 400 / 1100
        self.assertEqual(self.eng.get_ratio("Corner Bakery", "interest_coverage", period="2026-03").value, 19)  # 95 / 5
        self.assertEqual(self.eng.get_metric("Corner Bakery", "net_debt", period="2026-01").value, 300)

    def test_month_on_month_growth(self):
        r = self.eng.get_growth("Corner Bakery", "revenue", kind="mom")      # 550 -> 660
        self.assertEqual(r.value, 20)
        self.assertEqual(r.period, "2026-02 -> 2026-03")

    def test_balance_ratios_over_a_month_are_flagged_as_not_annualised(self):
        r = self.eng.get_ratio("Corner Bakery", "roe", period="2026-03")     # 70 / 1100
        self.assertEqual(r.value.quantize(Q10), D("6.3636363636"))
        self.assertTrue(any("not annualised" in x for x in r.limitations))
        self.assertFalse(any("annualised" in x for x in self.eng.get_ratio("Corner Bakery", "interest_coverage",
                                                                           period="2026-03").limitations))

    def test_days_ratios_use_the_month_length_and_need_no_annualising_warning(self):
        self.repos.facts.add_many([fact(self.eid, "trade_receivables", 100, None, date(2026, 3, 31), instant=True)])
        self.eng.refresh()
        r = self.eng.get_ratio("Corner Bakery", "dso", period="2026-03")      # 31 days x 100 / 660
        self.assertEqual(r.value.quantize(Q10), D("4.6969696970"))
        self.assertFalse(any("annualised" in x for x in r.limitations))
        self.assertIn("period_days", [i.metric for i in r.inputs])

    def test_average_balance_ratio_uses_the_adjacent_prior_month(self):
        r = self.eng.get_ratio("Corner Bakery", "roe_avg", period="2026-03")  # 70 / ((1100 + 1000) / 2)
        self.assertEqual(r.value.quantize(Q10), D("6.6666666667"))
        self.assertEqual({i.period for i in r.inputs if i.metric == "total_equity"}, {"2026-03", "2026-02"})

    def test_prior_period_must_be_adjacent(self):
        self.repos.connection.execute("DELETE FROM facts WHERE period_end = '2026-02-28'")
        self.eng.refresh()
        r = self.eng.get_ratio("Corner Bakery", "roe_avg", period="2026-03")   # January is not "one month earlier"
        self.assertIsNone(r.value)
        self.assertIn("no earlier comparable period", r.limitations[0])


class TestCrossCurrency(unittest.TestCase):
    """Acceptance 5: amounts in different currencies are never ranked or combined; ratios are."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        s, e = date(2026, 1, 1), date(2026, 12, 31)
        us = self.repos.entities.upsert(Entity(name="UsCo", identifiers={"ticker": "US"}, currency="USD")).id
        ind = self.repos.entities.upsert(Entity(name="InCo", identifiers={"ticker": "IN"}, currency="INR")).id
        for eid, rev, np_, eq in ((us, 1000, 100, 500), (ind, 80000, 12000, 40000)):
            self.repos.facts.add_many(
                [fact(eid, "revenue", rev, s, e, annual=True), fact(eid, "net_profit", np_, s, e, annual=True),
                 fact(eid, "total_equity", eq, s, e, instant=True)])
        self.eng = FinancialEngine(self.repos)

    def test_absolute_amounts_are_listed_but_not_ranked(self):
        out = self.eng.compare_companies("revenue", ["US", "IN"])
        self.assertEqual({r["currency"] for r in out["results"]}, {"USD", "INR"})
        self.assertTrue(all("rank" not in r for r in out["results"]))
        self.assertTrue(any("different currencies" in x for x in out["limitations"]))

    def test_same_currency_amounts_are_ranked(self):
        out = self.eng.compare_companies("revenue", ["US", "US"])
        self.assertEqual([r["rank"] for r in out["results"]], [1, 2])

    def test_ratios_compare_across_currencies(self):
        out = self.eng.compare_companies("roe", ["US", "IN"])          # 20% vs 30%
        self.assertEqual([(r["entity"], r["rank"]) for r in out["results"]], [("InCo", 1), ("UsCo", 2)])
        self.assertEqual(out["limitations"], [])

    def test_one_entity_mixing_currencies_cannot_produce_a_ratio(self):
        eid = self.repos.entities.upsert(Entity(name="MixCo", identifiers={"ticker": "MIX"})).id
        s, e = date(2026, 1, 1), date(2026, 12, 31)
        self.repos.facts.add_many([
            FinancialFact(entity_id=eid, metric="net_profit", value=10, currency="USD", statement_type=PL,
                          basis=Basis.CONSOLIDATED, period_start=s, period_end=e, financial_year=2026, is_annual=True),
            FinancialFact(entity_id=eid, metric="total_equity", value=100, currency="EUR", statement_type=BS,
                          basis=Basis.CONSOLIDATED, period_end=e, financial_year=2026, is_point_in_time=True)])
        r = FinancialEngine(self.repos).get_ratio("MIX", "roe")
        self.assertIsNone(r.value)
        self.assertIn("different currencies", r.limitations[0])


if __name__ == "__main__":
    unittest.main()
