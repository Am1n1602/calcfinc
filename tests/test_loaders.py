"""Loaders: period labels, inference, row-level errors, all-or-nothing loading, CSV layouts,
and DataFrame float handling. Expected numbers are worked out by hand."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from importlib.util import find_spec
from pathlib import Path

from calcfinc import FinancialEngine
from calcfinc.loaders import LoadError, load_csv, load_records
from calcfinc.period import resolve_period
from calcfinc.store import SqliteRepositories


class TestPeriodLabels(unittest.TestCase):
    def test_fiscal_labels_follow_the_year_end(self):
        p = resolve_period("FY2026", 3)                          # April 2025 - March 2026
        self.assertEqual((p.start, p.end, p.is_annual), (date(2025, 4, 1), date(2026, 3, 31), True))
        q = resolve_period("FY2026Q1", 3)
        self.assertEqual((q.start, q.end, q.quarter), (date(2025, 4, 1), date(2025, 6, 30), 1))
        q4 = resolve_period("FY2026Q4", 3)
        self.assertEqual((q4.start, q4.end), (date(2026, 1, 1), date(2026, 3, 31)))
        self.assertEqual(resolve_period("FY2025", 12).end, date(2025, 12, 31))
        self.assertEqual(resolve_period("FY2026", 6).start, date(2025, 7, 1))     # July-June year

    def test_months_ranges_and_single_dates(self):
        m = resolve_period("2028-02")
        self.assertEqual((m.start, m.end, m.is_annual), (date(2028, 2, 1), date(2028, 2, 29), False))
        r = resolve_period("2026-01-01..2026-03-31", 12)
        self.assertEqual((r.quarter, r.financial_year), (1, 2026))
        self.assertEqual(resolve_period("2026-04-01..2026-06-30", 3).quarter, 1)
        d = resolve_period("2026-12-31")
        self.assertEqual((d.start, d.end), (None, date(2026, 12, 31)))

    def test_bad_labels_say_what_is_accepted(self):
        for bad in ("2026", "FY26", "2026-13", "2026-12-31..2026-01-01", "Q1 2026"):
            with self.assertRaises(ValueError, msg=bad):
                resolve_period(bad)


LONG = """entity,metric,period,value,currency
Acme,revenue,FY2025,1000,USD
Acme,revenue,FY2026,1200,USD
Acme,net_profit,FY2025,100,USD
Acme,net_profit,FY2026,150,USD
Acme,total_equity,FY2025,500,USD
Acme,total_equity,FY2026,600,USD
"""
WIDE = """metric,FY2025,FY2026
revenue,1000,1200
net_profit,100,150
total_equity,500,600
"""


class TestRecordsAndCsv(unittest.TestCase):
    def tmp(self, text, name="data.csv"):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_long_csv_gives_hand_computed_results(self):
        eng = FinancialEngine.from_csv(self.tmp(LONG))
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_ratio("Acme", "roe").value, 25)                       # 150 / 600
        self.assertEqual(eng.get_growth("Acme", "revenue").value, 20)                  # 1000 -> 1200
        r = eng.get_metric("Acme", "revenue")
        self.assertEqual((r.unit, r.period), ("USD", "FY2026"))
        self.assertIsNotNone(r.inputs[0].source_id)                                    # provenance back to the file

    def test_wide_csv_with_an_entity_argument_matches_the_long_file(self):
        eng = FinancialEngine.from_csv(self.tmp(WIDE), entity="Acme", currency="USD")
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_ratio("Acme", "roe").value, 25)
        self.assertEqual(eng.get_cagr("Acme", "revenue").value, 20)

    def test_balance_sheet_items_become_instants_and_flows_become_ranges(self):
        eng = FinancialEngine.from_csv(self.tmp(WIDE), entity="Acme", currency="USD")
        self.addCleanup(eng.repos.close)
        facts = {f.metric: f for f in eng.repos.facts.list_facts(1) if f.financial_year == 2026}
        self.assertEqual((facts["revenue"].period_start, facts["revenue"].is_annual), (date(2026, 1, 1), True))
        self.assertEqual((facts["total_equity"].period_start, facts["total_equity"].is_point_in_time),
                         (None, True))
        self.assertEqual(facts["total_equity"].period_end, date(2026, 12, 31))

    def test_fiscal_year_end_and_explicit_columns_override_inference(self):
        rows = [{"entity": "Bharat", "metric": "revenue", "period": "FY2026", "value": "1000", "currency": "INR"},
                {"entity": "Bharat", "metric": "revenue", "period_start": "2025-04-01", "period_end": "2026-03-31",
                 "value": "1000", "currency": "INR", "basis": "standalone", "financial_year": "2026",
                 "reported_at": "2026-05-20", "source": "annual report"}]
        eng = FinancialEngine.from_records(rows, fiscal_year_end_month=3)
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_metric("Bharat", "revenue").value, 1000)
        self.assertEqual(eng.get_metric("Bharat", "revenue", basis="standalone").period, "FY2026")
        solo = eng.repos.facts.list_facts(1, basis="standalone")[0]
        self.assertEqual(solo.reported_at, date(2026, 5, 20))
        self.assertEqual(eng.repos.sources.get(solo.source_id).document_title, "annual report")

    def test_an_empty_value_is_stored_as_not_reported_not_zero(self):
        rows = [{"entity": "A", "metric": "revenue", "period": "FY2026", "value": "", "currency": "USD"}]
        eng = FinancialEngine.from_records(rows)
        self.addCleanup(eng.repos.close)
        self.assertIsNone(eng.repos.facts.list_facts(1)[0].value)
        self.assertIsNone(eng.get_metric("A", "revenue").value)

    def test_every_bad_row_is_reported_with_its_line_and_nothing_is_loaded(self):
        bad = LONG + ("Acme,revenue,FY2028,12x,USD\n"             # line 8
                      "Acme,revnue,FY2029,5,USD\n"                # line 9
                      "Acme,revenue,2029,5,USD\n"                 # line 10
                      "Acme,net_profit,FY2030,abc,USD\n")         # line 11
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        with self.assertRaises(LoadError) as ctx:
            load_csv(repos, self.tmp(bad))
        errors = ctx.exception.errors
        self.assertEqual([e.split(":")[0] for e in errors],
                         ["row 8, value", "row 9, metric", "row 10, period", "row 11, value"])
        self.assertEqual(repos.facts.list_facts(1), [])                             # nothing partially loaded
        self.assertEqual(repos.entities.list(), [])

    def test_a_row_with_too_many_cells_is_a_structural_error(self):
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_csv(self.tmp(LONG + "Acme,revenue,FY2027,1,200,USD\n"))     # unquoted comma
        self.assertIn("row 8: 6 cells but the header has 5", ctx.exception.errors[0])

    def test_row_level_messages(self):
        rows = [{"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1,200", "currency": "USD"},
                {"entity": "A", "metric": "revnue", "period": "FY2026", "value": "1", "currency": "USD"},
                {"entity": "A", "metric": "revenue", "period": "2026", "value": "1", "currency": "USD"},
                {"entity": "A", "metric": "revenue", "period": "FY2026", "value": 0.1, "currency": "USD"},
                {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1"},
                {"entity": "A", "metric": "revenue", "value": "1", "period_end": "2026-12-31", "currency": "USD"},
                {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1", "curency": "USD"}]
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_records(rows)
        text = "\n".join(ctx.exception.errors)
        for needle in ("row 1, value:", "write 1200.5", "unknown metric 'revnue'",
                       "unrecognised period '2026'", "row 4, value: float", "is an amount",
                       "flow metric and needs", "unknown column 'curency'"):
            self.assertIn(needle, text)

    def test_wide_header_errors_name_the_column(self):
        with self.assertRaises(LoadError) as ctx:
            FinancialEngine.from_csv(self.tmp("metric,FY2025,Total\nrevenue,1,2\n"), entity="A", currency="USD")
        self.assertIn("header 'Total'", ctx.exception.errors[0])

    def test_loading_the_same_file_twice_reuses_the_source(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        path = self.tmp(LONG)
        load_csv(repos, path)
        load_csv(repos, path)
        self.assertEqual(repos.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)
        self.assertEqual(len(repos.facts.list_facts(1)), 6)                          # same grain: overwritten

    def test_excel_style_bom_and_blank_lines_are_tolerated(self):
        path = self.tmp("﻿" + WIDE.replace("\n", "\n\n"))
        eng = FinancialEngine.from_csv(path, entity="Acme", currency="USD")
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_metric("Acme", "revenue").value, 1200)

    def test_existing_entities_are_reused_by_identifier(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        from calcfinc import Entity
        repos.entities.upsert(Entity(name="Acme Inc", identifiers={"ticker": "ACME"}, currency="USD",
                                     fiscal_year_end_month=3))
        report = load_records(repos, [{"entity": "acme", "metric": "revenue", "period": "FY2026", "value": "5"}])
        self.assertEqual((report.facts, report.created), (1, ()))
        fact = repos.facts.list_facts(1)[0]
        self.assertEqual((fact.period_start, fact.currency), (date(2025, 4, 1), "USD"))   # its own calendar


@unittest.skipUnless(find_spec("pandas"), "pandas is not installed (optional extra)")
class TestDataFrame(unittest.TestCase):
    def test_long_frame_with_strings_loads(self):
        import pandas as pd
        df = pd.DataFrame({"entity": ["A", "A"], "metric": ["revenue", "revenue"], "period": ["FY2025", "FY2026"],
                           "value": ["1000", "1200"], "currency": ["USD", "USD"]})
        eng = FinancialEngine.from_dataframe(df)
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_growth("A", "revenue").value, 20)

    def test_float_cells_are_refused_by_default(self):
        import pandas as pd
        df = pd.DataFrame({"metric": ["revenue"], "FY2026": [1200.5]})
        with self.assertRaises(TypeError) as ctx:
            FinancialEngine.from_dataframe(df, layout="wide", entity="A", currency="USD")
        self.assertIn("float_policy='repr'", str(ctx.exception))

    def test_repr_policy_converts_through_shortest_text_and_records_it(self):
        import pandas as pd
        df = pd.DataFrame({"metric": ["revenue", "net_profit"], "FY2025": [0.1, None],
                           "FY2026": [0.30000000000000004, 5.5]})
        eng = FinancialEngine.from_dataframe(df, layout="wide", float_policy="repr", entity="A", currency="USD")
        self.addCleanup(eng.repos.close)
        # 0.1 arrives as the text "0.1", not as the binary value 0.1000000000000000055...
        self.assertEqual(eng.get_metric("A", "revenue", period="FY2025").value, D("0.1"))
        self.assertEqual(eng.get_metric("A", "revenue", period="FY2026").value, D("0.30000000000000004"))
        self.assertIsNone(eng.get_metric("A", "net_profit", period="FY2025").value)            # NaN = not reported
        note = eng.repos.sources.get(1).document_title
        self.assertIn("4 float cell(s) converted", note)             # 0.1, NaN, 0.3..., 5.5

    def test_metric_as_index_and_integer_columns(self):
        import pandas as pd
        df = pd.DataFrame({"FY2025": [1000, 100], "FY2026": [1200, 150]},
                          index=pd.Index(["revenue", "net_profit"], name="metric"))
        eng = FinancialEngine.from_dataframe(df, layout="wide", entity="A", currency="USD")
        self.addCleanup(eng.repos.close)
        self.assertEqual(eng.get_ratio("A", "net_profit_margin").value, D("12.5"))


if __name__ == "__main__":
    unittest.main()
