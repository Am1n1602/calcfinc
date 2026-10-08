# calcfinc

Turn periodic financial statements for any entity (company, SME, business unit, project) into
auditable metrics: ratios, growth, CAGR, valuation, margin decomposition, segment attribution.

Every result carries its value, unit, formula, the exact input facts, and a plain-language
limitation when it cannot be computed. A missing input yields `None` plus a reason, never zero
and never an estimate.

- **Exact arithmetic.** All numbers are `Decimal`; floats are refused at the door.
- **Any currency, calendar, standard and frequency.** Currency travels on each fact; fiscal years
  follow the entity; months, quarters and years are all first-class.
- **Open definitions.** Ratios are formula strings in a registry. Add your own with
  `register_ratio`, and read exactly what any result used.
- **Zero runtime dependencies.** Python 3.11+.

> **Status: pre-alpha.** The API may change before 0.1.

## Quick start

```
metric,FY2025,FY2026
revenue,1000,1200
net_profit,100,150
total_equity,500,600
```

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv("acme.csv", entity="Acme Inc", currency="USD")

roe = eng.get_ratio("Acme Inc", "roe")
roe.value        # Decimal('25')
roe.formula      # '100 * net_profit / total_equity'
roe.inputs       # the exact facts used, with period, source and currency
roe.limitations  # () -- or the reason the value is None, or any substitution made

eng.get_growth("Acme Inc", "revenue").value      # Decimal('20')  (percent, FY2025 -> FY2026)
eng.get_cagr("Acme Inc", "revenue").value        # Decimal('20.0')
```

A ratio that cannot be computed says why instead of guessing. This file has no cash flow
statement, so:

```python
r = eng.get_ratio("Acme Inc", "free_cash_flow")
r.value          # None
r.limitations    # ('free_cash_flow: operating_cash_flow not reported; capex: capex_ppe not reported; ... [FY2026]',)
```

Seven runnable examples with synthetic data are in [`examples/`](examples): a USD company, an INR
company with consolidated and standalone bases, a bank and an insurer, monthly SME accounts with
a custom DSCR ratio, cross-currency comparison, a US filer from SEC `companyfacts` JSON, and an
Indian exchange XBRL filing. The fact and CSV format is documented in
[`docs/fact-schema.md`](docs/fact-schema.md).

## Source adapters

Beyond CSV, calcfinc can read the SEC's public `companyfacts` JSON (US-GAAP filers) and Indian
exchange XBRL filings. Both keep restatements as versions, tie every fact to its filing, and
derive the quarter a source never reports (the SEC's Q4). See [`docs/adapters.md`](docs/adapters.md)
for what each does, the SEC's fair-access rules, and what has not been verified against live data.

## What it will not do

It will not convert currencies, so amounts in different currencies are listed but never ranked
(ratios compare freely). It will not annualise a quarterly or monthly ratio, and says so when a
ratio mixes flows with balances over part of a year. For a full-year view of quarterly or monthly
data, use the trailing-twelve-month ratios (`roe_ttm`, `net_profit_margin_ttm`, `pe_ttm`,
`ev_ebitda_ttm`, ...). They sum the latest four adjacent quarters (or twelve months) and return
`None`, with the reason, if any period is missing, rather than stretching the window. It does not
ship any market or vendor data.

`period="latest"` (or `latest_annual`, `latest_quarter`, `latest_month`) means the newest period of
that kind. If a ratio's inputs are missing there, the result is `None` with the reason; it does not
quietly show an older year. Pass `fallback=True` to get the newest period where it can be computed,
with a limitation naming both periods.

Results are calculations, not investment advice.

## Development

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
```

## Licence

MIT
