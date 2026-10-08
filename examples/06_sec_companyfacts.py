"""Example 6: a US filer from the SEC's companyfacts JSON (a synthetic file here, read offline).

Shows what the adapter does that a plain copy of the numbers would not: the fourth quarter the SEC
never reports is derived, a restated figure is kept as a second version, and every fact points to
the filing it came from. To download a real file, see fetch_companyfacts and docs/adapters.md.
"""
from pathlib import Path

from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import sec_companyfacts as sec

repos = SqliteRepositories(":memory:")
report = sec.load_companyfacts_file(repos, Path(__file__).parent / "data" / "sec_companyfacts_synthetic.json",
                                    ticker="SYN")
print(f"loaded {report.facts} facts from {report.filings} filings; fiscal year ends in month "
      f"{report.fiscal_year_end_month}; {report.derived_quarters} quarters derived")

eng = FinancialEngine(repos)
q4 = eng.get_metric("SYN", "revenue", period="FY2025Q4")
q4_fact = next(f for f in repos.facts.list_facts(1, metric="revenue") if f.quarter == 4)
print(f"Q4 revenue: {q4.value} {q4.unit} ({q4_fact.mapping_reason})")
print("revenue TTM (four quarters to 2025-12-31):", eng.get_ratio("SYN", "revenue_ttm", period="FY2025Q4").value)

versions = [(str(f.value), f.reported_at.isoformat()) for f in repos.facts.list_facts(1, metric="net_profit")
            if f.is_annual]
print("net profit FY2025 as filed, then restated:", " -> ".join(f"{v} ({d})" for v, d in versions))

roe = eng.get_ratio("SYN", "roe", period="FY2025")
print(f"ROE FY2025: {roe.value} pct, on the latest figures")
src = repos.sources.get(eng.get_metric("SYN", "revenue", period="FY2025").inputs[0].source_id)
print("revenue FY2025 comes from:", src.document_title, "-", src.uri)
