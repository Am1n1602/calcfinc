"""Valuation (priced at the fiscal year end), plus bank and insurer statement formats."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import Basis, Entity, FinancialEngine, FinancialFact, SharePrice, SqliteRepositories, StatementType

PL, BS = StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET
CONS = Basis.CONSOLIDATED
FY_START, FY_END = date(2026, 1, 1), date(2026, 12, 31)


def _fact(eid, metric, value, *, instant=False):
    return FinancialFact(
        entity_id=eid, metric=metric, value=value, statement_type=BS if instant else PL, basis=CONS,
        period_start=None if instant else FY_START, period_end=FY_END, financial_year=2026,
        is_annual=not instant, is_point_in_time=instant)


def _entity(repos, name, ticker, currency="USD"):
    return repos.entities.upsert(Entity(name=name, identifiers={"ticker": ticker}, currency=currency)).id


def _seed(repos):
    eid = _entity(repos, "Valco", "VAL")
    repos.facts.add_many(
        [_fact(eid, m, v) for m, v in [("revenue", 1000), ("net_profit", 100), ("pbt_before_exceptional", 130),
                                       ("finance_costs", 10), ("depreciation", 20), ("other_income", 0),
                                       ("eps_basic", 10), ("dividends", 40)]]
        + [_fact(eid, m, v, instant=True) for m, v in [("total_equity", 500), ("total_assets", 1200),
                                                       ("current_liabilities", 200), ("cash_and_equivalents", 50),
                                                       ("borrowings_noncurrent", 150), ("shares_outstanding", 10)]])
    repos.prices.add_prices([SharePrice(eid, date(2026, 12, 28), 200, "USD")])   # 3 days before year end
    repos.commit()
    return eid


class TestValuation(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = _seed(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_market_cap_and_pe(self):
        mc = self.eng.get_ratio("VAL", "market_cap", period="latest_annual")      # 200 x 10 shares
        self.assertEqual(mc.value, 2000)
        self.assertEqual((mc.unit, mc.currency), ("USD", "USD"))
        pe = self.eng.get_ratio("VAL", "pe", period="latest_annual")              # 200 / 10
        self.assertEqual(pe.value, 20)
        self.assertEqual(pe.unit, "x")
        self.assertEqual(pe.kind, "valuation")
        self.assertEqual(pe.components["share_price"], 200)
        self.assertEqual(pe.components["price_date"], "2026-12-28")
        self.assertIn("share_price", [i.metric for i in pe.inputs])

    def test_pb_and_yields(self):
        self.assertEqual(self.eng.get_ratio("VAL", "pb", period="latest_annual").value, 4)            # 2000 / 500
        self.assertEqual(self.eng.get_ratio("VAL", "earnings_yield", period="latest_annual").value, 5)  # 10 / 200
        self.assertEqual(self.eng.get_ratio("VAL", "dividend_yield", period="latest_annual").value, 2)  # (40/10)/200

    def test_ev_ebitda(self):
        # ebitda = 130 + 20 + 10 - 0 = 160; net debt = 150 - 50 = 100; EV = 2000 + 100 = 2100
        self.assertEqual(self.eng.get_ratio("VAL", "ev_ebitda", period="latest_annual").value, D("13.125"))

    def test_more_valuation_multiples(self):
        self.assertEqual(self.eng.get_valuation("VAL", "enterprise_value").value, 2100)
        self.assertEqual(self.eng.get_valuation("VAL", "ev_sales").value, D("2.1"))          # 2100 / 1000
        self.assertEqual(self.eng.get_valuation("VAL", "price_to_sales").value, 2)           # 2000 / 1000
        self.assertEqual(self.eng.get_valuation("VAL", "ev_ebit").value.quantize(D("1e-6")),
                         D("15"))                                                            # 2100 / (130 + 10 = 140)

    def test_latest_defaults_to_the_latest_annual_period_for_valuation(self):
        self.assertEqual(self.eng.get_ratio("VAL", "pe").value, 20)

    def test_missing_price_returns_none_with_limitation(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        _seed(repos)
        repos.connection.execute("DELETE FROM share_prices")
        repos.commit()
        r = FinancialEngine(repos).get_ratio("VAL", "pe", period="latest_annual")
        self.assertIsNone(r.value)
        self.assertTrue(any("no share price" in x for x in r.limitations))

    def test_price_in_another_currency_is_refused(self):
        self.repos.prices.add_prices([SharePrice(self.eid, date(2026, 12, 28), 200, "EUR")])
        r = self.eng.get_ratio("VAL", "pe", period="latest_annual")
        self.assertIsNone(r.value)
        self.assertTrue(any("different currencies" in x for x in r.limitations))

    def test_negative_earnings_give_no_pe(self):
        eid = _entity(self.repos, "Lossco", "LOSS")
        self.repos.facts.add_many([_fact(eid, "eps_basic", -3), _fact(eid, "shares_outstanding", 10, instant=True)])
        self.repos.prices.add_prices([SharePrice(eid, date(2026, 12, 28), 50, "USD")])
        r = FinancialEngine(self.repos).get_ratio("LOSS", "pe")
        self.assertIsNone(r.value)
        self.assertTrue(any("not positive" in x for x in r.limitations))

    def test_get_valuation_alias_and_compare(self):
        self.assertEqual(self.eng.get_valuation("VAL", "p/e").value, 20)
        cc = self.eng.compare_companies("pe", ["VAL"], period="latest_annual")
        self.assertEqual(cc["kind"], "ratio")
        self.assertEqual(cc["results"][0]["entity"], "Valco")

    def test_unknown_valuation_metric(self):
        r = self.eng.get_valuation("VAL", "peg")
        self.assertIsNone(r.value)
        self.assertTrue(any("unknown valuation metric" in x for x in r.limitations))

    def test_graham_number(self):
        # sqrt(22.5 x EPS 10 x book value per share (500 / 10 = 50)) = sqrt(11250) = 106.0660...
        r = self.eng.get_ratio("VAL", "graham_number")
        self.assertEqual(r.value.quantize(D("1e-10")), D("106.0660171780"))
        self.assertEqual(r.currency, "USD")


def _seed_bank(repos):
    eid = _entity(repos, "Bankco", "BNK")
    repos.facts.add_many(
        [_fact(eid, m, v) for m, v in [("net_profit", 200), ("pbt", 260), ("bank.operating_profit", 400),
                                       ("bank.provisions", 60), ("dividends", 50)]]
        + [_fact(eid, m, v, instant=True) for m, v in [("total_equity", 1000), ("total_assets", 20000),
                                                       ("shares_outstanding", 10)]])
    repos.prices.add_prices([SharePrice(eid, date(2026, 12, 28), 300, "USD")])
    repos.commit()


def _seed_insurer(repos):
    eid = _entity(repos, "Lifeco", "LIFE")
    repos.facts.add_many(
        [_fact(eid, m, v) for m, v in [("net_profit", 50), ("total_expenses", 2400), ("total_income", 2500)]]
        + [_fact(eid, m, v, instant=True) for m, v in [("total_equity", 500), ("total_assets", 10000)]])
    repos.commit()


class TestBankValuation(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        _seed_bank(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_pe_from_net_profit_when_no_reported_eps(self):
        # shares 10; EPS = 200 / 10 = 20; P/E = 300 / 20 = 15
        pe = self.eng.get_ratio("BNK", "pe", period="latest_annual")
        self.assertEqual(pe.value, 15)
        self.assertTrue(any("EPS derived" in x for x in pe.limitations))
        self.assertEqual(pe.formula, "share_price / eps")

    def test_ev_ebitda_uses_ppop_proxy_and_says_so(self):
        # market cap 3000 / pre-provision operating profit 400 = 7.5
        ev = self.eng.get_ratio("BNK", "ev_ebitda", period="latest_annual")
        self.assertEqual(ev.value, D("7.5"))
        self.assertTrue(any("PPOP" in x for x in ev.limitations))
        self.assertEqual(ev.formula, "market_cap / bank.operating_profit")      # the formula actually used


class TestInsurerRatios(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        _seed_insurer(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_margin_uses_total_income_topline(self):
        m = self.eng.get_ratio("LIFE", "net_profit_margin", period="latest_annual")      # 50 / 2500
        self.assertEqual(m.value, 2)
        self.assertTrue(any("total_income used" in x for x in m.limitations))

    def test_roe_and_dupont(self):
        self.assertEqual(self.eng.get_ratio("LIFE", "roe", period="latest_annual").value, 10)    # 50 / 500
        comps = self.eng.decompose_metric("LIFE", "roe", period="latest_annual").components["components"]
        self.assertEqual(comps["net_profit_margin"], 2)
        self.assertEqual(comps["asset_turnover"], D("0.25"))        # 2500 / 10000
        self.assertEqual(comps["equity_multiplier"], 20)            # 10000 / 500


if __name__ == "__main__":
    unittest.main()
