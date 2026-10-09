"""Ind-AS adapter: XBRL file -> raw facts -> canonical records -> facts. All data here is
synthetic; none of it comes from an exchange."""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path

from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import ind_as_xbrl as ind
from calcfinc.adapters.ind_as_xbrl import canonical

XBRL = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:in-capmkt="http://example.test/in-capmkt"
            xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
  <xbrli:context id="OneD"><xbrli:entity><xbrli:identifier scheme="syn">SYN</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="OneI"><xbrli:entity><xbrli:identifier scheme="syn">SYN</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2025-06-30</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="OneReportable1D"><xbrli:entity><xbrli:identifier scheme="syn">SYN</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2025-04-01</xbrli:startDate><xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
  <in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5">1,000</in-capmkt:RevenueFromOperations>
  <in-capmkt:RevenueFromOperations contextRef="OneReportable1D" unitRef="INR">400</in-capmkt:RevenueFromOperations>
  <in-capmkt:OtherIncome contextRef="OneD" unitRef="INR">50</in-capmkt:OtherIncome>
  <in-capmkt:Income contextRef="OneD" unitRef="INR">1050</in-capmkt:Income>
  <in-capmkt:Expenses contextRef="OneD" unitRef="INR">800</in-capmkt:Expenses>
  <in-capmkt:ProfitBeforeExceptionalItemsAndTax contextRef="OneD" unitRef="INR">250</in-capmkt:ProfitBeforeExceptionalItemsAndTax>
  <in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">200</in-capmkt:ProfitLossForPeriod>
  <in-capmkt:OtherComprehensiveIncomeNetOfTaxes contextRef="OneD" unitRef="INR" sign="-">5</in-capmkt:OtherComprehensiveIncomeNetOfTaxes>
  <in-capmkt:PaidUpValueOfEquityShareCapital contextRef="OneD" unitRef="INR">500</in-capmkt:PaidUpValueOfEquityShareCapital>
  <in-capmkt:FaceValueOfEquityShareCapital contextRef="OneD" unitRef="INR">5</in-capmkt:FaceValueOfEquityShareCapital>
  <in-capmkt:Assets contextRef="OneI" unitRef="INR">5000</in-capmkt:Assets>
  <in-capmkt:Liabilities contextRef="OneI" unitRef="INR">3000</in-capmkt:Liabilities>
  <in-capmkt:Equity contextRef="OneI" unitRef="INR">2000</in-capmkt:Equity>
</xbrli:xbrl>
"""  # noqa: E501 (XML data)

# Some filers declare the period as plain facts and give the context no period of its own.
XBRL_SELF_DESCRIBED = """<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-bse-fin="http://example.test/in-bse-fin">
  <xbrli:context id="OneD"/>
  <in-bse-fin:DateOfEndOfReportingPeriod contextRef="OneD">2025-06-30</in-bse-fin:DateOfEndOfReportingPeriod>
  <in-bse-fin:DateOfStartOfFinancialYear contextRef="OneD">2025-04-01</in-bse-fin:DateOfStartOfFinancialYear>
  <in-bse-fin:ReportingQuarter contextRef="OneD">First quarter</in-bse-fin:ReportingQuarter>
  <in-bse-fin:RevenueFromOperations contextRef="OneD">700</in-bse-fin:RevenueFromOperations>
