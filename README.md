# calcfinc

[![ci](https://github.com/Am1n1602/calcfinc/actions/workflows/ci.yml/badge.svg)](https://github.com/Am1n1602/calcfinc/actions/workflows/ci.yml)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Am1n1602/calcfinc/blob/main/examples/calcfinc_tour.ipynb)

**Financial ratios you can defend.** Every number calcfinc returns comes with the formula that produced it,
the exact figures it used, the filing each figure came from, and a plain-language note whenever something
was substituted or is missing. Exact decimal arithmetic, no dependencies, and `None` with a reason instead
of a guess.

Apple's return on equity from its own 10-K, in four lines:

```python skip
from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import sec_companyfacts as sec

raw = sec.fetch_companyfacts(320193, "Your Name you@example.com")      # the SEC wants a real contact
repos = SqliteRepositories(":memory:")
sec.load_companyfacts(repos, sec.read_companyfacts(raw), ticker="AAPL")
roe = FinancialEngine(repos).get_ratio("AAPL", "roe", period="FY2025")
```

```text
roe.value        Decimal('151.9129833317510476991306470644081')     percent, exact
roe.formula      100 * net_profit / total_equity
roe.inputs       net_profit    112,010,000,000 USD   FY2025   reported 2025-10-31   10-K 0000320193-25-000079
                 total_equity   73,733,000,000 USD   FY2025   reported 2025-10-31   10-K 0000320193-25-000079
roe.limitations  ()
```

Ask for something Apple does not report and you get the reason, not a number:

```text
interest_coverage.value         None
interest_coverage.limitations   ('interest_coverage: finance_costs not reported [FY2025]',)
```

The same for an Indian exchange filing (Ind-AS XBRL), here Tata Consultancy Services' consolidated results: April-March
year, rupees, consolidated and standalone kept apart, and the Schedule III / ICAI ratio forms as `india.*`. The two
TCS filings used here are public regulatory filings, included unmodified in
[`examples/data/tcs`](examples/data/tcs) so you can run this yourself (the installed package contains no data);
for other companies you download the files from the exchange.

```python skip
from pathlib import Path

from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import ind_as_xbrl

repos = SqliteRepositories(":memory:")
ind_as_xbrl.load_xbrl_files(repos, sorted(Path("examples/data/tcs").glob("*Consolidated.xbrl")), entity="TCS")   # basis from the file name
roe = FinancialEngine(repos).get_ratio("TCS", "india.roe", period="FY2025")
```

```text
roe.value        Decimal('52.16419904858624191565556683948902')    percent
roe.formula      100 * (net_profit - india.preference_dividend) / ((total_equity + prior(total_equity)) / 2)
roe.inputs       net_profit      487,970,000,000 INR   FY2025   31-MAR-2025_Integrated_Filing-_Financials_Original_Consolidated.xbrl   (Rs 48,797 crore)
                 total_equity    957,710,000,000 INR   FY2025   31-MAR-2025_Integrated_Filing-_Financials_Original_Consolidated.xbrl
                 total_equity    913,190,000,000 INR   FY2024   31-Mar-2024_Financial_Results_Original_Consolidated.xbrl
roe.limitations  ('india.preference_dividend not reported; treated as 0 in india.roe',)
```

Profit is divided by *average* equity (March 2024 and March 2025), as the Schedule III form specifies, which is why
it differs from the plain year-end `roe` (50.95%). The one input the filing did not carry is announced rather than
silently assumed. The figures are TCS's own, as filed. The [tour notebook](examples/calcfinc_tour.ipynb) runs this
same example in Colab (section 12), after a walk-through on made-up sample files.

Most ratio libraries return a bare float. Here you also get the audit trail: `roe.inputs` is the list of facts,
each with its period, currency, filing and report date, so anyone can recompute the figure by hand or
follow it back to the SEC. `roe.to_frame()` gives that trail as a pandas DataFrame, with the values still
exact `Decimal`s.

- **Exact.** Every number is a `Decimal`; floats are refused at every entrance. A result is the same on
  any machine and Python version.
- **Honest.** A missing input gives `None` and the reason, never zero and never an estimate.
- **Auditable.** The formula, every input fact, its filing and report date, and any restatement warning travel
  with the result.
- **Open.** More than a hundred ratios, each one a readable formula string ([list](docs/ratios.md)). Add your
  own with `register_ratio`.
- **Any entity.** Any currency, any fiscal calendar (March, 52/53-week...), months, quarters and years,
  consolidated and standalone. Banks and insurers get the ratios that suit them; operating-company ratios that
  mislead return `None` with the reason.
- **Zero runtime dependencies.** Python 3.11 or later; pandas is optional.

> **Status: 0.1, beta.** Tested on real filings of 19 US and 20 Indian companies, and checked live on Tesla,
> Boeing, HCLTech and Titan (see
> [what has and has not been verified](docs/manual.md#15-what-has-and-has-not-been-verified)). The API
> may still change in 0.x; changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Try it

```bash
pip install calcfinc
```

Or open the [tour notebook in Colab](https://colab.research.google.com/github/Am1n1602/calcfinc/blob/main/examples/calcfinc_tour.ipynb):
it runs on built-in sample data, with an optional live Apple download at the end.

## Quick start

A CSV with one row per metric and one column per fiscal year:

```csv acme.csv
metric,FY2025,FY2026
revenue,1000,1200
net_profit,100,150
total_equity,500,600
total_assets,2000,2400
```

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv("acme.csv", entity="Acme Inc", currency="USD")

roe = eng.get_ratio("Acme Inc", "roe")
roe.value                                        # -> 25
roe.formula                                      # -> 100 * net_profit / total_equity

# growth in percent, FY2025 to FY2026, and compound annual growth
eng.get_growth("Acme Inc", "revenue").value      # -> 20
eng.get_cagr("Acme Inc", "revenue").value        # -> 20
```

A figure that cannot be computed says why instead of guessing. This file has no cash flow
statement:

```python
fcf = eng.get_ratio("Acme Inc", "free_cash_flow")
fcf.value                                        # -> None
print(fcf.limitations[0])
```

## What you can ask

| | |
|---|---|
| `get_ratio`, `get_metric` | margins, returns, leverage, liquidity, efficiency, per-share, trailing twelve months |
| `get_valuation` | P/E, P/B, EV/EBITDA, yields, market cap (you supply prices) |
| `get_growth`, `get_cagr` | year on year, quarter on quarter, month on month, compound |
| `compare_periods`, `compare_companies` | two periods side by side; rank entities (never across currencies) |
| `decompose_metric` | DuPont (three and five factor), net-margin bridge |
| `check`, `check_periods` | accounting identities; do the quarters add up to the year |
| `get_segment_data`, `segment_growth` | segment revenue, contribution, growth |
| `calculate` | any formula over numbers you give it |

## Where data comes from

CSV (long or wide), dicts, pandas, or your own storage; a SQLite file if you want it to persist.
Two adapters read real filings:

- **SEC `companyfacts`** (US-GAAP, and IFRS for 20-F and 40-F filers): exact periods, restatements
  kept as versions (and viewable `as_of` a date), the fourth quarter derived, bank lines for banks,
  premiums and claims for insurers.
- **Indian exchange XBRL** (Ind-AS): April-March year, `india.*` ratios in the Schedule III and ICAI
  forms, placeholder zeros not loaded.

Both tie every fact to its filing. See [docs/adapters.md](docs/adapters.md). No market or vendor
data is bundled in the package, and there is no network access except one explicit SEC download helper. (The
repository, but not the package, includes two TCS filings for the demo; see
[`examples/data/tcs`](examples/data/tcs).)

## What it will not do

- Convert currencies. Amounts in different currencies are listed, never ranked.
- Annualise a quarterly ratio. It says "not annualised" and offers the trailing-twelve-month form.
- Hide a substitution. A fallback definition, a derived quarter or a mixed restatement vintage is
  always in `limitations`.
- Guess. Where a source concept is not mapped, the metric is absent, not approximated.

## Documentation

- **[Manual](docs/manual.md)**: concepts, loading data, periods, every question you can ask,
  reading results, custom ratios, running it in production, troubleshooting. Its examples are run
  by the test suite.
- [Tour notebook](examples/calcfinc_tour.ipynb) (also tested)
- [Ratio and metric reference](docs/ratios.md) (generated from the code)
- [Fact format and CSV layouts](docs/fact-schema.md)
- [Adapters and real-data results](docs/adapters.md)
- [Examples](examples): seven runnable scripts with synthetic data

## Development

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"     # Windows: .venv\Scripts\python
.venv/bin/python -m pytest && .venv/bin/ruff check . && .venv/bin/mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Licence

MIT. Results are calculations, not investment advice.
