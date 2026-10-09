"""Growth, CAGR and period comparisons must name the facts they were computed from, each with its own
source, filing date and currency. Expected values are worked out by hand; source ids are never compared
to a number, they are resolved through the store to the source's title."""
from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import FinancialEngine


def row(metric, period, value, source, reported, entity="Acme", currency="USD"):
    return {"entity": entity, "metric": metric, "period": period, "value": value, "currency": currency,
            "source": source, "reported_at": reported}


class Base(unittest.TestCase):
    def engine(self, rows, **kw):
        eng = FinancialEngine.from_records(rows, **kw)
        self.addCleanup(eng.repos.close)
        return eng

    def seen(self, eng, result):
        """(metric, period, value, source title, reported_at, currency) for each input, in order."""
        return [(i.metric, i.period, i.value, eng.repos.sources.get(i.source_id).document_title,
                 i.reported_at, i.currency) for i in result.inputs]


class TestGrowthKeepsProvenance(Base):
    def test_yoy_on_a_reported_metric_names_both_years_with_their_own_filings(self):
        eng = self.engine([row("revenue", "FY2025", "100", "10-K 2025", "2025-11-01"),
                           row("revenue", "FY2026", "120", "10-K 2026", "2026-11-01")])
        r = eng.get_growth("Acme", "revenue")
        self.assertEqual(r.value, 20)
        self.assertEqual(self.seen(eng, r), [
            ("revenue", "FY2025", D(100), "10-K 2025", date(2025, 11, 1), "USD"),
            ("revenue", "FY2026", D(120), "10-K 2026", date(2026, 11, 1), "USD")])

    def test_qoq_keeps_each_quarters_own_filing(self):
        eng = self.engine([row("revenue", "FY2026Q1", "100", "10-Q Q1", "2026-05-01"),
                           row("revenue", "FY2026Q2", "110", "10-Q Q2", "2026-08-01")])
        r = eng.get_growth("Acme", "revenue", kind="qoq")
        self.assertEqual(r.value, 10)
        self.assertEqual([(p, t, d) for (_, p, _, t, d, _) in self.seen(eng, r)],
                         [("FY2026 Q1", "10-Q Q1", date(2026, 5, 1)), ("FY2026 Q2", "10-Q Q2", date(2026, 8, 1))])

    def test_mom_keeps_each_months_own_source(self):
        eng = self.engine([row("revenue", "2026-01", "200", "Jan accounts", "2026-02-10"),
                           row("revenue", "2026-02", "210", "Feb accounts", "2026-03-10")])
        r = eng.get_growth("Acme", "revenue", kind="mom")
        self.assertEqual(r.value, 5)
        self.assertEqual([(t, d) for (_, _, _, t, d, _) in self.seen(eng, r)],
                         [("Jan accounts", date(2026, 2, 10)), ("Feb accounts", date(2026, 3, 10))])

    def test_cagr_start_and_end_keep_their_own_vintages(self):
        eng = self.engine([row("revenue", "FY2024", "100", "10-K 2024", "2024-11-01"),
                           row("revenue", "FY2025", "110", "10-K 2025", "2025-11-01"),
                           row("revenue", "FY2026", "121", "10-K 2026", "2026-11-01")])
        r = eng.get_cagr("Acme", "revenue")
        self.assertEqual(r.value, 10)                                    # (121 / 100) ** (1 / 2) - 1
        self.assertEqual([(p, t, d) for (_, p, _, t, d, _) in self.seen(eng, r)],
                         [("FY2024", "10-K 2024", date(2024, 11, 1)), ("FY2026", "10-K 2026", date(2026, 11, 1))])

    def test_growth_of_a_ratio_traces_to_the_underlying_facts_not_a_stand_in(self):
        eng = self.engine([row("net_profit", "FY2025", "10", "NP25", "2025-11-01"),
                           row("revenue", "FY2025", "100", "REV25", "2025-11-02"),
                           row("net_profit", "FY2026", "15", "NP26", "2026-11-01"),
                           row("revenue", "FY2026", "120", "REV26", "2026-11-02")])
        r = eng.get_growth("Acme", "net_profit_margin")
        # margins are 10% and 12.5%, so growth is 25%
        self.assertEqual(r.value, 25)
        got = {(m, p): (v, t) for (m, p, v, t, _, _) in self.seen(eng, r)}
        self.assertEqual(got, {("net_profit", "FY2025"): (D(10), "NP25"), ("revenue", "FY2025"): (D(100), "REV25"),
                               ("net_profit", "FY2026"): (D(15), "NP26"), ("revenue", "FY2026"): (D(120), "REV26")})
        self.assertTrue(all(i.source_id is not None and i.reported_at is not None for i in r.inputs))
        self.assertNotIn("net_profit_margin", {i.metric for i in r.inputs})

    def test_a_restated_input_keeps_its_actual_source_and_date(self):
        eng = self.engine([row("revenue", "FY2025", "100", "10-K 2025", "2025-11-01"),
                           row("revenue", "FY2026", "120", "10-K 2026", "2026-11-01"),
                           row("revenue", "FY2026", "110", "10-K/A 2026 restated", "2027-03-01")])
        r = eng.get_growth("Acme", "revenue")
        self.assertEqual(r.value, 10)                                    # the restated 110 against 100
        self.assertEqual(self.seen(eng, r)[1][2:5], (D(110), "10-K/A 2026 restated", date(2027, 3, 1)))

    def test_inputs_from_filings_far_apart_are_flagged_in_the_limitations(self):
        eng = self.engine([row("net_profit", "FY2026", "15", "NP", "2026-11-01"),
                           row("revenue", "FY2026", "120", "REV recast", "2027-11-01"),
                           row("net_profit", "FY2025", "10", "NP25", "2025-11-01"),
                           row("revenue", "FY2025", "100", "REV25", "2025-11-01")])
        r = eng.get_growth("Acme", "net_profit_margin")
        self.assertTrue(any("different filings" in t and "FY2026" in t for t in r.limitations), r.limitations)

    def test_missing_data_is_still_none_with_the_old_reason_and_no_invented_provenance(self):
        eng = self.engine([row("revenue", "FY2026", "120", "10-K 2026", "2026-11-01")])
        r = eng.get_growth("Acme", "revenue")
        self.assertIsNone(r.value)
        self.assertEqual(r.inputs, ())
        self.assertEqual(r.limitations, ("no periods with revenue",))        # the message it always had
        c = eng.get_cagr("Acme", "revenue")
        self.assertEqual((c.value, c.inputs), (None, ()))
        self.assertEqual(eng.get_growth("Acme", "no_such_metric").inputs, ())


