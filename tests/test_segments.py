"""SegmentEngine: contribution %, YoY growth, share-of-total-change."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from calcfinc import Basis, Entity, Segment, SegmentFact, SqliteRepositories
from calcfinc.engine import SegmentEngine
from calcfinc.num import dsum

CONS = Basis.CONSOLIDATED


def _sf(sid, eid, value, fy, *, annual=True, currency="USD"):
    return SegmentFact(
        segment_id=sid, entity_id=eid, metric="segment_revenue", value=value, basis=CONS, currency=currency,
        period_start=date(fy, 1, 1), period_end=date(fy, 12, 31), financial_year=fy, is_annual=annual)


class TestSegmentEngine(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.eid = self.repos.entities.upsert(
            Entity(name="Testco", identifiers={"ticker": "TEST"})).id
        seg = lambda n: self.repos.segments.upsert_segment(Segment(self.eid, n)).segment_id  # noqa: E731
        self.a, self.b, self.c = seg("Alpha"), seg("Beta"), seg("Gamma")
        # FY2025 totals 1000 (600/300/100); FY2026 totals 1300 (700/450/150) -> +300
        self.repos.segments.add_facts([
            _sf(self.a, self.eid, 600, 2025), _sf(self.b, self.eid, 300, 2025), _sf(self.c, self.eid, 100, 2025),
            _sf(self.a, self.eid, 700, 2026), _sf(self.b, self.eid, 450, 2026), _sf(self.c, self.eid, 150, 2026),
        ])
        self.repos.commit()
        self.eng = SegmentEngine(self.repos)

    def test_get_segment_data_contributions(self):
        r = self.eng.get_segment_data("TEST", period="latest_annual")
        self.assertTrue(r.ok)
        self.assertEqual([row.segment for row in r.rows], ["Alpha", "Beta", "Gamma"])   # sorted by revenue desc
        self.assertEqual(r.total_revenue, 1300)
        self.assertEqual(r.currency, "USD")
        self.assertEqual(r.rows[1].contribution_pct.quantize(D("1e-10")), D("34.6153846154"))   # 450 / 1300
        self.assertEqual(r.rows[0].contribution_pct.quantize(D("1e-10")), D("53.8461538462"))   # 700 / 1300
        self.assertLessEqual(abs(dsum(row.contribution_pct for row in r.rows) - 100), D("1e-30"))
        self.assertTrue(any("margin not available" in x for x in r.limitations))

    def test_get_segment_data_specific_fy(self):
        r = self.eng.get_segment_data("TEST", period="FY2025")
        self.assertEqual(r.total_revenue, 1000)
        self.assertEqual(r.rows[0].contribution_pct, 60)

    def test_segment_growth_attribution(self):
        r = self.eng.segment_growth("TEST", kind="yoy")
        self.assertTrue(r.ok)
        self.assertEqual(r.total_change, 300)
        by = {row.segment: row for row in r.rows}
        self.assertEqual(by["Alpha"].abs_change, 100)
        self.assertEqual(by["Beta"].abs_change, 150)
        self.assertEqual(by["Gamma"].abs_change, 50)
        self.assertEqual(by["Beta"].share_of_total_change_pct, 50)                     # 150 / 300
        self.assertEqual(by["Alpha"].growth_pct.quantize(D("1e-10")), D("16.6666666667"))   # 100 / 600
        self.assertEqual(r.rows[0].segment, "Beta")                                    # biggest contributor first

    def test_mixed_currencies_are_refused_not_summed(self):
        self.repos.segments.add_facts([_sf(self.b, self.eid, 450, 2026, currency="EUR")])
        r = self.eng.get_segment_data("TEST", period="FY2026")
        self.assertIsNone(r.total_revenue)
        self.assertTrue(any("different currencies" in x for x in r.limitations))

    def test_unknown_entity(self):
        r = self.eng.get_segment_data("NOPE")
        self.assertFalse(r.ok)
        self.assertTrue(r.limitations)

    def test_no_segments(self):
        self.repos.entities.upsert(Entity(name="Plainco", identifiers={"ticker": "PLAIN"}))
        r = self.eng.get_segment_data("PLAIN")
        self.assertFalse(r.ok)
        self.assertIn("single-segment or not disclosed", r.limitations[0])


if __name__ == "__main__":
    unittest.main()
