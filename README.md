# calcfinc

[![ci](https://github.com/Am1n1602/calcfinc/actions/workflows/ci.yml/badge.svg)](https://github.com/Am1n1602/calcfinc/actions/workflows/ci.yml)

**Auditable financial metrics from the statements of any entity.** Give it periodic figures (a
CSV, a pandas frame, an SEC filing, an Indian exchange filing) and ask for ratios, growth,
CAGR, valuation, DuPont, trailing twelve months. Every answer carries the formula that produced
it, the exact figures it used, and a plain-language note whenever something was substituted or
could not be computed.

```python skip
roe = eng.get_ratio("Acme Inc", "roe")
roe.value        # Decimal('25')
roe.formula      # '100 * net_profit / total_equity'
roe.inputs       # the facts used: metric, value, period, currency, source, date reported
roe.limitations  # () - or why the value is None, or what was substituted
```

- **Exact.** Every number is a `Decimal`; floats are refused at every entrance. A result is the
  same on any machine and any Python version.
- **Honest.** A missing input gives `None` and the reason, never zero and never an estimate.
- **Open.** More than a hundred ratios, each one a readable formula string
  ([list](docs/ratios.md)). Add your own with `register_ratio`.
- **Any entity.** Any currency, any fiscal calendar (March, 52/53-week...), months, quarters
  and years, consolidated and standalone, banks and insurers.
- **Zero runtime dependencies.** Python 3.11 or later; pandas is optional.

> **Status: 0.1, beta.** Tested on 19 US and 20 Indian companies' real filings (see
> [what has and has not been verified](docs/manual.md#15-what-has-and-has-not-been-verified)).
> The API may still change in 0.x; changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Install

```bash
pip install calcfinc
```

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

- **SEC `companyfacts`** (US-GAAP): exact periods, restatements kept as versions, the fourth
  quarter derived, bank lines for banks.
- **Indian exchange XBRL** (Ind-AS): April-March year, `india.*` ratios in the Schedule III and ICAI
  forms, placeholder zeros not loaded.

Both tie every fact to its filing. See [docs/adapters.md](docs/adapters.md). No market or vendor
data is bundled, and there is no network access except one explicit SEC download helper.

## Things it deliberately will not do

- Convert currencies. Amounts in different currencies are listed, never ranked.
- Annualise a quarterly ratio. It says "not annualised" and offers the trailing-twelve-month form.
- Hide a substitution. A fallback definition, a derived quarter or a mixed restatement vintage is
  always in `limitations`.
- Apply operating-company ratios to a bank or an insurer. Interest cover, debt and the
  working-capital ratios return `None` with the reason for financial companies.

## Documentation

- **[Manual](docs/manual.md)**: concepts, loading data, periods, every question you can ask,
  reading results, custom ratios, running it in production, troubleshooting. Its examples are run
  by the test suite.
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