class TestComparePeriodsKeepsProvenance(Base):
    ROWS = [row("revenue", "FY2025", "100", "REV25", "2025-11-01"),
            row("revenue", "FY2026", "120", "REV26", "2026-11-01"),
            row("net_profit", "FY2025", "10", "NP25", "2025-11-02"),
            row("net_profit", "FY2026", "15", "NP26", "2026-11-02")]

    def test_one_metric_names_both_periods_facts(self):
        eng = self.engine(self.ROWS)
        r = eng.compare_periods("Acme", "revenue", a="FY2025", b="FY2026")
        self.assertEqual(r.components["revenue"]["pct_change"], 20)       # existing output unchanged
        self.assertEqual([(p, t) for (_, p, _, t, _, _) in self.seen(eng, r)],
                         [("FY2025", "REV25"), ("FY2026", "REV26")])

    def test_several_metrics_do_not_borrow_each_others_inputs(self):
        eng = self.engine(self.ROWS)
        r = eng.compare_periods("Acme", ["revenue", "net_profit"], a="FY2025", b="FY2026")
        for name, titles in (("revenue", {"REV25", "REV26"}), ("net_profit", {"NP25", "NP26"})):
            own = r.components[name]["inputs"]
            self.assertEqual({i.metric for i in own}, {name})
            self.assertEqual({eng.repos.sources.get(i.source_id).document_title for i in own}, titles)
        self.assertEqual(len(r.inputs), 4)

    def test_a_ratio_compares_through_its_leaf_facts(self):
        eng = self.engine(self.ROWS)
        r = eng.compare_periods("Acme", "net_profit_margin", a="FY2025", b="FY2026")
        self.assertEqual(r.components["net_profit_margin"]["abs_change"], D("2.5"))     # 12.5% less 10%
        self.assertEqual({i.metric for i in r.inputs}, {"net_profit", "revenue"})
        self.assertEqual(len(r.inputs), 4)

    def test_a_metric_missing_in_one_period_gets_only_the_provenance_that_exists(self):
        eng = self.engine(self.ROWS[:2] + [self.ROWS[2]])               # no FY2026 net profit
        r = eng.compare_periods("Acme", "net_profit", a="FY2025", b="FY2026")
        self.assertEqual((r.components["net_profit"]["from"], r.components["net_profit"]["to"]), (10, None))
        self.assertEqual([(i.period, i.value) for i in r.inputs], [("FY2025", D(10))])
        unknown = eng.compare_periods("Acme", "ebit", a="FY2025", b="FY2026")
        self.assertEqual(unknown.inputs, ())
        self.assertFalse(unknown.ok)


class TestSerialisation(Base):
    def test_to_dict_keeps_source_dates_currency_and_exact_decimal_strings(self):
        eng = self.engine([row("revenue", "FY2025", "100.10", "10-K 2025", "2025-11-01"),
                           row("revenue", "FY2026", "120.20", "10-K 2026", "2026-11-01")])
        d = json.loads(json.dumps(eng.get_growth("Acme", "revenue").to_dict()))
        first = d["inputs"][0]
        self.assertEqual((first["metric"], first["value"], first["currency"], first["reported_at"]),
                         ("revenue", "100.10", "USD", "2025-11-01"))
        self.assertIsInstance(first["source_id"], int)
        c = json.loads(json.dumps(eng.compare_periods("Acme", "revenue", a="FY2025", b="FY2026").to_dict()))
        self.assertEqual(c["components"]["revenue"]["inputs"][1]["reported_at"], "2026-11-01")


if __name__ == "__main__":
    unittest.main()
