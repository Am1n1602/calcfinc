"""Example 7: an Indian exchange XBRL filing (a synthetic one here): April-March year, INR,
exact numbers, and the `india.*` ratios."""
from pathlib import Path

from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import ind_as_xbrl

repos = SqliteRepositories(":memory:")
report = ind_as_xbrl.load_xbrl_file(repos, Path(__file__).parent / "data" / "synthetic_consolidated_30-Jun-2025.xbrl",
                                    entity="SYN")
print(f"loaded {report.facts} facts; records needing review: {len(report.needs_review)}")

eng = FinancialEngine(repos)
print("periods:", eng.periods("SYN"))                   # the quarter April-June 2025 is FY2026 Q1
print("roe:", eng.get_ratio("SYN", "roe").value)
print("shares outstanding:", eng.get_metric("SYN", "shares_outstanding").value, "(paid-up capital / face value)")

roce = eng.get_ratio("SYN", "india.roce")                 # tangible net worth + debt + deferred tax basis
print(f"india.roce: {roce.value} pct")
for note in roce.limitations:
    print("  note:", note)
