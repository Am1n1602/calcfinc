"""SEC companyfacts adapter. The document below is synthetic (a made-up company); no SEC data is
stored in this repository, and no test touches the network."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import sec_companyfacts as sec
from calcfinc.adapters.sec_companyfacts import fetch

A1, A2, A3, A4, A5, A8, A9, A10, A11 = (f"0000123456-{y}-0000{n:02d}" for y, n in
                                        ((25, 1), (25, 2), (25, 3), (26, 4), (26, 5), (26, 8), (27, 9), (26, 10),
                                         (26, 11)))
FILED = {A1: "2025-05-02", A2: "2025-08-01", A3: "2025-10-31", A4: "2026-02-20", A5: "2026-05-01",
         A8: "2026-02-01", A9: "2027-02-19", A10: "2026-03-10", A11: "2025-08-15"}
FORM = {A1: "10-Q", A2: "10-Q", A3: "10-Q", A4: "10-K", A5: "10-Q", A8: "8-K", A9: "10-K", A10: "20-F", A11: "6-K"}


def e(start, end, val, accn, **extra):
    d = {"end": end, "val": val, "accn": accn, "fy": 1999, "fp": "ZZ",       # fy / fp are meaningless here
         "form": FORM[accn], "filed": FILED[accn], **extra}
    if start:
        d["start"] = start
    return d


def concept(unit, *entries):
    return {"label": "x", "units": {unit: list(entries)}}


def document(us=None, dei=None, ifrs=None):
    return {"cik": 1234567, "entityName": "Synthco Inc",
            "facts": {"us-gaap": us or {}, **({"dei": dei} if dei else {}), **({"ifrs-full": ifrs} if ifrs else {})}}


Q1, Q2, Q3 = ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30")
H1, N9, FY = ("2025-01-01", "2025-06-30"), ("2025-01-01", "2025-09-30"), ("2025-01-01", "2025-12-31")

US = {
    "Revenues": concept(
        "USD", e(*Q1, 100, A1), e(*Q2, 110, A2), e(*H1, 210, A2), e(*Q3, 120, A3), e(*N9, 330, A3),
        e(*FY, 450, A4), e(*FY, 450, A9),                              # A9 repeats the comparative: not a restatement
        e(*FY, 999, A8)),                                              # an 8-K: ignored
    "RevenueFromContractWithCustomerExcludingAssessedTax": concept(
        "USD", e("2026-01-01", "2026-03-31", 130, A5)),                 # the only concept for this quarter
    "NetIncomeLoss": concept(
        "USD", e(*Q1, 18, A1), e(*Q2, 20, A2), e(*H1, 38, A2), e(*Q3, 22, A3), e(*N9, 60, A3),
        e(*FY, 80, A4), e(*FY, 78, A9)),                               # FY2025 restated from 80 to 78
    "NetCashProvidedByUsedInOperatingActivities": concept(             # cash flow: year-to-date only
        "USD", e(*Q1, 20, A1), e(*H1, 45, A2), e(*N9, 75, A3), e(*FY, 110, A4)),
    "EarningsPerShareBasic": concept(
        "USD/shares", e(*Q1, D("0.18"), A1), e(*Q2, D("0.20"), A2), e(*Q3, D("0.22"), A3),
        e(*N9, D("0.60"), A3), e(*FY, D("0.80"), A4)),
    "Assets": concept("USD", e(None, "2025-09-30", 950, A3), e(None, "2025-12-31", 1000, A4),
                      e(None, "2026-03-31", 1050, A5)),
    "StockholdersEquity": concept("USD", e(None, "2025-12-31", 400, A4), e(None, "2026-03-31", 420, A5)),
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
        concept("USD", e(*FY, 100, A4)),
}
DEI = {"EntityCommonStockSharesOutstanding": concept("shares", e(None, "2026-02-10", 1000000, A4))}


class Base(unittest.TestCase):
    def load(self, doc=None, **kw):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.report = sec.load_companyfacts(self.repos, doc or document(US, DEI), **kw)
        return self.repos

    def facts(self, metric, **filt):
        out = [f for f in self.repos.facts.list_facts(1, metric=metric)
               if all(getattr(f, k) == v for k, v in filt.items())]
        return {(f.period_start, f.period_end, f.reported_at): f for f in out}


class TestPeriodsAndVersions(Base):
    def setUp(self):
        self.load()

    def test_only_single_quarters_and_years_are_stored_never_year_to_date(self):
        spans = {(f.period_start, f.period_end) for f in self.repos.facts.list_facts(1, metric="revenue")}
        self.assertIn((date(2025, 1, 1), date(2025, 12, 31)), spans)
        self.assertNotIn((date(2025, 1, 1), date(2025, 6, 30)), spans)         # 6 months
        self.assertNotIn((date(2025, 1, 1), date(2025, 9, 30)), spans)         # 9 months

    def test_direct_quarters_and_the_derived_fourth_quarter(self):
        q = {f.period_end: f for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter}
        self.assertEqual([q[date(2025, m, d)].value for m, d in ((3, 31), (6, 30), (9, 30))], [100, 110, 120])
        q4 = q[date(2025, 12, 31)]
        self.assertEqual(q4.value, 120)                                        # 450 - 330 (and 450 - 100 - 110 - 120)
        self.assertEqual((q4.period_start, q4.quarter, q4.financial_year), (date(2025, 10, 1), 4, 2025))
        self.assertEqual(q4.mapping_confidence.value, "derived")
        self.assertIn("12M year-to-date less 9M", q4.mapping_reason)
        self.assertEqual(q[date(2025, 3, 31)].mapping_confidence.value, "exact")

    def test_cash_flow_reported_only_year_to_date_becomes_single_quarters(self):
        q = {f.quarter: f for f in self.repos.facts.list_facts(1, metric="operating_cash_flow") if f.quarter}
        self.assertEqual([q[n].value for n in (1, 2, 3, 4)], [20, 25, 30, 35])            # 20, 45-20, 75-45, 110-75
        self.assertEqual((q[2].period_start, q[2].period_end), (date(2025, 4, 1), date(2025, 6, 30)))
        self.assertEqual(q[1].mapping_confidence.value, "exact")
        self.assertEqual(q[3].mapping_confidence.value, "derived")

    def test_per_share_figures_are_never_derived(self):
        eps = self.repos.facts.list_facts(1, metric="eps_basic")
        self.assertEqual(sorted(f.value for f in eps if f.quarter), [D("0.18"), D("0.20"), D("0.22")])
        self.assertFalse(any(f.quarter == 4 for f in eps))                    # EPS is not additive

    def test_the_report_counts_the_quarters_it_had_to_derive(self):
        # revenue Q4; net profit Q4 and net-profit-to-owners Q4 (one concept feeds both); cash flow Q2, Q3, Q4
        self.assertEqual(self.report.derived_quarters, 6)

    def test_a_restated_figure_is_kept_as_a_second_version_dated_by_its_filing(self):
        fy = [f for f in self.repos.facts.list_facts(1, metric="net_profit") if f.is_annual]
        self.assertEqual([(f.value, f.reported_at) for f in fy],
                         [(80, date(2026, 2, 20)), (78, date(2027, 2, 19))])

    def test_an_identical_repeat_in_a_later_filing_is_not_a_second_version(self):
        fy = [f for f in self.repos.facts.list_facts(1, metric="revenue") if f.is_annual]
        self.assertEqual([(f.value, f.reported_at) for f in fy], [(450, date(2026, 2, 20))])

    def test_the_derived_fourth_quarter_has_a_version_for_each_filing_of_its_year(self):
        q4 = [f for f in self.repos.facts.list_facts(1, metric="net_profit") if f.quarter == 4]
        # 80 - 60 when the year was first filed, 78 - 60 once it was restated
        self.assertEqual([(f.value, f.reported_at) for f in q4], [(20, date(2026, 2, 20)), (18, date(2027, 2, 19))])

    def test_forms_other_than_financial_statements_are_ignored(self):
        self.assertFalse(any(f.value == 999 for f in self.repos.facts.list_facts(1)))
        self.assertNotIn(A8, {self.repos.sources.get(f.source_id).document_title.split()[-1]
                              for f in self.repos.facts.list_facts(1) if f.source_id})

    def test_balance_sheet_items_are_instants_and_shares_come_from_the_cover_page(self):
        assets = {f.period_end: f for f in self.repos.facts.list_facts(1, metric="total_assets")}
        self.assertEqual(sorted(a.value for a in assets.values()), [950, 1000, 1050])
        self.assertTrue(all(a.is_point_in_time and a.period_start is None for a in assets.values()))
        shares = self.repos.facts.list_facts(1, metric="shares_outstanding")[0]
        self.assertEqual((shares.value, shares.period_end, shares.currency), (1000000, date(2026, 2, 10), None))


class TestTagChoice(Base):
    def test_the_first_candidate_wins_per_period_and_a_lower_one_is_flagged(self):
        self.load()
        rev = {f.period_end: f for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter}
        self.assertEqual(rev[date(2025, 3, 31)].mapping_confidence.value, "exact")      # Revenues
        q1_26 = rev[date(2026, 3, 31)]
        self.assertEqual(q1_26.value, 130)
        self.assertEqual(q1_26.mapping_confidence.value, "alternate_tag")
        self.assertIn("RevenueFromContractWithCustomerExcludingAssessedTax", q1_26.mapping_reason)
        self.assertIn("better-ranked concept (Revenues)", q1_26.mapping_reason)

    def test_a_filers_only_concept_is_not_called_an_alternate(self):
        # NetIncomeLoss is second choice for net profit, but this filer never reports ProfitLoss at all
        self.load()
        for f in self.repos.facts.list_facts(1, metric="net_profit"):
            self.assertEqual((f.mapping_confidence.value == "alternate_tag", f.mapping_reason is None
                              or "derived" in f.mapping_reason), (False, True), f.period_end)

    def test_non_operating_interest_is_read_but_parent_only_oci_is_not(self):
        # Microsoft files interest under InterestExpenseNonoperating. Its OCI is parent-only, which
        # would mix bases with net profit for a filer that has minorities, so oci stays absent.
        self.load(document({"InterestExpenseNonoperating": concept("USD", e(*FY, 40, A4)),
                            "OtherComprehensiveIncomeLossNetOfTaxPortionAttributableToParent":
                                concept("USD", e(*FY, -7, A4))}))
        self.assertEqual([f.value for f in self.repos.facts.list_facts(1, metric="finance_costs")], [40])
        self.assertEqual(self.repos.facts.list_facts(1, metric="oci"), [])

    def test_a_start_date_that_differs_by_a_day_between_filings_is_one_period(self):
        # a recast filing gives the same quarter a start of 2 July where the original said 1 July
        q = ("2016-07-01", "2016-09-30")
        jitter = ("2016-07-02", "2016-09-30")
        self.load(document({"Revenues": concept("USD", e(*q, 20453, A1), e(*jitter, 21928, A9))}))
        facts = self.repos.facts.list_facts(1, metric="revenue")
        self.assertEqual(len({(f.period_start, f.period_end) for f in facts}), 1)
        self.assertEqual([(f.value, f.reported_at) for f in facts],
                         [(20453, date(2025, 5, 2)), (21928, date(2027, 2, 19))])      # original, then recast
        self.assertEqual(FinancialEngine(self.repos).get_metric("Synthco Inc", "revenue").value, 21928)

    def test_genuinely_different_periods_ending_on_the_same_day_stay_apart(self):
        self.load(document({"Revenues": concept("USD", e("2025-01-01", "2025-03-31", 100, A1),
                                                 e("2025-02-01", "2025-03-31", 60, A1))}))   # 3 months and 2 months
        self.assertEqual(len(self.repos.facts.list_facts(1, metric="revenue")), 1)         # only the quarter is kept

    def _split_concepts(self, second_year_value):
        # the year under Revenues; the quarters and 9 months (and a year) under RevenuesNetOfInterestExpense
        net = [e(*Q1, 100, A1), e(*Q2, 110, A2), e(*Q3, 120, A3), e(*N9, 330, A3), e(*FY, second_year_value, A4)]
        self.load(document({"Revenues": concept("USD", e(*FY, 450, A4)),
                            "RevenuesNetOfInterestExpense": concept("USD", *net)}))
        return {f.quarter: f.value for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter}

    def test_two_concepts_that_agree_wherever_they_overlap_are_one_series_for_deriving_q4(self):
        self.assertEqual(self._split_concepts(450), {1: 100, 2: 110, 3: 120, 4: 120})     # 450 - 330, across concepts

    def test_a_recast_in_another_filing_is_not_mistaken_for_a_different_definition(self):
        # in 2014 the filer reported Q1 under Revenues (22,993); a 2015 filing recast it under the other concept
        # (23,215). That is two vintages, not two definitions, so it must not stop the equivalence.
        net = [e(*Q1, 100, A1), e(*Q2, 110, A2), e(*Q3, 120, A3), e(*N9, 330, A3), e(*FY, 450, A4)]
        self.load(document({
            "Revenues": concept("USD", e(*FY, 450, A4), e("2014-01-01", "2014-03-31", 22993, A1)),
            "RevenuesNetOfInterestExpense": concept("USD", *net, e("2014-01-01", "2014-03-31", 23215, A9))}))
        got = {f.quarter: f.value for f in self.repos.facts.list_facts(1, metric="revenue")
               if f.quarter and f.period_end.year == 2025}
        self.assertEqual(got, {1: 100, 2: 110, 3: 120, 4: 120})

    def test_two_concepts_that_disagree_are_never_mixed_to_derive_a_quarter(self):
        quarters = self._split_concepts(460)                  # same year, a different number: not the same quantity
        self.assertEqual(quarters, {1: 100, 2: 110, 3: 120})                              # no invented Q4

    def test_banks_quarterly_net_revenue_concept_is_recognised(self):
        q = {f"2025-{m:02d}-01": f"2025-{m + 2:02d}-{d}" for m, d in ((1, "31"), (4, "30"), (7, "30"))}
        entries = [e(s, end, v, a) for (s, end), v, a in zip(q.items(), (100, 110, 120), (A1, A2, A3), strict=True)]
        entries += [e(*FY, 450, A4)]
        self.load(document({"RevenuesNetOfInterestExpense": concept("USD", *entries)}))
        got = {f.quarter: f.value for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter}
        # three reported quarters, and the fourth derived as the year less those three (450 - 330)
        self.assertEqual(got, {1: 100, 2: 110, 3: 120, 4: 120})

    def test_a_concept_in_the_wrong_kind_of_unit_is_skipped_not_coerced(self):
        self.load(document({"Revenues": concept("shares", e(*FY, 450, A4))}))
        self.assertEqual(self.repos.facts.list_facts(1, metric="revenue"), [])

    def test_a_fact_with_a_dimension_is_ignored(self):
        self.load(document({"Revenues": concept("USD", e(*FY, 450, A4), e(*FY, 70, A4, dimensions={"x": "y"}))}))
        self.assertEqual([f.value for f in self.repos.facts.list_facts(1, metric="revenue")], [450])

    def test_us_gaap_has_no_exceptional_items_so_pre_tax_income_stands_in(self):
        self.load()
        pbe = self.repos.facts.list_facts(1, metric="pbt_before_exceptional")[0]
        self.assertEqual(pbe.value, 100)
        self.assertEqual(pbe.mapping_confidence.value, "derived")


class TestEntityAndProvenance(Base):
    def test_a_new_entity_gets_its_cik_currency_and_inferred_fiscal_year_end(self):
        self.load(ticker="SYN")
        ent = self.repos.entities.resolve("0001234567")
        self.assertEqual((ent.name, ent.currency, ent.fiscal_year_end_month), ("Synthco Inc", "USD", 12))
        self.assertEqual(ent.identifiers, {"cik": "0001234567", "ticker": "SYN"})
        self.assertEqual(self.repos.entities.resolve("syn").id, ent.id)

    def test_every_fact_traces_to_its_filing(self):
        self.load()
        q4 = next(f for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter == 4)
        src = self.repos.sources.get(q4.source_id)
        self.assertEqual((src.kind, src.document_title), ("sec-filing", f"10-K {A4}"))    # the later of FY and 9M
        self.assertEqual(src.uri, f"https://www.sec.gov/Archives/edgar/data/1234567/{A4.replace('-', '')}/")
        self.assertEqual(self.report.filings, 6)

    def test_loading_the_same_document_twice_changes_nothing(self):
        self.load()
        def counts():
            return (len(self.repos.facts.list_facts(1)),
                    self.repos.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        before = counts()
        sec.load_companyfacts(self.repos, document(US, DEI))
        self.assertEqual(counts(), before)

    def test_a_september_year_end_is_inferred_from_52_week_years(self):
        fy = ("2024-09-29", "2025-09-27")                       # 52 weeks, ends on a Saturday
        q1 = ("2024-09-29", "2024-12-28")
        self.load(document({"Revenues": concept("USD", e(*fy, 400, A4), e(*q1, 100, A1))}))
        ent = self.repos.entities.get(1)
        self.assertEqual(ent.fiscal_year_end_month, 9)
        q = next(f for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter)
        self.assertEqual((q.quarter, q.financial_year), (1, 2025))

    def test_a_filer_reporting_in_another_currency(self):
        self.load(document({"Revenues": concept("EUR", e(*FY, 450, A4))}))
        self.assertEqual(self.repos.entities.get(1).currency, "EUR")
        self.assertEqual(self.repos.facts.list_facts(1, metric="revenue")[0].currency, "EUR")

    def test_a_document_that_is_not_companyfacts_is_rejected(self):
        with self.assertRaises(ValueError):
            sec.parse_companyfacts({"facts": {}})


class TestWithTheEngine(Base):
    def setUp(self):
        self.load()
        self.eng = FinancialEngine(self.repos)

    def test_periods_are_labelled_on_the_inferred_calendar(self):
        self.assertEqual(self.eng.periods("Synthco Inc"),
                         ["FY2025 Q1", "FY2025 Q2", "FY2025 Q3", "FY2025", "FY2025 Q4",
                          "as of 2026-02-10", "FY2026 Q1"])        # the cover-page share count is its own date

    def test_the_four_quarters_add_up_to_the_year(self):
        # revenue 100 + 110 + 120 + 120 = 450 and net profit 18 + 20 + 22 + 18 = 78 (the restated year)
        self.assertEqual(self.eng.get_ratio("Synthco Inc", "revenue_ttm", period="FY2025Q4").value, 450)
        self.assertEqual(self.eng.get_ratio("Synthco Inc", "net_profit_ttm", period="FY2025Q4").value, 78)
        self.assertEqual(self.eng.get_metric("Synthco Inc", "revenue", period="FY2025").value, 450)

    def test_cash_flow_quarters_also_add_up_to_the_reported_year(self):
        facts = self.repos.facts.list_facts(1, metric="operating_cash_flow")
        self.assertEqual(sum(f.value for f in facts if f.quarter), 110)
        self.assertEqual(next(f.value for f in facts if f.is_annual), 110)

    def test_ratios_use_the_latest_restated_figure(self):
        r = self.eng.get_ratio("Synthco Inc", "roe", period="FY2025")        # 78 / 400, not 80 / 400
        self.assertEqual(r.value, D("19.5"))
        self.assertTrue(any(i.metric == "net_profit" and i.value == 78 for i in r.inputs))

    def test_latest_is_the_newest_period_not_the_newest_one_that_happens_to_compute(self):
        # FY2026 Q1 has revenue and assets but no net profit, so ROE cannot be computed there
        r = self.eng.get_ratio("Synthco Inc", "roe")
        self.assertIsNone(r.value)
        self.assertIn("net_profit not reported [FY2026 Q1]", r.limitations[0])

    def test_fallback_says_which_period_was_used_instead(self):
        r = self.eng.get_ratio("Synthco Inc", "roe", fallback=True)
        self.assertEqual((r.period, r.value), ("FY2025 Q4", D("4.5")))          # 18 / 400
        self.assertIn("could not be computed for FY2026 Q1", r.limitations[0])
        self.assertIn("FY2025 Q4", r.limitations[0])

    def test_a_derived_quarter_is_a_note_not_a_review_flag(self):
        r = self.eng.get_ratio("Synthco Inc", "roe", period="FY2025Q4")
        self.assertTrue(any("net_profit: " in t and "12M year-to-date less 9M" in t for t in r.limitations))
        self.assertFalse(any("flagged for review" in t for t in r.limitations))

    def test_inputs_first_reported_in_different_filings_are_called_out(self):
        # FY2025 profit was restated in the 2027 10-K, the FY2025 equity is from the 2026 10-K
        r = self.eng.get_ratio("Synthco Inc", "roe", period="FY2025")
        self.assertEqual({i.metric: i.reported_at for i in r.inputs},
                         {"net_profit": date(2027, 2, 19), "total_equity": date(2026, 2, 20)})
        self.assertTrue(any("different filings: total_equity reported 2026-02-20, net_profit reported 2027-02-19" in t
                            for t in r.limitations))
        q1 = self.eng.get_ratio("Synthco Inc", "asset_turnover", period="FY2026Q1")
        self.assertFalse(any("different filings" in t for t in q1.limitations))


class TestAsOf(Base):
    """The synthetic filer restates FY2025 net profit from 80 to 78 in the 10-K filed 2027-02-19."""

    def setUp(self):
        self.load()
        self.eng = FinancialEngine(self.repos)
        self.before, self.after = self.eng.as_of("2026-06-30"), self.eng.as_of(date(2027, 3, 1))

    def test_a_view_before_the_restatement_shows_the_original_figure(self):
        r = self.before.get_ratio("Synthco Inc", "roe", period="FY2025")
        self.assertEqual((r.value, r.as_of), (D("20"), date(2026, 6, 30)))               # 80 / 400
        self.assertEqual(self.after.get_ratio("Synthco Inc", "roe", period="FY2025").value, D("19.5"))   # 78 / 400
        self.assertIsNone(self.eng.get_ratio("Synthco Inc", "roe", period="FY2025").as_of)

    def test_a_trailing_year_is_still_there_between_a_filing_and_its_restatement(self):
        # the fourth quarter is derived from the year, so it has to exist in both versions of the year
        self.assertEqual(self.before.get_ratio("Synthco Inc", "net_profit_ttm", period="FY2025Q4").value, 80)
        self.assertEqual(self.after.get_ratio("Synthco Inc", "net_profit_ttm", period="FY2025Q4").value, 78)

    def test_later_periods_are_not_visible(self):
        self.assertEqual(self.before.periods("Synthco Inc")[-1], "FY2026 Q1")        # filed 2026-05-01
        early = self.eng.as_of("2025-09-01")
        self.assertEqual(early.get_metric("Synthco Inc", "revenue").period, "FY2025 Q2")
        self.assertEqual(early.get_growth("Synthco Inc", "revenue", kind="qoq").value, D("10"))

    def test_before_any_filing_nothing_is_known_and_it_says_so(self):
        r = self.eng.as_of("2025-01-01").get_metric("Synthco Inc", "revenue")
        self.assertIsNone(r.value)
        self.assertIn("facts reported later are left out of this view", r.limitations[-1])
        # a figure that is missing for another reason is not blamed on the date
        again = self.eng.as_of("2027-06-01").get_metric("Synthco Inc", "no_such_metric")
        self.assertFalse(any("left out of this view" in t for t in again.limitations))

    def test_many_views_read_the_store_once(self):
        from unittest import mock
        with mock.patch.object(self.repos.facts, "list_facts", wraps=self.repos.facts.list_facts) as spy:
            for day in ("2025-09-01", "2026-03-01", "2026-09-01", "2027-03-01"):
                view = self.eng.as_of(day)
                view.get_metric("Synthco Inc", "revenue")
                view.get_metric("Synthco Inc", "no_such_metric")             # may ask whether later facts exist
        self.assertEqual(spy.call_count, 1)

    def test_a_bad_date_is_an_error(self):
        for bad in ("last tuesday", 20260630, None):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.eng.as_of(bad)


class TestRecastQuarter(Base):
    """A fourth quarter derived from the year, which a later filing reports itself with a start a day later."""

    def test_the_derived_and_the_reported_quarter_are_versions_of_one_period(self):
        q4_own = ("2025-10-02", "2025-12-31")
        us = {"Revenues": concept("USD", e(*Q1, 100, A1), e(*H1, 210, A2), e(*N9, 330, A3), e(*FY, 450, A4),
                                  e(*q4_own, 121, A9))}
        self.load(document(us))
        q4 = [f for f in self.repos.facts.list_facts(1, metric="revenue") if f.quarter == 4]
        self.assertEqual({(f.period_start, f.period_end) for f in q4}, {(date(2025, 10, 2), date(2025, 12, 31))})
        self.assertEqual([(f.value, f.reported_at) for f in q4], [(120, date(2026, 2, 20)), (121, date(2027, 2, 19))])
        self.assertEqual(FinancialEngine(self.repos).periods("Synthco Inc").count("FY2025 Q4"), 1)


class TestUsBank(Base):
    """The concepts a large US bank files under; 650 - 250 = 400 net interest income."""

    def setUp(self):
        us = {"InterestIncomeOperating": concept("USD", e(*FY, 650, A4)),
              "InterestExpense": concept("USD", e(*FY, 250, A4)),
              "Deposits": concept("USD", e(None, "2025-12-31", 6000, A4)),
              "NoninterestExpense": concept("USD", e(*FY, 300, A4)),            # what marks a filer as a bank
              "FinancingReceivableExcludingAccruedInterestBeforeAllowanceForCreditLoss":
                  concept("USD", e(None, "2025-12-31", 4500, A4)),
              "ProvisionForLoanLeaseAndOtherLosses": concept("USD", e(*FY, 45, A4)),
              "LaborAndRelatedExpense": concept("USD", e(*FY, 120, A4)),
              "StockholdersEquity": concept("USD", e(None, "2025-12-31", 400, A4)),
              "Assets": concept("USD", e(None, "2025-12-31", 8000, A4)),
              "Revenues": concept("USD", e(*FY, 700, A4)),
              "NetIncomeLoss": concept("USD", e(*FY, 80, A4))}
        self.load(document(us))
        self.eng = FinancialEngine(self.repos)

    def test_bank_lines_are_mapped(self):
        got = {f.metric: f.value for f in self.repos.facts.list_facts(1) if f.metric.startswith("bank.")}
        self.assertEqual(got, {"bank.interest_earned": 650, "bank.interest_expended": 250, "bank.deposits": 6000,
                               "bank.gross_advances": 4500, "bank.provisions": 45, "bank.employee_cost": 120})

    def test_the_bank_ratios_work_and_the_generic_ones_are_held_back(self):
        self.assertEqual(self.eng.get_ratio("Synthco Inc", "bank.net_interest_income", period="FY2025").value, 400)
        self.assertEqual(self.eng.get_ratio("Synthco Inc", "bank.loan_to_deposit", period="FY2025").value, 75)
        self.assertEqual(self.eng.get_ratio("Synthco Inc", "roe", period="FY2025").value, 20)
        held = self.eng.get_ratio("Synthco Inc", "debt_to_equity", period="FY2025")
        self.assertIsNone(held.value)
        self.assertIn("does not apply to a bank", held.limitations[0])


class TestUsInsurer(Base):
    """The concepts a US property and casualty insurer files under; no total underwriting expense exists."""

    US = {"PremiumsEarnedNet": concept("USD", e(*FY, 1000, A4)),
          "PolicyholderBenefitsAndClaimsIncurredNet": concept("USD", e(*FY, 640, A4)),
          "NetInvestmentIncome": concept("USD", e(*FY, 90, A4)),
          "DeferredPolicyAcquisitionCostAmortizationExpense": concept("USD", e(*FY, 150, A4)),
          "StockholdersEquity": concept("USD", e(None, "2025-12-31", 800, A4)),
          "NetIncomeLoss": concept("USD", e(*FY, 120, A4))}

    def test_the_report_counts_only_quarters_that_are_stored(self):
        # the total benefits and expenses series derives three quarters, but it is only an input
        us = {**self.US, "BenefitsLossesAndExpenses": concept("USD", e(*Q1, 200, A1), e(*H1, 420, A2),
                                                              e(*N9, 650, A3), e(*FY, 900, A4))}
        self.load(document(us))
        self.assertEqual(self.report.derived_quarters, 0)

    def test_premium_claims_and_investment_income_are_mapped_and_the_loss_ratio_works(self):
        self.load(document(self.US))
        got = {f.metric: f.value for f in self.repos.facts.list_facts(1) if f.metric.startswith("insurance.")}
        self.assertEqual(got, {"insurance.net_earned_premium": 1000, "insurance.claims_incurred": 640,
                               "insurance.net_investment_income": 90})
        eng = FinancialEngine(self.repos)
        self.assertEqual(eng.get_ratio("Synthco Inc", "insurance.loss_ratio", period="FY2025").value, 64)
        held = eng.get_ratio("Synthco Inc", "quick_ratio", period="FY2025")
        self.assertIn("does not apply to an insurer", held.limitations[0])

    def test_underwriting_expenses_are_total_costs_less_claims_and_say_so(self):
        us = {**self.US, "BenefitsLossesAndExpenses": concept("USD", e(*FY, 900, A4))}
        self.load(document(us))
        eng = FinancialEngine(self.repos)
        r = eng.get_ratio("Synthco Inc", "insurance.combined_ratio", period="FY2025")
        self.assertEqual(r.value, 90)                                   # (900 - 640) / 1000 + 640 / 1000
        self.assertTrue(any("total benefits, losses and expenses less claims" in t for t in r.limitations))
        self.assertEqual({i.metric for i in r.inputs},
                         {"insurance.claims_incurred", "insurance.net_earned_premium",
                          "insurance.underwriting_expenses"})

    def test_the_derived_expenses_follow_a_restatement_of_either_part(self):
        us = {**self.US, "BenefitsLossesAndExpenses": concept("USD", e(*FY, 900, A4), e(*FY, 880, A9)),
              "PolicyholderBenefitsAndClaimsIncurredNet": concept("USD", e(*FY, 640, A4), e(*FY, 650, A9))}
        self.load(document(us))
        facts = self.repos.facts.list_facts(1, metric="insurance.underwriting_expenses")
        got = [(f.value, f.reported_at) for f in facts]
        self.assertEqual(got, [(260, date(2026, 2, 20)), (230, date(2027, 2, 19))])

    def test_without_a_total_the_expense_ratios_say_what_is_missing(self):
        self.load(document(self.US))
        eng = FinancialEngine(self.repos)
        for name in ("insurance.expense_ratio", "insurance.combined_ratio"):
            r = eng.get_ratio("Synthco Inc", name, period="FY2025")
            self.assertIsNone(r.value)
            self.assertIn("underwriting_expenses not reported", r.limitations[0])

    def test_a_property_casualty_only_premium_concept_counts(self):
        us = {**self.US, "PremiumsEarnedNetPropertyAndCasualty": concept("USD", e(*FY, 1000, A4))}
        del us["PremiumsEarnedNet"]
        self.load(document(us))
        self.assertEqual(self.facts("insurance.net_earned_premium", period_end=date(2025, 12, 31))
                         [(date(2025, 1, 1), date(2025, 12, 31), date(2026, 2, 20))].value, 1000)

    def test_a_manufacturer_with_a_captive_insurer_is_not_an_insurer(self):
        # premiums are 30 of 1000 revenue: tagged, but not the business
        us = {**self.US, "Revenues": concept("USD", e(*FY, 1000, A4)),
              "PremiumsEarnedNet": concept("USD", e(*FY, 30, A4))}
        self.load(document(us))
        self.assertFalse(any(f.metric.startswith("insurance.") for f in self.repos.facts.list_facts(1)))
        self.assertIsNone(FinancialEngine(self.repos)._sector(self.repos.entities.get(1), []))

    def test_an_insurer_whose_premiums_are_most_of_its_revenue_is_one(self):
        us = {**self.US, "Revenues": concept("USD", e(*FY, 1250, A4))}                   # premiums 1000 of 1250
        self.load(document(us))
        self.assertTrue(any(f.metric == "insurance.net_earned_premium" for f in self.repos.facts.list_facts(1)))

    def test_net_investment_income_without_premiums_is_not_an_insurers(self):
        # a fund or a business development company files NetInvestmentIncome too
        self.load(document({"NetInvestmentIncome": concept("USD", e(*FY, 90, A4)),
                            "BenefitsLossesAndExpenses": concept("USD", e(*FY, 900, A4))}))
        self.assertFalse(any(f.metric.startswith("insurance.") or f.metric.startswith("_")
                             for f in self.repos.facts.list_facts(1)))

    def test_a_bank_that_also_files_premiums_is_not_an_insurer(self):
        # Citigroup-style: an insurance arm's premiums beside the bank concepts
        us = {**self.US, "NoninterestExpense": concept("USD", e(*FY, 300, A4)),
              "Deposits": concept("USD", e(None, "2025-12-31", 6000, A4))}
        self.load(document(us))
        self.assertFalse(any(f.metric.startswith("insurance.") for f in self.repos.facts.list_facts(1)))


class TestIfrsFiler(Base):
    """A 20-F filer: IFRS concepts, annual statements in its own currency, quarters from a 6-K."""

    IFRS = {"Revenue": concept("EUR", e(*FY, 450, A10), e(*Q1, 100, A11)),
            "ProfitLoss": concept("EUR", e(*FY, 80, A10), e(*Q1, 18, A11)),
            "ProfitLossAttributableToOwnersOfParent": concept("EUR", e(*FY, 78, A10)),
            "Equity": concept("EUR", e(None, "2025-12-31", 400, A10)),
            "Assets": concept("EUR", e(None, "2025-12-31", 1000, A10)),
            "BasicEarningsLossPerShare": concept("EUR/shares", e(*FY, D("0.78"), A10)),
            # trade AND other receivables are not trade receivables, and lease liabilities are not debt
            "TradeAndOtherCurrentReceivables": concept("EUR", e(None, "2025-12-31", 90, A10)),
            "LeaseLiabilities": concept("EUR", e(None, "2025-12-31", 60, A10))}

    def test_ifrs_concepts_are_mapped_in_the_filers_currency(self):
        self.load(document(ifrs=self.IFRS))
        self.assertEqual(self.repos.entities.get(1).currency, "EUR")
        got = {f.metric: f.value for f in self.repos.facts.list_facts(1) if f.period_end == date(2025, 12, 31)}
        self.assertEqual(got["revenue"], 450)
        self.assertEqual(got["net_profit_owners"], 78)
        self.assertEqual((got["total_equity"], got["eps_basic"]), (400, D("0.78")))
        self.assertEqual(self.report.notes, ())

    def test_only_clean_concepts_are_read(self):
        self.load(document(ifrs=self.IFRS))
        metrics = {f.metric for f in self.repos.facts.list_facts(1)}
        self.assertFalse(metrics & {"trade_receivables", "borrowings_current", "borrowings_noncurrent"})

    def test_a_6k_quarter_sits_beside_the_20f_year(self):
        self.load(document(ifrs=self.IFRS))
        q1 = self.facts("revenue", period_start=date(2025, 1, 1), period_end=date(2025, 3, 31))
        self.assertEqual([(f.value, f.quarter) for f in q1.values()], [(100, 1)])
        self.assertEqual(self.report.fiscal_year_end_month, 12)

    def test_ratios_work_for_an_annual_only_filer(self):
        self.load(document(ifrs=self.IFRS))
        eng = FinancialEngine(self.repos)
        self.assertEqual(eng.get_ratio("Synthco Inc", "roe", period="FY2025").value, D("20"))        # 80 / 400
        self.assertEqual(eng.get_ratio("Synthco Inc", "revenue_ttm").value, 450)

    def test_continuing_operations_eps_is_not_taken_for_eps(self):
        ifrs = {k: v for k, v in self.IFRS.items() if k != "BasicEarningsLossPerShare"}
        ifrs["BasicEarningsLossPerShareFromContinuingOperations"] = concept("EUR/shares", e(*FY, D("0.9"), A10))
        self.load(document(ifrs=ifrs))
        self.assertFalse(any(f.metric == "eps_basic" for f in self.repos.facts.list_facts(1)))

    def test_a_6k_that_repeats_the_20f_year_still_fixes_a_non_december_year_end(self):
        # a March year reported first in a 6-K earnings release, then identically in the 20-F
        y25, y24 = ("2024-04-01", "2025-03-31"), ("2023-04-01", "2024-03-31")
        ifrs = {"Revenue": concept("EUR", e(*y25, 450, A11), e(*y25, 450, A10), e(*y24, 400, A11), e(*y24, 400, A10))}
        self.load(document(ifrs=ifrs))
        self.assertEqual(self.report.fiscal_year_end_month, 3)
        self.assertFalse(any("no full-year" in n for n in self.report.notes))

    def test_an_ifrs_bank_is_declared_a_bank_and_its_interest_is_not_a_finance_cost(self):
        ifrs = {**self.IFRS, "DepositsFromBanks": concept("EUR", e(None, "2025-12-31", 300, A10)),
                "InterestExpense": concept("EUR", e(*FY, 120, A10))}
        self.load(document(ifrs=ifrs))
        self.assertEqual(self.repos.entities.get(1).sector, "bank")
        self.assertNotIn("finance_costs", {f.metric for f in self.repos.facts.list_facts(1)})
        self.assertTrue(any("IFRS bank" in n for n in self.report.notes))
        held = FinancialEngine(self.repos).get_ratio("Synthco Inc", "interest_coverage", period="FY2025")
        self.assertIsNone(held.value)

    def test_an_ifrs_17_insurer_is_named_not_mismapped(self):
        self.load(document(ifrs={**self.IFRS, "InsuranceRevenue": concept("EUR", e(*FY, 300, A10))}))
        self.assertFalse(any(f.metric.startswith("insurance.") for f in self.repos.facts.list_facts(1)))
        self.assertTrue(any("IFRS 17" in n for n in self.report.notes))


class TestRealFilerShapes(Base):
    def test_a_non_bank_with_deposits_and_interest_lines_gets_no_bank_metrics(self):
        # an insurer or industrial files Deposits and InterestExpense too, but no NoninterestExpense
        self.load(document({"Deposits": concept("USD", e(None, "2025-12-31", 6000, A4)),
                            "InterestExpense": concept("USD", e(*FY, 250, A4)),
                            "InterestIncomeOperating": concept("USD", e(*FY, 650, A4))}))
        metrics = {f.metric for f in self.repos.facts.list_facts(1)}
        self.assertEqual(metrics, {"finance_costs"})

    def test_twelve_months_reported_in_a_10q_is_not_a_fiscal_year(self):
        # Amazon-style: every 10-Q also gives a trailing-twelve-month figure
        ttm = ("2024-10-01", "2025-09-30")
        self.load(document({"Revenues": concept("USD", e(*FY, 450, A4), e(*ttm, 999, A3), e(*Q3, 120, A3))}))
        spans = {(f.period_start, f.period_end) for f in self.repos.facts.list_facts(1, metric="revenue")}
        self.assertNotIn((date(2024, 10, 1), date(2025, 9, 30)), spans)
        self.assertIn((date(2025, 1, 1), date(2025, 12, 31)), spans)
        self.assertEqual(self.report.fiscal_year_end_month, 12)

    def test_a_52_53_week_year_ending_in_the_first_week_of_september_is_an_august_year(self):
        # Costco-style: years end on the Sunday nearest 31 August, so 3 Sep 2023 is FY2023
        y23, y24 = ("2022-08-29", "2023-09-03"), ("2023-09-04", "2024-09-01")
        self.load(document({"Revenues": concept("USD", e(*y23, 100, A1), e(*y24, 120, A4))}))
        self.assertEqual(self.report.fiscal_year_end_month, 8)
        eng = FinancialEngine(self.repos)
        self.assertEqual(eng.periods("Synthco Inc"), ["FY2023", "FY2024"])
        self.assertEqual(eng.get_metric("Synthco Inc", "revenue", period="FY2023").value, 100)

    def test_latest_skips_a_cover_page_date_that_carries_only_a_share_count(self):
        dei = {"EntityCommonStockSharesOutstanding": concept("shares", e(None, "2026-06-30", 1000000, A5))}
        self.load(document(US, dei))
        eng = FinancialEngine(self.repos)
        self.assertEqual(eng.periods("Synthco Inc")[-1], "as of 2026-06-30")
        r = eng.get_ratio("Synthco Inc", "equity_multiplier")                    # 1050 / 420
        self.assertEqual((r.period, r.value), ("FY2026 Q1", D("2.5")))


class TestFetch(unittest.TestCase):
    def setUp(self):
        fetch._last_request[0] = float("-inf")

    def opener(self, status=200, body=b"{}", headers=None, seen=None):
        def run(request):
            if seen is not None:
                seen.append(request)
            return status, headers or {}, body
        return run

    def test_a_contact_in_the_user_agent_is_required(self):
        for bad in ("", "python-urllib", "Jane Doe"):
            with self.assertRaises(ValueError, msg=bad):
                fetch.fetch_companyfacts(320193, bad, opener=self.opener())

    def test_the_request_is_the_documented_url_with_the_callers_user_agent(self):
        seen = []
        out = fetch.fetch_companyfacts("320193", "Jane Doe jane@example.com",
                                       opener=self.opener(body=b'{"a": 1}', seen=seen))
        self.assertEqual(out, b'{"a": 1}')
        self.assertEqual(seen[0].full_url, "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
        self.assertEqual(seen[0].get_header("User-agent"), "Jane Doe jane@example.com")

    def test_gzip_responses_are_decompressed(self):
        body = gzip.compress(b'{"a": 1}')
        out = fetch.fetch_companyfacts(1, "J jane@example.com", opener=self.opener(
            body=body, headers={"Content-Encoding": "gzip"}))
        self.assertEqual(out, b'{"a": 1}')

    def test_requests_are_spaced_under_the_sec_limit(self):
        clock = iter([100.0, 100.0, 100.05, 100.05]).__next__            # second call comes 0.05 s after the first
        slept = []
        for _ in range(2):
            fetch.fetch_companyfacts(1, "J j@example.com", opener=self.opener(), sleep=slept.append, clock=clock)
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], fetch.MIN_INTERVAL - 0.05, places=6)
        self.assertLessEqual(fetch.MIN_INTERVAL, 0.1 * 2)                # at most 5 per second

    def test_refusals_explain_themselves_and_are_not_retried(self):
        calls = []
        with self.assertRaises(fetch.SecFetchError) as ctx:
            fetch.fetch_companyfacts(1, "J j@example.com", opener=self.opener(status=429, seen=calls))
        self.assertIn("10 requests per second", str(ctx.exception))
        self.assertEqual(len(calls), 1)
        with self.assertRaises(fetch.SecFetchError) as ctx:
            fetch.fetch_companyfacts(1, "J j@example.com", opener=self.opener(status=404))
        self.assertIn("CIK 0000000001", str(ctx.exception))

    def test_bad_ciks_are_rejected_before_any_request(self):
        for bad in ("abc", 0, -5, 10**10):
            with self.assertRaises(ValueError, msg=str(bad)):
                fetch.fetch_companyfacts(bad, "J j@example.com", opener=self.opener())


class TestFiles(unittest.TestCase):
    def test_a_downloaded_file_is_read_with_exact_decimals_and_loaded(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "CIK0001234567.json"
        # json.dumps writes the float 0.1 as the text 0.1; reading it with parse_float=Decimal keeps it exact
        doc = document({"EarningsPerShareBasic": concept("USD/shares", e(*FY, 0.1, A4))})
        path.write_text(json.dumps(doc), encoding="utf-8")
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        sec.load_companyfacts_file(repos, path)
        self.assertEqual(repos.facts.list_facts(1, metric="eps_basic")[0].value, D("0.1"))


if __name__ == "__main__":
    unittest.main()