</xbrli:xbrl>
"""

DURATION = {
    "context_id": "OneD", "period_start": "2025-04-01", "period_end": "2025-06-30", "instant": None,
    "revenue": D("1000"), "other_income": D("50"), "total_income": D("1050"), "total_expenses": D("800"),
    "pbt_before_exceptional": D("250"), "exceptional_items": D("10"), "pbt": D("260"),
    "current_tax": D("50"), "deferred_tax": D("10"), "tax_expense": D("60"),
    "pat_continuing_ops": D("200"), "net_profit": D("200"), "oci": D("-5"),
    "total_comprehensive_income": D("195"), "paid_up_equity_capital": D("500"),
    "face_value_per_share": D("5"), "eps_basic": D("2"),
    "_missing_fields": ["total_assets"], "_validation": {}, "_needs_review": False,
}
INSTANT = {
    "context_id": "OneI", "period_start": None, "period_end": None, "instant": "2025-06-30",
    "total_assets": D("5000"), "total_liabilities": D("3000"), "total_equity": D("2000"),
    "current_assets": D("2500"), "noncurrent_assets": D("2500"),
    "current_liabilities": D("1500"), "noncurrent_liabilities": D("1500"),
}


class TestParseNumber(unittest.TestCase):
    def test_formats(self):
        p = canonical.parse_number
        self.assertEqual(p("59,553.00"), D("59553.00"))
        self.assertEqual(p("(1,234.5)"), D("-1234.5"))
        self.assertEqual(p("₹ 1,200"), D("1200"))
        self.assertEqual(p("1,234.5*"), D("1234.5"))
        self.assertEqual(p("1.5E+3"), D("1500"))
        self.assertEqual(p(1099800000.0), D("1099800000.0"))              # from JSON; the text is kept
        self.assertEqual(p(5), D("5"))

    def test_not_numbers(self):
        p = canonical.parse_number
        for bad in (None, "", "-", "NA", "N/A", "ADANIENT", "NaN", "Infinity", True, D("NaN")):
            self.assertIsNone(p(bad), repr(bad))


class TestRawFactMapping(unittest.TestCase):
    def row(self, tag, value, ctx="OneD", **kw):
        return {"line_item_tag": tag, "value": value, "context_id": ctx, "period_start": "2025-04-01",
                "period_end": "2025-06-30", "instant": None, "sign": None, **kw}

    def test_exact_tag_local_name_fallback_sign_and_context_filter(self):
        records = canonical.map_facts([
            self.row("in-capmkt:RevenueFromOperations", "1,000"),
            self.row("in-bse-fin:ProfitBeforeTax", "260"),                       # older prefix, same concept
            self.row("in-capmkt:OtherComprehensiveIncomeNetOfTaxes", "5", sign="-"),
            self.row("in-capmkt:RevenueFromOperations", "999", ctx="OneReportable1D"),   # segment context
            self.row("in-bse-fin:Symbol", "SYN"),                                 # untracked
        ])
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual((r["revenue"], r["pbt"], r["oci"]), (D("1000"), D("260"), D("-5")))
        self.assertNotIn("999", [str(v) for v in r.values()])

    def test_net_premium_income_is_the_insurer_marker(self):
        r = canonical.map_facts([self.row("in-capmkt:NetPremiumIncome", "259,984")])[0]
        self.assertEqual(r["insurance_net_premium"], D("259984"))

    def test_bank_totals_are_built_only_from_complete_parts(self):
        rows = [self.row("in-capmkt:Capital", "100"), self.row("in-capmkt:ReservesAndSurplus", "900"),
                self.row("in-capmkt:CashAndBalancesWithReserveBankOfIndia", "30"),
                self.row("in-capmkt:BalancesWithBanksAndMoneyAtCallAndShortNotice", "20"),
                self.row("in-capmkt:Deposits", "7000"), self.row("in-capmkt:Borrowings", "500"),
                self.row("in-capmkt:OtherLiabilitiesAndProvisions", "250")]
        r = canonical.map_facts(rows)[0]
        self.assertEqual(r["total_equity"], 1000)                             # 100 + 900
        self.assertEqual(r["cash_and_equivalents"], 50)                       # 30 + 20
        self.assertEqual(r["total_liabilities"], 7750)                        # 7000 + 500 + 250
        self.assertFalse(any(k.startswith("_bank") for k in r))
        partial = canonical.map_facts([self.row("in-capmkt:Capital", "100")])[0]
        self.assertNotIn("total_equity", partial)                             # reserves missing: no guess

    def test_a_reported_total_beats_the_derived_one(self):
        r = canonical.map_facts([self.row("in-capmkt:Equity", "1234"), self.row("in-capmkt:Capital", "100"),
                                 self.row("in-capmkt:ReservesAndSurplus", "900")])[0]
        self.assertEqual(r["total_equity"], 1234)

    def test_contexts_that_disagree_on_a_balance_are_reported(self):
        a = {"context_id": "OneI", "instant": "2025-06-30", "paid_up_equity_capital": D("29000000")}
        b = {"context_id": "FourI", "instant": "2025-06-30", "paid_up_equity_capital": D("296000000")}
        issues = canonical.consistency_issues([a, b])
        self.assertEqual(len(issues), 1)
        self.assertEqual((issues[0]["field"], issues[0]["severity"]), ("paid_up_equity_capital", "high"))
        self.assertEqual(issues[0]["magnitude_pct"], D("920.69"))             # 267,000,000 / 29,000,000
        same = dict(b, paid_up_equity_capital=D("29000000.5"))
        self.assertEqual(canonical.consistency_issues([a, same]), [])         # within rounding


class TestXbrlFile(unittest.TestCase):
    def tmp(self, text, name):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_rows_carry_prefixed_tags_periods_units_and_signs(self):
        rows = ind.parse_xbrl_file(self.tmp(XBRL, "x_consolidated_30-Jun-2025.xbrl"), "SYN")
        revenue = [r for r in rows if r["line_item_tag"] == "in-capmkt:RevenueFromOperations"]
        self.assertEqual({r["context_id"] for r in revenue}, {"OneD", "OneReportable1D"})
        main = next(r for r in revenue if r["context_id"] == "OneD")
        self.assertEqual((main["period_start"], main["period_end"], main["unit"], main["decimals"]),
                         ("2025-04-01", "2025-06-30", "iso4217:INR", "-5"))
        assets = next(r for r in rows if r["line_item_tag"] == "in-capmkt:Assets")
        self.assertEqual((assets["instant"], assets["period_start"]), ("2025-06-30", None))
        oci = next(r for r in rows if r["line_item_tag"].endswith("OtherComprehensiveIncomeNetOfTaxes"))
        self.assertEqual(oci["sign"], "-")

    def test_a_period_the_filing_declares_about_itself_is_recovered(self):
        rows = ind.parse_xbrl_file(self.tmp(XBRL_SELF_DESCRIBED, "y_standalone_30-Jun-2025.xbrl"))
        revenue = next(r for r in rows if r["line_item_tag"].endswith("RevenueFromOperations"))
        self.assertEqual((revenue["period_start"], revenue["period_end"]), ("2025-04-01", "2025-06-30"))

    def test_a_declared_period_with_day_and_month_swapped_loses_to_the_context(self):
        # a real filing declared 10 January and 4 January for 1 October and 1 April; its contexts were right
        text = XBRL_SELF_DESCRIBED.replace('<xbrli:context id="OneD"/>', (
            '<xbrli:context id="OneD"><xbrli:period><xbrli:startDate>2025-10-01</xbrli:startDate>'
            '<xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>')).replace(
            "2025-06-30", "2025-12-31").replace(
            "</xbrli:xbrl>", '<in-bse-fin:DateOfStartOfReportingPeriod contextRef="OneD">2025-01-10'
                             '</in-bse-fin:DateOfStartOfReportingPeriod></xbrli:xbrl>')
        rows = ind.parse_xbrl_file(self.tmp(text, "z_standalone_31-Dec-2025.xbrl"))
        revenue = next(r for r in rows if r["line_item_tag"].endswith("RevenueFromOperations"))
        self.assertEqual((revenue["period_start"], revenue["period_end"]), ("2025-10-01", "2025-12-31"))

    def test_a_filing_loads_end_to_end_with_the_indian_year_and_the_basis_from_its_name(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        report = ind.load_xbrl_file(repos, self.tmp(XBRL, "syn_Consolidated_30-Jun-2025.xbrl"), entity="SYN")
        self.assertEqual((report.entity, report.needs_review), ("SYN", ()))
        ent = repos.entities.resolve("SYN")
        self.assertEqual((ent.currency, ent.fiscal_year_end_month), ("INR", 3))
        eng = FinancialEngine(repos)
        self.assertEqual(eng.periods("SYN"), ["FY2026 Q1"])
        self.assertEqual(eng.get_metric("SYN", "revenue").value, 1000)        # not the segment's 400
        self.assertEqual(eng.get_metric("SYN", "oci").value, -5)              # sign="-" applied
        self.assertEqual(eng.get_ratio("SYN", "roe").value, 10)               # 100 x 200 / 2000
        self.assertEqual(eng.get_metric("SYN", "shares_outstanding").value, 100)   # 500 / 5
        src = eng.get_metric("SYN", "revenue").inputs[0].source_id
        self.assertTrue(repos.sources.get(src).content_hash)

    def test_a_revision_is_loaded_after_its_original_whatever_the_order_given(self):
        revised = XBRL.replace(">1,000<", ">900<").replace(">1050<", ">950<")
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        revision = self.tmp(revised, "syn_Revision_Consolidated_30-Jun-2025.xbrl")
        original = self.tmp(XBRL, "syn_Original_Consolidated_30-Jun-2025.xbrl")
        reports = ind.load_xbrl_files(repos, [revision, original], entity="SYN")          # revision listed first
        self.assertEqual(len(reports), 2)
        self.assertEqual(FinancialEngine(repos).get_metric("SYN", "revenue").value, 900)

    def test_the_basis_must_be_known(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        with self.assertRaises(ValueError):
            ind.load_xbrl_file(repos, self.tmp(XBRL, "mystery.xbrl"), entity="SYN")


class TestCanonicalRecords(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)

    def facts(self, **kw):
        return {f.metric: f for f in self.repos.facts.list_facts(1, **kw)}

    def test_periods_use_the_april_march_year_and_balance_items_are_instants(self):
        ind.load_canonical(self.repos, [DURATION, INSTANT], entity="SYN")
        f = self.facts()
        rev = f["revenue"]
        self.assertEqual((rev.period_start, rev.period_end, rev.financial_year, rev.quarter, rev.is_annual),
                         (date(2025, 4, 1), date(2025, 6, 30), 2026, 1, False))
        self.assertEqual(rev.currency, "INR")
        assets = f["total_assets"]
        self.assertEqual((assets.period_start, assets.is_point_in_time, assets.quarter, assets.financial_year),
                         (None, True, None, 2026))
        self.assertEqual(f["eps_basic"].currency, "INR")
        self.assertIsNone(f["debt_equity_ratio_reported"].currency if "debt_equity_ratio_reported" in f else None)

    def test_old_names_are_renamed_and_untracked_keys_ignored(self):
        rec = dict(DURATION, pat_continuing_ops=D("200"), bank_interest_earned=D("900"), advances=D("5000"),
                   mystery_field=D("1"))
        ind.load_canonical(self.repos, [rec], entity="SYN")
        f = self.facts()
        self.assertEqual(f["profit_continuing_ops"].value, 200)
        self.assertEqual(f["bank.interest_earned"].value, 900)
        self.assertEqual(f["bank.advances"].is_point_in_time, True)
        self.assertNotIn("pat_continuing_ops", f)
        self.assertNotIn("mystery_field", f)

    def test_a_merged_record_gives_the_same_facts_as_separate_ones(self):
        merged = dict(DURATION, **{k: v for k, v in INSTANT.items() if k not in
                                   ("context_id", "period_start", "period_end", "instant")})
        merged["context_id"] = "OneD+OneI"
        ind.load_canonical(self.repos, [merged], entity="A")
        ind.load_canonical(self.repos, [DURATION, INSTANT], entity="B")
        key = lambda f: (f.metric, str(f.value), f.period_start, f.period_end, f.is_point_in_time)  # noqa: E731
        a = sorted(key(f) for f in self.repos.facts.list_facts(1))
        b = sorted(key(f) for f in self.repos.facts.list_facts(2))
        self.assertEqual(a, b)

    def test_shares_are_derived_from_paid_up_capital_and_face_value_and_marked_as_derived(self):
        ind.load_canonical(self.repos, [DURATION], entity="SYN")
        shares = self.facts()["shares_outstanding"]
        self.assertEqual(shares.value, 100)
        self.assertTrue(shares.is_point_in_time)
        self.assertEqual(shares.mapping_confidence.value, "derived")
        self.assertIn("paid-up equity capital / face value", shares.mapping_reason)

    def test_a_record_that_fails_its_own_arithmetic_loads_but_is_flagged(self):
        bad = dict(DURATION, total_expenses=D("700"))                          # 1050 - 700 != 250
        report = ind.load_canonical(self.repos, [bad], entity="SYN")
        self.assertEqual(report.needs_review, ("2025-06-30",))
        reasons = {f.mapping_reason for f in self.repos.facts.list_facts(1)}
        self.assertEqual(len(reasons), 1)
        self.assertIn("income_minus_expenses_eq_pbt_before_exceptional", reasons.pop())
        good = ind.load_canonical(SqliteRepositories(":memory:"), [DURATION], entity="SYN")
        self.assertEqual(good.needs_review, ())

    def test_a_flow_figure_with_no_start_date_is_skipped_and_reported(self):
        only_instant = {"context_id": "OneI", "instant": "2025-06-30", "total_assets": D("5000"),
                        "net_profit": D("500")}
        report = ind.load_canonical(self.repos, [only_instant], entity="SYN")
        self.assertEqual(report.facts, 1)
        self.assertTrue(any("net_profit" in s for s in report.skipped))

    def test_an_existing_entity_keeps_its_own_calendar(self):
        from calcfinc import Entity
        self.repos.entities.upsert(Entity(name="SYN", currency="INR", fiscal_year_end_month=12))
        ind.load_canonical(self.repos, [DURATION], entity="SYN")
        self.assertEqual(self.facts()["revenue"].financial_year, 2025)         # December year end wins

    def test_restating_a_filing_keeps_both_versions(self):
        ind.load_canonical(self.repos, [DURATION], entity="SYN", reported_at=date(2025, 8, 1))
        ind.load_canonical(self.repos, [dict(DURATION, revenue=D("1100"), total_income=D("1150"),
                                             pbt_before_exceptional=D("350"), pbt=D("360"),
                                             pat_continuing_ops=D("300"), net_profit=D("300"),
                                             total_comprehensive_income=D("295"))],
                           entity="SYN", reported_at=date(2025, 11, 1))
        self.assertEqual(FinancialEngine(self.repos).get_metric("SYN", "revenue").value, 1100)
        versions = [f.value for f in self.repos.facts.list_facts(1, metric="revenue")]
        self.assertEqual(versions, [1000, 1100])

    def test_canonical_json_files_load_by_name_with_exact_numbers(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = Path(d.name) / "SYN_standalone_30-Jun-2025_canonical.json"
        path.write_text('[{"context_id": "OneD", "period_start": "2025-04-01", "period_end": "2025-06-30", '
                        '"instant": null, "revenue": 105613700000.0, "eps_basic": 5.47}]', encoding="utf-8")
        report = ind.load_canonical_file(self.repos, path)
        self.assertEqual((report.entity, report.facts), ("SYN", 2))
        got = {f.metric: f for f in self.repos.facts.list_facts(1, basis="standalone")}
        self.assertEqual(got["revenue"].value, D("105613700000.0"))
        self.assertEqual(got["eps_basic"].value, D("5.47"))                    # not 5.4699999999999997...
        with self.assertRaises(ValueError):
            ind.load_canonical_file(self.repos, Path(d.name) / "odd-name.json")


def rec(ctx, start, end, **fields):
    return {"context_id": ctx, "period_start": start, "period_end": end, "instant": None,
            **{k: D(str(v)) for k, v in fields.items()}}


class TestRealWorldQuirks(unittest.TestCase):
    """Patterns found by running the adapter over ~3,000 real filings (reproduced here with
    made-up numbers): zeros that mean 'not applicable', and contexts that contradict each other."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.names = lambda: {f.metric for f in self.repos.facts.list_facts(1)}  # noqa: E731

    def test_a_consolidated_banks_all_zero_npa_block_is_not_a_zero_npa_ratio(self):
        block = dict(gross_npa=0, net_npa=0, gross_npa_ratio=0, net_npa_ratio=0, return_on_assets=0,
                     cet1_ratio=0, additional_tier1_ratio=0, bank_interest_earned=900, advances=6000)
        report = ind.load_canonical(self.repos, [rec("OneD", "2025-04-01", "2025-06-30", **block)], entity="BNK")
        self.assertTrue(self.names() >= {"bank.interest_earned", "bank.advances"})
        self.assertFalse(self.names() & {"bank.gross_npa", "bank.net_npa", "bank.gross_npa_ratio",
                                          "bank.cet1_ratio", "bank.additional_tier1_ratio",
                                          "india.return_on_assets_reported"})
        self.assertTrue(any("treated as not reported" in s and "gross_npa" in s for s in report.skipped))
        eng = FinancialEngine(self.repos)
        self.assertIsNone(eng.get_ratio("BNK", "bank.gross_npa_to_advances").value)     # not 0%

    def test_real_npa_figures_and_partial_zeros_are_kept(self):
        real = dict(gross_npa=300, net_npa=0, gross_npa_ratio=D("5"), net_npa_ratio=0, advances=6000)
        ind.load_canonical(self.repos, [rec("OneD", "2025-04-01", "2025-06-30", **real)], entity="BNK")
        # the block is not all zero, so nothing is treated as a placeholder
        self.assertTrue(self.names() >= {"bank.gross_npa", "bank.net_npa", "bank.net_npa_ratio"})

    def test_a_filer_can_switch_the_rule_off(self):
        block = dict(gross_npa=0, net_npa=0, gross_npa_ratio=0, net_npa_ratio=0)
        ind.load_canonical(self.repos, [rec("OneD", "2025-04-01", "2025-06-30", **block)], entity="BNK",
                           placeholder_zeros=False)
        self.assertIn("bank.gross_npa", self.names())

    def test_genuine_zeros_are_kept(self):
        ind.load_canonical(self.repos, [rec("OneD", "2025-04-01", "2025-06-30", exceptional_items=0,
                                            net_profit_nci=0, borrowings_noncurrent=0, revenue=1000)], entity="X")
        self.assertTrue(self.names() >= {"exceptional_items", "net_profit_nci", "borrowings_noncurrent"})

    def test_zero_paid_up_capital_is_missing_so_the_other_context_supplies_the_share_count(self):
        # one context reports 0 for paid-up capital (no data), the other the real figure
        ind.load_canonical(self.repos, [
            rec("OneD", "2025-04-01", "2025-06-30", paid_up_equity_capital=0, face_value_per_share=5),
            rec("FourD", "2025-04-01", "2025-06-30", paid_up_equity_capital=695600000, face_value_per_share=2)],
            entity="APO")
        shares = [f for f in self.repos.facts.list_facts(1, metric="shares_outstanding")]
        self.assertEqual([f.value for f in shares], [347800000])               # 695,600,000 / 2

    def test_two_contexts_claiming_one_period_with_different_totals_keep_the_current_one_and_say_so(self):
        # a cumulative context given the quarter's own dates, with roughly double the values
        report = ind.load_canonical(self.repos, [
            rec("OneD", "2024-07-01", "2024-09-30", total_income=284892900000, net_profit=4351800000),
            rec("FourD", "2024-07-01", "2024-09-30", total_income=552393500000, net_profit=9141500000)],
            entity="LIFE")
        got = {f.metric: f for f in self.repos.facts.list_facts(1)}
        self.assertEqual((got["total_income"].value, got["net_profit"].value), (284892900000, 4351800000))
        self.assertIn("FourD reports 552393500000", got["total_income"].mapping_reason)
        self.assertIn("OneD used", got["total_income"].mapping_reason)
        self.assertEqual(len(report.conflicts), 2)

    def test_stale_prior_year_capital_in_another_context_does_not_override_the_current_one(self):
        report = ind.load_canonical(self.repos, [
            rec("OneD", "2021-01-01", "2021-03-31", paid_up_equity_capital=718900000, face_value_per_share=5),
            rec("FourD", "2020-04-01", "2021-03-31", paid_up_equity_capital=695600000, face_value_per_share=5)],
            entity="APO")
        shares = self.repos.facts.list_facts(1, metric="shares_outstanding")
        # different periods (quarter vs year) but the same balance date: one share count, from the current context
        self.assertEqual([f.value for f in shares], [143780000])
        # paid-up capital is a balance, so the two contexts now meet on it too: capital and share count
        self.assertEqual(len(report.conflicts), 2)
        self.assertIn("contexts disagree", shares[0].mapping_reason)

    def test_contexts_that_agree_raise_no_conflict(self):
        report = ind.load_canonical(self.repos, [
            rec("OneD", "2025-04-01", "2025-06-30", revenue=1000),
            rec("FourD", "2025-04-01", "2025-06-30", revenue=1000)], entity="X")
        self.assertEqual((report.conflicts, report.facts), ((), 1))

    def test_context_trust_order(self):
        from calcfinc.adapters.ind_as_xbrl.load import _rank
        from calcfinc.fact import FinancialFact
        flow = FinancialFact(entity_id=1, metric="revenue", value=1, statement_type="profit_and_loss",
                             basis="consolidated")
        pit = FinancialFact(entity_id=1, metric="total_assets", value=1, statement_type="balance_sheet",
                            basis="consolidated", is_point_in_time=True)
        self.assertEqual(_rank("FourD+OneI", flow), (3, "FourD"))      # a flow comes from the duration half
        self.assertEqual(_rank("FourD+OneI", pit), (0, "OneI"))        # a balance from the instant half
        self.assertEqual(_rank("PY_D", flow), (9, "PY_D"))


if __name__ == "__main__":
    unittest.main()
