"""build_period_records grouping, merging, restatements and period typing."""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from calcfinc import Entity, SqliteRepositories
from calcfinc.engine import build_period_records
from calcfinc.period import PeriodWindows, fiscal_year
from tests._fixture import bs, pl, seed


def fy26_revenue_fact(eid, value=1200):
    return pl(eid, "revenue", value, 2026, None, date(2026, 1, 1), date(2026, 12, 31), annual=True)


class TestRecords(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = seed(self.repos)

    def fy26(self):
        recs = build_period_records(self.repos, self.eid, "consolidated")
        return next(r for r in recs if r.is_annual and r.financial_year == 2026)

    def test_instant_merged_into_duration_for_same_period_end(self):
        fy26 = self.fy26()
        self.assertEqual(fy26.get("revenue"), 1200)           # from the duration fact
        self.assertEqual(fy26.get("total_assets"), 2400)      # merged from the balance-sheet snapshot
        self.assertEqual(fy26.get("total_equity"), 600)
        self.assertEqual(fy26.currencies["total_assets"], "USD")

    def test_quarters_are_single_quarter(self):
        recs = build_period_records(self.repos, self.eid, "consolidated")
        q1 = next(r for r in recs if r.quarter == 1)
        self.assertTrue(q1.is_single_quarter)
        self.assertFalse(q1.is_annual)
        self.assertEqual(q1.get("revenue"), 280)

    def test_sorted_chronologically(self):
        recs = build_period_records(self.repos, self.eid, "consolidated")
        ends = [r.period_end for r in recs]
        self.assertEqual(ends, sorted(ends))
        self.assertEqual(recs[-1].period_end, date(2026, 12, 31))

    def test_labels(self):
        labels = {r.label for r in build_period_records(self.repos, self.eid, "consolidated")}
        self.assertIn("FY2026", labels)
        self.assertIn("FY2026 Q1", labels)

    def test_unknown_metric_absent(self):
        recs = build_period_records(self.repos, self.eid, "consolidated")
        self.assertNotIn("made_up", recs[-1].values)
        self.assertIsNone(recs[-1].get("made_up"))

    def test_restated_figure_replaces_the_original_and_the_original_is_kept(self):
        # FY2026 revenue was seeded as 1200 with no report date, then re-published as 1200 and
        # restated to 1250 later. The latest report wins; every version stays stored.
        self.repos.facts.add_many([
            replace(fy26_revenue_fact(self.eid, 1200), reported_at=date(2027, 2, 1)),
            replace(fy26_revenue_fact(self.eid, 1250), reported_at=date(2027, 9, 1)),
        ])
        self.assertEqual(self.fy26().get("revenue"), 1250)
        stored = [f for f in self.repos.facts.list_facts(self.eid, metric="revenue")
                  if f.period_end == date(2026, 12, 31)]
        self.assertEqual([f.value for f in stored], [1200, 1200, 1250])

    def test_a_later_missing_value_never_erases_a_reported_one(self):
        self.repos.facts.add_many([replace(fy26_revenue_fact(self.eid), value=None,
                                           reported_at=date(2027, 3, 1), mapping_reason="withdrawn")])
        rec = self.fy26()
        self.assertEqual(rec.get("revenue"), 1200)
        self.assertEqual(rec.review_flags["revenue"], "withdrawn")      # the reason is kept for review


class TestPeriodTyping(unittest.TestCase):
    def test_windows_classify_by_duration(self):
        w = PeriodWindows()
        self.assertEqual([w.classify(d) for d in (30, 89, 181, 364, 500, None)],
                         ["month", "quarter", "half", "year", None, None])

    def test_windows_are_configurable(self):
        self.assertEqual(PeriodWindows(month=(26, 35)).classify(34), "month")
        self.assertIsNone(PeriodWindows().classify(34))

    def test_fiscal_year_follows_the_entity_year_end(self):
        self.assertEqual(fiscal_year(date(2025, 12, 31), 12), 2025)
        self.assertEqual(fiscal_year(date(2026, 3, 31), 3), 2026)    # April-March year
        self.assertEqual(fiscal_year(date(2025, 6, 30), 3), 2026)
        self.assertEqual(fiscal_year(date(2025, 6, 30), 6), 2025)    # July-June year

    def test_balance_sheet_only_snapshot_gets_its_fiscal_year_from_the_entity(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        eid = repos.entities.upsert(Entity(name="Mar Co", currency="INR", fiscal_year_end_month=3)).id
        repos.facts.add_many([bs(eid, "total_assets", 100, 0, date(2025, 6, 30))])
        rec = build_period_records(repos, eid, "consolidated", fiscal_year_end_month=3)[0]
        self.assertEqual(rec.financial_year, 2026)
        rec = build_period_records(repos, eid, "consolidated", fiscal_year_end_month=12)[0]
        self.assertEqual(rec.financial_year, 2025)


if __name__ == "__main__":
    unittest.main()
