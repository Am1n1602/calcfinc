"""The Indian counterparts (`india.*`), registered by the Ind-AS adapter where the ICAI / Schedule III,
SEBI or RBI form differs from the generic ratio. Expected values are worked out by hand."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc.adapters import ind_as_xbrl
from calcfinc.engine.evaluate import Evaluator
from calcfinc.registry import ratios
from tests._fixture import make_record

Q10 = D("1e-10")

PRIOR = {"total_equity": 500, "total_assets": 2000, "trade_receivables": 90, "inventory": 70, "trade_payables": 50}
CUR = {
    "net_profit": 150, "total_equity": 600, "india.preference_dividend": 10, "revenue": 1200,
    "cost_of_revenue": 600, "india.net_credit_sales": 1000, "india.net_credit_purchases": 450,
    "trade_receivables": 100, "inventory": 80, "trade_payables": 60, "finance_costs": 12,
    "pbt_before_exceptional": 210, "depreciation": 48, "total_assets": 2400, "current_assets": 720,
    "current_liabilities": 360, "borrowings_noncurrent": 240, "india.intangible_assets": 40,
    "india.deferred_tax_liabilities": 20, "india.scheduled_principal_repayment": 30,
    "india.lease_payments": 8, "india.other_noncash_adjustments": 5, "india.prepaid_expenses": 15,
}


def ev(cur=None, prior=True):
    p = make_record(PRIOR, start=date(2025, 1, 1), end=date(2025, 12, 31)) if prior else None
    return Evaluator(make_record(CUR if cur is None else cur), prior=p)


class TestIndianCounterparts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ind_as_xbrl.register()

    def val(self, name, **kw):
        out = ev(**kw).value(name)
        self.assertIsNotNone(out.value, out.reason)
        return out

    def test_roe_deducts_preference_dividend_and_uses_average_equity(self):
        out = self.val("india.roe")
        self.assertEqual(out.value.quantize(Q10), D("25.4545454545"))          # (150 - 10) / ((600 + 500) / 2)
        # the generic average-equity ROE has no preference-dividend deduction: 150 / 550
        self.assertEqual(self.val("roe_avg").value.quantize(Q10), D("27.2727272727"))

    def test_roe_treats_a_missing_preference_dividend_as_zero_and_says_so(self):
        cur = {k: v for k, v in CUR.items() if k != "india.preference_dividend"}
        out = self.val("india.roe", cur=cur)
        self.assertEqual(out.value.quantize(Q10), D("27.2727272727"))
        self.assertTrue(any("india.preference_dividend not reported; treated as 0" in n for n in out.notes))

    def test_average_based_ratios_need_a_prior_period_and_never_guess(self):
        for name in ("india.roe", "india.roa", "india.inventory_turnover", "india.trade_receivables_turnover"):
            out = ev(prior=False).value(name)
            self.assertIsNone(out.value, name)
            self.assertIn("no earlier comparable period", out.reason)

    def test_roa_adds_back_interest_over_average_assets(self):
        self.assertEqual(self.val("india.roa").value.quantize(Q10), D("7.3636363636"))   # 162 / 2200

    def test_roce_on_tangible_net_worth_plus_debt_plus_deferred_tax(self):
        self.assertEqual(self.val("india.capital_employed").value, 820)        # (600 - 40) + 240 + 20
        self.assertEqual(self.val("india.roce").value.quantize(Q10), D("27.0731707317"))   # 222 / 820
        # the generic ROCE (total assets - current liabilities) is a different number: 222 / 2040
        self.assertEqual(self.val("roce").value.quantize(Q10), D("10.8823529412"))

    def test_quick_ratio_also_excludes_prepaid_expenses(self):
        self.assertEqual(self.val("india.quick_ratio").value.quantize(Q10), D("1.7361111111"))   # 625 / 360
        self.assertEqual(self.val("quick_ratio").value.quantize(Q10), D("1.7777777778"))         # 640 / 360

    def test_net_capital_turnover_is_sales_over_working_capital(self):
        self.assertEqual(self.val("india.net_capital_turnover").value.quantize(Q10), D("3.3333333333"))

    def test_turnovers_use_average_balances(self):
        self.assertEqual(self.val("india.inventory_turnover").value, 8)                       # 600 / 75
        self.assertEqual(self.val("india.trade_receivables_turnover").value.quantize(Q10), D("10.5263157895"))
        self.assertEqual(self.val("india.trade_payables_turnover").value.quantize(Q10), D("8.1818181818"))

    def test_receivable_days_use_the_real_period_length(self):
        out = self.val("india.trade_receivables_days")                                         # 365 x 95 / 1000
        self.assertEqual(out.value.quantize(D("1e-20")), D("34.675"))

    def test_credit_sales_and_purchases_fall_back_to_revenue_and_cost_with_a_note(self):
        cur = {k: v for k, v in CUR.items() if not k.startswith("india.net_credit")}
        recv = self.val("india.trade_receivables_turnover", cur=cur)
        self.assertEqual(recv.value.quantize(Q10), D("12.6315789474"))                         # 1200 / 95
        self.assertTrue(any("revenue used" in n for n in recv.notes))
        pay = self.val("india.trade_payables_turnover", cur=cur)
        self.assertEqual(pay.value.quantize(Q10), D("10.9090909091"))                          # 600 / 55
        self.assertTrue(any("cost of revenue used" in n for n in pay.notes))

    def test_debt_service_coverage_icai_form(self):
        self.assertEqual(self.val("india.dscr").value, D("4.3"))               # (150 + 48 + 12 + 5) / (12 + 8 + 30)

    def test_debt_service_coverage_sebi_suggested_form(self):
        self.assertEqual(self.val("india.dscr_sebi").value.quantize(Q10), D("5.2857142857"))   # 222 / (12 + 30)

    def test_dscr_without_a_principal_schedule_is_none_not_a_guess(self):
        cur = {k: v for k, v in CUR.items() if k != "india.scheduled_principal_repayment"}
        out = ev(cur).value("india.dscr")
        self.assertIsNone(out.value)
        self.assertIn("india.scheduled_principal_repayment not reported", out.reason)

    def test_registration_is_idempotent_and_leaves_the_generic_ratios_alone(self):
        ind_as_xbrl.register()
        self.assertEqual(ratios.get_spec("roe").formula, "100 * net_profit / total_equity")
        self.assertEqual(ratios.get_spec("interest_coverage").formula, "ebit / finance_costs")


if __name__ == "__main__":
    unittest.main()
