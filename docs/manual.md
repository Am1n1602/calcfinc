# calcfinc manual

Version 0.1.3. This manual is tested: every Python example in it is run by the test suite, and
every value shown after `# ->` is checked against what the code returns.

**Contents**

1. [What calcfinc is](#1-what-calcfinc-is)
2. [Install](#2-install)
3. [A first session](#3-a-first-session)
4. [The ideas you need](#4-the-ideas-you-need)
5. [Getting data in](#5-getting-data-in)
6. [Periods](#6-periods)
7. [Asking questions](#7-asking-questions)
8. [Reading a result](#8-reading-a-result)
9. [Checking your data](#9-checking-your-data)
10. [Banks and insurers](#10-banks-and-insurers)
11. [Your own metrics and ratios](#11-your-own-metrics-and-ratios)
12. [Exact numbers](#12-exact-numbers)
13. [Source adapters: SEC and Indian filings](#13-source-adapters-sec-and-indian-filings)
14. [Running it for real](#14-running-it-for-real)
15. [What has and has not been verified](#15-what-has-and-has-not-been-verified)
16. [Troubleshooting](#16-troubleshooting)
17. [Reference](#17-reference)

---

## 1. What calcfinc is

calcfinc turns the periodic financial statements of any entity (a listed company, a small
business, a division, a project) into **auditable metrics**: ratios, growth, CAGR, valuation,
DuPont decomposition, segment attribution, trailing twelve months. Every number it returns
comes with the formula that produced it, the exact input figures (with period, source and
filing date), and a plain-language note whenever something was substituted or could not be
computed.

It is built around four promises:

- **Exact.** Every number is a `Decimal`. Floats are refused at every entrance, because 0.1 as a
  float is not 0.1.
- **Honest.** A missing input gives `None` and the reason. Never zero, never an estimate. A
  substitute (a fallback definition, a derived quarter) is always announced.
- **Auditable.** `result.formula` and `result.inputs` let anyone recompute the figure by hand.
- **Open.** Definitions are formula strings in a registry. You can read every one, change none by
  accident, and add your own.

It has no runtime dependencies (Python 3.11 or later, standard library only) and does not
ship, fetch (unless you call the one download helper) or bundle any market or vendor data in the package.

**What it deliberately does not do.** It does not convert currencies (amounts in different
currencies are listed but never ranked), annualise a quarterly ratio (it says so instead), fill
gaps, forecast, or give investment advice. Results are calculations.

## 2. Install

```bash
pip install calcfinc              # the library
pip install "calcfinc[pandas]"    # only if you load pandas DataFrames
```

For development from a clone:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # on Windows: .venv\Scripts\python
.venv/bin/python -m pytest
```

## 3. A first session

Put a company's figures in a CSV. One row per metric, one column per fiscal year:

```csv acme.csv
metric,FY2025,FY2026
revenue,1000,1200
net_profit,100,150
total_equity,500,600
total_assets,2000,2400
```

Load it and ask a question:

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv("acme.csv", entity="Acme Inc", currency="USD")

roe = eng.get_ratio("Acme Inc", "roe")
roe.value        # -> 25
roe.unit         # -> pct
roe.period       # -> FY2026
roe.formula      # -> 100 * net_profit / total_equity
```

The result lists the facts it was computed from:

```python
for fact in roe.inputs:
    print(fact.metric, fact.value, fact.period, fact.currency)
```

Growth, compound growth and a ratio that cannot be computed:

```python
eng.get_growth("Acme Inc", "revenue").value     # -> 20
eng.get_cagr("Acme Inc", "revenue").value       # -> 20

fcf = eng.get_ratio("Acme Inc", "free_cash_flow")
fcf.value                                       # -> None
print(fcf.limitations[0])                       # says what is missing and in which period
```

That last call is the point of the library: this file has no cash flow statement, so free cash
flow is `None` with the reason, not a guess.

## 4. The ideas you need

**Entity.** Whatever has statements: a company, a unit, a project. Found by name, alias or any
identifier (ticker, ISIN, CIK, LEI).

**Fact.** One reported figure: entity, metric, period, basis, value, currency, and optionally
when it was published (`reported_at`) and where it came from. Everything calcfinc computes is
derived from facts, and every result lists the facts it used. The full list of fields and the CSV
layouts are in [fact-schema.md](fact-schema.md).

**Metric.** A name for an input you report: `revenue`, `net_profit`, `total_assets`,
`bank.advances`. Over eighty are built in, the Indian additions included; the table is in
[ratios.md](ratios.md). A metric is
either a *flow* (income statement and cash flow: a figure for a stretch of time) or a *balance*
(balance sheet: a figure at a date).

**Ratio.** A named formula over metrics and other ratios: `roe = 100 * net_profit / total_equity`.
More than a hundred are built in. "Ratio" here includes derived amounts such as `ebitda` and
`free_cash_flow`.

**Basis.** `consolidated` (the default) or `standalone`. They are separate data sets and are
never substituted for each other.

**Period.** A month, quarter, half-year or year, placed on the entity's own fiscal calendar.
`FY2026` means the fiscal year *ending* in 2026.

**Restatement.** If the same figure is reported twice with different `reported_at` dates, both
are kept and the engine uses the later one. Each result says when each input was reported.

**Result.** Every question returns an `EngineResult` (section 8). An unanswerable question is a
result with `value=None`; only a malformed request raises `EngineError`.

## 5. Getting data in

### CSV

Two layouts, detected from the header. **Wide** is one row per metric, one column per period (as
in section 3). **Long** is one row per fact and lets you carry several entities, currencies,
bases and report dates in one file:

```csv long.csv
entity,metric,period,value,currency,basis
Acme,revenue,FY2026,1200,USD,consolidated
Acme,revenue,FY2026,700,USD,standalone
Acme,net_profit,FY2026,150,USD,consolidated
```

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv("long.csv")
eng.get_metric("Acme", "revenue").value                         # -> 1200
eng.get_metric("Acme", "revenue", basis="standalone").value     # -> 700
```

A file with any bad row loads **nothing**. Every problem is reported with its line and column:

```python
from calcfinc.loaders import LoadError

try:
    FinancialEngine.from_records([{"entity": "A", "metric": "revnue", "period": "FY2026", "value": "1"}])
except LoadError as e:
    print(e.errors[0])      # row 1, metric: unknown metric 'revnue'; did you mean 'revenue'? ...
```

An empty cell in a *wide* file means "no data" and creates nothing. An empty `value` in a *long*
file is an explicit "not reported" fact.

### Records and DataFrames

`from_records` takes dicts with the long-layout keys:

```python
from calcfinc import FinancialEngine

rows = [
    {"entity": "Acme", "metric": "revenue", "period": "FY2026Q1", "value": "250", "currency": "USD"},
    {"entity": "Acme", "metric": "revenue", "period": "FY2026Q2", "value": "260", "currency": "USD"},
    {"entity": "Acme", "metric": "revenue", "period": "FY2026Q3", "value": "270", "currency": "USD"},
    {"entity": "Acme", "metric": "revenue", "period": "FY2026Q4", "value": "280", "currency": "USD"},
]
eng = FinancialEngine.from_records(rows)
eng.get_ratio("Acme", "revenue_ttm", period="FY2026Q4").value   # -> 1060
```

`FinancialEngine.from_dataframe(df, layout="long" | "wide")` takes a pandas frame (install the
`pandas` extra). A float cell is refused unless you pass `float_policy="repr"`, which converts it
through its shortest text form (a NaN cell becomes "not reported") and records how many float
cells it handled on the load's source.

All three loaders take the same options: `entity=`, `currency=` (the default for facts that give
none), `basis=`, `fiscal_year_end_month=` (default 12), `sector=` (section 10) and `windows=`
(section 6).

### Restatements

```python
from calcfinc import FinancialEngine

rows = [
    {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "100", "currency": "USD",
     "reported_at": "2027-02-01"},
    {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "90", "currency": "USD",
     "reported_at": "2027-08-01"},
]
eng = FinancialEngine.from_records(rows)
eng.get_metric("A", "revenue").value                          # -> 90
[f.value for f in eng.repos.facts.list_facts(1, metric="revenue")]   # -> [Decimal('100'), Decimal('90')]
```

Both versions stay in the store, so you can audit what changed and when. If the later figure
is missing (`None`), it does not erase the earlier one.

### As it was known on a date

`as_of` gives a view of the same data as it stood on a date: a fact first reported later, such as a
restatement, is left out. Use it for a back-test, or to reproduce a number you published.

```python
past = eng.as_of("2027-06-01")                      # a new engine; eng itself is unchanged
past.get_metric("A", "revenue").value               # -> 100
past.get_metric("A", "revenue").as_of               # -> 2027-06-01
eng.as_of("2026-12-31").get_metric("A", "revenue").value   # -> None
```

- Every method works on the view, and each result carries `as_of`. A date that is a filing date
  includes that filing.
- A fact with no `reported_at` cannot be placed in time. It stays in every view, and a result that
  used one says so in `limitations`, so a back-test is never quietly wrong. Load `reported_at` (the
  records and DataFrame loaders take a column; Indian XBRL takes `reported_at=` or, for several
  files, `{file name or path: date}` with an entry for every file, `None` for an undated one).
- Segment data is not dated; a view refuses it.
- Views made from one engine read the store once and share that read, so a loop over many dates is cheap.
  After loading more data, call `refresh()` on the engine and make new views.
- For SEC data, fourth quarters and year-to-date cash flows are derived for each version of their
  year, so a view between a filing and its restatement still has them. A database loaded with an
  earlier release should be loaded again to get those versions.

### A database that outlives the process

`FinancialEngine.from_*` keep everything in memory. To keep it, open a `SqliteRepositories` on a
file, load into it, and build the engine on it. Reopen it later and nothing needs reloading:

```python
from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.loaders import load_records

rows = [{"entity": "Acme", "metric": "revenue", "period": "FY2026", "value": "1200", "currency": "USD"}]

with SqliteRepositories("books.db") as repos:     # commits on a clean exit, always closes
    load_records(repos, rows)

repos = SqliteRepositories("books.db")
eng = FinancialEngine(repos)
eng.get_metric("Acme", "revenue").value           # -> 1200
repos.close()
```

Values are stored as exact decimal text, so no SQLite type conversion can touch them. If you add
facts after building an engine, call `eng.refresh()` so it rebuilds its period records.
You can also supply your own storage by implementing the protocols in `calcfinc.store.base`.

### Share prices

Valuation needs prices, and calcfinc ships none. Add your own, one close per entity and day:

```python
from datetime import date
from decimal import Decimal

from calcfinc import FinancialEngine, SharePrice

rows = [{"entity": "Acme", "metric": m, "period": "FY2026", "value": v, "currency": "USD"}
        for m, v in (("eps_basic", "15"), ("total_equity", "600"))]
rows.append({"entity": "Acme", "metric": "shares_outstanding", "period": "2026-12-31", "value": "10"})
eng = FinancialEngine.from_records(rows)

acme = eng.repos.entities.resolve("Acme")
eng.repos.prices.add_prices(
    [SharePrice(entity_id=acme.id, price_date=date(2026, 12, 31), close=Decimal("300"), currency="USD")])
eng.repos.commit()

eng.get_valuation("Acme", "pe").value            # -> 20
eng.get_valuation("Acme", "pb").value            # -> 5
eng.get_valuation("Acme", "market_cap").value    # -> 3000
```

A year's valuation uses the last close on or up to 14 days before the period end. If there is none,
the result is `None` and says so. Valuation ratios are priced at fiscal year ends; the
trailing-twelve-month ones (`pe_ttm`) can be priced at any quarter end.

### Segments

Segment revenue lives beside the facts and gives contribution and growth:

```python
from datetime import date

from calcfinc import Basis, FinancialEngine, Segment, SegmentFact

eng = FinancialEngine.from_records(
    [{"entity": "Acme", "metric": "revenue", "period": "FY2026", "value": "1000", "currency": "USD"}])
acme = eng.repos.entities.resolve("Acme")

for name, value in (("Retail", "600"), ("Wholesale", "400")):
    seg = eng.repos.segments.upsert_segment(Segment(entity_id=acme.id, name=name))
    eng.repos.segments.add_facts([SegmentFact(
        segment_id=seg.segment_id, entity_id=acme.id, metric="segment_revenue", value=value,
        basis=Basis.CONSOLIDATED, currency="USD", period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31), financial_year=2026, is_annual=True)])
eng.repos.commit()

res = eng.get_segment_data("Acme")
[(r.segment, r.contribution_pct) for r in res.rows]       # -> [('Retail', Decimal('60')), ('Wholesale', Decimal('40'))]
```

`segment_growth` gives each segment's change, growth and share of the total change. Segment
margin is never computed: filings report segment revenue, and calcfinc will not approximate the rest.

## 6. Periods

Everywhere a period is accepted, these forms work:

| You write | Meaning |
|---|---|
| `"latest"` | the newest reporting period of any kind |
| `"latest_annual"`, `"latest_quarter"`, `"latest_month"` | the newest period of that kind |
| `2026` or `"FY2026"` | the fiscal year ending in 2026 |
| `"FY2026Q1"` or `(2026, 1)` | the first fiscal quarter of FY2026 |
| `"2026-03"` | the calendar month |

In data files a period can also be an explicit range (`2026-01-01..2026-12-31`) or a single date
(`2026-12-31`, for a balance).

**Fiscal calendar.** Set `fiscal_year_end_month` (March for India's April-March year, for
example). Quarters count from the start of that year. A period end in the first week of a month
counts as the previous month, so 52/53-week years that end on 3 September are still August
year ends.

**Period types** are decided by length: month 27 to 32 days, quarter 71 to 111, half 160 to 200,
year 330 to 400. Pass `windows=PeriodWindows(...)` to a loader for an unusual calendar.

**"latest" means the newest period, not the newest period that happens to work.** If a ratio's
inputs are missing there, you get `None` and the reason. Ask for `fallback=True` if you want the
newest period where it can be computed; the result then says which period it used and why:

```python
from calcfinc import FinancialEngine

rows = [{"entity": "A", "metric": m, "period": f"FY2026Q{q}", "value": v, "currency": "USD"}
        for q in (1, 2, 3) for m, v in (("net_profit", "10"), ("total_equity", "100"))]
rows.append({"entity": "A", "metric": "revenue", "period": "FY2026Q4", "value": "50", "currency": "USD"})
rows.append({"entity": "A", "metric": "total_equity", "period": "FY2026Q4", "value": "100", "currency": "USD"})
eng = FinancialEngine.from_records(rows)

eng.get_ratio("A", "roe").value                              # -> None
eng.get_ratio("A", "roe", fallback=True).period              # -> FY2026 Q3
print(eng.get_ratio("A", "roe", fallback=True).limitations[0])
```

`latest` skips a date that carries only a balance (a cover-page share count) because it is not a
reporting period. A reported metric (`get_metric("A", "revenue")`) means the latest period that
reports it.

**Not annualised.** A quarterly return is a quarterly return. When a ratio divides a flow by a
balance over part of a year, the result carries the note "not annualised". For a full-year
view of quarterly or monthly data use the trailing-twelve-month ratios: `ttm(x)` sums the latest
adjacent periods that make a year (4 quarters, 12 months, 2 half-years) and is `None`, with the
reason, if one is missing. `roe_ttm`, `net_profit_margin_ttm`, `pe_ttm`, `ev_ebitda_ttm` and others
are built in.

## 7. Asking questions

All of these return an `EngineResult`, except `compare_companies`, which returns a dictionary.
Every method takes an entity name, alias, identifier or `Entity`, and `basis=`.

| Method | Answers |
|---|---|
| `get_metric(entity, metric, period=)` | a reported figure, or any derived quantity |
| `get_ratio(entity, ratio, period=, fallback=)` | any registered ratio |
| `get_valuation(entity, kind, period=)` | P/E, P/B, EV/EBITDA, yields, market cap (needs prices) |
| `get_growth(entity, metric, kind="yoy"\|"qoq"\|"mom")` | percentage change between comparable periods |
| `get_cagr(entity, metric, years=)` | compound annual growth over the annual history |
| `compare_periods(entity, metrics, a=, b=)` | two periods side by side |
| `compare_companies(metric, entities, period=)` | rank entities on one metric |
| `decompose_metric(entity, "roe"\|"dupont5"\|"net_margin")` | what drives a figure |
| `calculate(expr, **vars)` | any formula over numbers you give it |
| `check(entity)`, `check_periods(entity)` | accounting identities (section 9) |
| `get_segment_data(entity)`, `segment_growth(entity)` | segment revenue (section 5) |
| `periods(entity)`, `available_metrics(entity)` | what the engine knows |

A few worth showing:

```python
from calcfinc import FinancialEngine

rows = []
for entity, scale in (("Alpha", 1), ("Beta", 2)):
    for period, rev, profit, equity, assets in (("FY2025", 1000, 100, 500, 2000), ("FY2026", 1200, 150, 600, 2400)):
        for metric, value in (("revenue", rev), ("net_profit", profit), ("total_equity", equity),
                              ("total_assets", assets)):
            rows.append({"entity": entity, "metric": metric, "period": period,
                         "value": str(value * scale if metric != "net_profit" else value), "currency": "USD"})
eng = FinancialEngine.from_records(rows)

# two periods side by side
cmp = eng.compare_periods("Alpha", ["revenue", "net_profit"], a="FY2025", b="FY2026")
cmp.components["revenue"]["pct_change"]            # -> 20

# DuPont: ROE = margin x turnover x leverage
d = eng.decompose_metric("Alpha", "roe")
d.value                                            # -> 25
d.components["components"]["net_profit_margin"]   # -> 12.5
d.components["reconciles"]                         # -> True

# rank companies on a ratio; roe is Alpha 25%, Beta 12.5%
ranked = eng.compare_companies("roe", ["Alpha", "Beta"], period="FY2026")
[(r["entity"], r["rank"]) for r in ranked["results"]]       # -> [('Alpha', 1), ('Beta', 2)]
```

`compare_companies` refuses to rank *amounts* in different currencies and says so; ratios
compare freely because they carry no currency.

## 8. Reading a result

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_records([
    {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "1200", "currency": "USD"},
    {"entity": "A", "metric": "net_profit", "period": "FY2026", "value": "150", "currency": "USD"},
])
r = eng.get_ratio("A", "net_profit_margin")
r.value               # -> 12.5
r.name                # -> net_profit_margin
r.kind                # -> ratio
r.entity              # -> A
r.basis               # -> consolidated
r.definition_version  # -> 1
r.ok                  # -> True
```

| Field | Meaning |
|---|---|
| `value` | a `Decimal`, or `None` if it cannot be computed |
| `unit` | `pct`, `x`, `days`, `per_share`, or the ISO currency of an amount |
| `currency` | the currency of an amount; `None` for ratios |
| `period`, `basis`, `entity` | what was answered |
| `formula` | the formula actually used, which may be a labelled fallback |
| `inputs` | tuple of `FactRef`: `metric`, `value`, `period`, `currency`, `source_id`, `reported_at` |
| `components` | extra detail (the DuPont factors, a valuation's price and date) |
| `limitations` | tuple of plain-language notes |
| `definition_version` | bumps when a built-in definition changes |
| `as_of` | the date of the view that answered, or `None` |

**`limitations` is part of the answer.** It carries, in this order of importance:

- why `value` is `None` ("net_profit not reported [FY2026 Q4]");
- a substitution that was made ("EBITDA proxied by pre-provision operating profit");
- a derived input ("single quarter derived: 12M year-to-date less 9M");
- a review flag from the source ("source record flagged for review (...)");
- inputs for one period that were first reported in different filings, which may not agree;
- a ratio that mixes flows with balances over part of a year ("not annualised").

Anyone passing a number onward should pass its limitations with it.

**Growth, CAGR and comparisons keep their lineage too.** Each input is the fact from its own period,
with its own source and filing date, so a restated year beside an unrestated one is visible. For a
ratio, the inputs are the underlying facts of each period, not the ratio's name:

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_records([
    {"entity": "A", "metric": "revenue", "period": "FY2025", "value": "100", "currency": "USD",
     "source": "10-K 2025", "reported_at": "2025-11-01"},
    {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "120", "currency": "USD",
     "source": "10-K 2026", "reported_at": "2026-11-01"},
])
g = eng.get_growth("A", "revenue")
[(i.period, i.value, i.reported_at.isoformat()) for i in g.inputs]    # -> [('FY2025', Decimal('100'), '2025-11-01'), ('FY2026', Decimal('120'), '2026-11-01')]
eng.repos.sources.get(g.inputs[1].source_id).document_title           # -> 10-K 2026
```

`compare_periods` lists every fact used in `inputs`, and each metric's own in
`components[metric]["inputs"]`.

`result.to_frame()` turns the inputs into a pandas DataFrame, one row per fact, with the columns
`metric`, `period`, `value`, `currency`, `source_id` and `reported_at`. The values stay `Decimal`, so
nothing is rounded on the way in. It needs pandas (`pip install "calcfinc[pandas]"`) and says so if it is
missing.

```python skip
g.to_frame()
#         metric  period  value currency  source_id reported_at
# 0      revenue  FY2025    100      USD          1  2025-11-01
# 1      revenue  FY2026    120      USD          2  2026-11-01
```

**To JSON.** `result.to_dict()` gives a JSON-safe dictionary in which every `Decimal` is an exact
string, never a JSON number, so nothing is rounded in transit:

```python
import json

d = r.to_dict()
d["value"]                       # -> 12.5
json.dumps(d)[:30]               # -> {"kind": "ratio", "name": "net
```

## 9. Checking your data

`check(entity)` tests the accounting identities that each period should satisfy: assets equal
liabilities plus equity, income less expenses equals profit before tax, current plus non-current
equals total, net profit plus other comprehensive income equals total comprehensive income. It
tolerates the larger of 1 currency unit or 0.05% of the figures involved, because filings round. A
failure is **reported, never corrected**.

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_records([
    {"entity": "X", "metric": m, "period": "FY2026", "value": v, "currency": "USD"}
    for m, v in (("total_assets", "100"), ("total_liabilities", "60"), ("total_equity", "30"))])
result = eng.check("X")[0]
result.needs_review          # -> True
result.failed                # -> ['assets_eq_liabilities_plus_equity']
```

`check_periods(entity)` asks, for each year with four single quarters, whether the quarters add
up to the year for every amount (not per-share figures). It is the quickest way to find a restated
year sitting beside unrestated quarters:

```python
from calcfinc import FinancialEngine

rows = [{"entity": "Q", "metric": "revenue", "period": f"FY2026Q{n}", "value": str(v), "currency": "USD"}
        for n, v in enumerate((100, 110, 120, 130), 1)]
rows.append({"entity": "Q", "metric": "revenue", "period": "FY2026", "value": "470", "currency": "USD"})
eng = FinancialEngine.from_records(rows)
eng.check_periods("Q")[0].failed             # -> ['quarters_sum_eq_year:revenue']
```

Real statements fail some identities for real reasons: regulatory deferral balances, redeemable
minority interests, discontinued operations. A failure means "look", not "wrong".

## 10. Banks and insurers

Several generic ratios describe an operating business and mislead for a financial company. A
large US bank, run through the generic definitions, showed an interest cover of 1.76, an EBIT
margin of 39.8% and debt/equity of 0.18, none of which means what it means for a manufacturer.
For a bank, calcfinc returns `None` with the reason instead:

```python
from calcfinc import FinancialEngine

facts = {"revenue": "650", "pbt_before_exceptional": "100", "finance_costs": "250", "net_profit": "80",
         "total_equity": "400", "total_assets": "8000", "borrowings_noncurrent": "200"}
rows = [{"entity": "Corp", "metric": m, "period": "FY2026", "value": v, "currency": "USD"}
        for m, v in facts.items()]

corp = FinancialEngine.from_records(rows)
corp.get_ratio("Corp", "interest_coverage").value          # -> 1.4

bank = FinancialEngine.from_records(rows, sector="bank")
r = bank.get_ratio("Corp", "interest_coverage")
r.value                                                    # -> None
print(r.limitations[0])
bank.get_ratio("Corp", "roe").value                        # -> 20
```

The same figures, declared a bank, keep ROE (which is meaningful) and lose interest cover.

**How an entity becomes a bank or an insurer.** Declare it: `sector="bank"` or `"insurer"` when
loading, or `Entity(..., sector=...)`. If you declare nothing, calcfinc infers it:

- a **bank** reports `bank.interest_earned` and `bank.interest_expended` together with
  `bank.deposits`, `bank.advances` or `bank.gross_advances`;
- an **insurer** reports `insurance.net_earned_premium`.

Any other declared sector (for example `"corporate"`) switches the inference off. The adapters
supply these lines for filings that carry them.

**What is held back.** Everything built on a held-back ratio is held back too.

| Sector | Held back | Kept |
|---|---|---|
| bank | EBIT, EBITDA, interest cover, margins and ROCE built on them; total debt and every debt ratio and EV built on it; current, quick and cash ratios; gross margin, turnovers and days; free cash flow, cash conversion, capex ratios | ROE, ROA, `roa_avg`, equity multiplier, DuPont, per-share and valuation ratios, everything under `bank.*` |
| insurer | current, quick and cash ratios; gross margin, turnovers and days; free cash flow, cash conversion, capex ratios | debt ratios and interest cover (insurers borrow), ROE, ROA, everything else |

**Insurers from the SEC feed.** US insurers' premiums earned, claims incurred and net investment income
are mapped, so the loss ratio and the investment income ratio work. No concept is a filer's total
underwriting expense, so it is derived: total benefits, losses and expenses less claims incurred, marked
`derived` with that reason. It is therefore an upper bound that also holds interest expense, interest
credited to policyholders, policyholder dividends and other items inside the total. For a property and
casualty insurer the expense and combined ratios are close to the usual figures (Progressive 23.9% and
89.9% for 2025); for Chubb it reads higher than the company's own expense ratio, and for a life insurer
(MetLife: 45.6% and 145%) it is not an underwriting expense at all, and claims incurred holds
policyholder benefits, so the "loss ratio" reads as a benefit ratio. Compare it with the filing before
relying on it.

The exact list is in [ratios.md](ratios.md), under "not computed for". The bank ratios
(`bank.net_interest_margin`, `bank.credit_cost`, `bank.gross_npa_to_advances`, `bank.cost_to_income`
and others) follow the RBI forms, with labelled fallbacks where a filing lacks the preferred input.
`calculate()` still evaluates any formula you give it by hand.

## 11. Your own metrics and ratios

Register the inputs you report, then a formula over them. DSCR, for example, has no single
universal definition, so it is not built in. Define yours:

```python
from calcfinc import FinancialEngine, RatioSpec, StatementType, register_metric, register_ratio

register_metric("principal_repaid", "currency", StatementType.CASH_FLOW, label="Loan principal repaid")
register_ratio(RatioSpec(
    "dscr", "x", "(net_profit + depreciation + finance_costs) / (principal_repaid + finance_costs)",
    label="Debt service coverage"))

facts = {"net_profit": "80", "depreciation": "20", "finance_costs": "10", "principal_repaid": "40"}
eng = FinancialEngine.from_records(
    [{"entity": "Bakery", "metric": m, "period": "FY2026", "value": v, "currency": "GBP"} for m, v in facts.items()])

r = eng.get_ratio("Bakery", "dscr")
r.value          # -> 2.2
r.formula        # -> (net_profit + depreciation + finance_costs) / (principal_repaid + finance_costs)
```

**`register_metric(name, kind, statement_type, point_in_time=False, label="")`.** `kind` is
`currency`, `per_share`, `shares`, `x` or `pct`. Set `point_in_time=True` for a balance. Names are
`lower_snake_case`, optionally `namespace.name`. A typo in a data file is an error because the
metric must be registered.

**`RatioSpec(name, unit, formula, ...)`.**

| Option | Meaning |
|---|---|
| `unit` | `pct`, `x`, `currency`, `per_share`, `shares` or `days` |
| `optional=("x",)` | inputs that count as 0 when not reported, announced in `limitations` |
| `fallbacks=((formula, note), ...)` | tried in order when the primary cannot be computed; the note is added to the result |
| `requires_positive=("x",)` | inputs that must be above 0, else `None` with a reason |
| `label`, `version` | text for the reference page; bump `version` when you change a definition |

**The formula language** is deliberately tiny: numbers, `+ - * / **`, parentheses, names (including
dotted ones such as `bank.advances`), and the functions `abs`, `min`, `max`, `round`, `sqrt`,
`prior(x)` and `ttm(x)`. There is no `//` or `%`, no strings, no attributes, no calls to anything
else, and a formula is limited to 2000 characters. Anything else raises `CalcError`. Number
literals are read as text, so `0.1` is exactly one tenth.

- `prior(x)` is `x` one comparable period earlier (adjacent: a gap means unavailable, not a guess).
- `ttm(x)` sums `x` over the periods that make a year; it is refused at registration for balances.
- `share_price` and `period_days` are built-in names.

Registration checks every name, so a ratio built on a mistyped metric fails at once, not
silently later. Registries are **process-wide**: register once at start-up.

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_records([])
eng.calculate("a / b * 100", a=1, b=8).value        # -> 12.5
eng.calculate("0.1 + 0.2").value                    # -> 0.3
print(eng.calculate("1 / 0").limitations[0])        # division by zero
```

## 12. Exact numbers

- Pass numbers as `int`, `str` or `Decimal`. A `float` raises `TypeError` (`LoadError` when it is
  in a file row) with a message telling you how to write it.
- At most **34 significant digits** and an exponent between -999 and 999. Larger values are
  refused, not rounded.
- Every operation is performed once, correctly rounded to 34 digits, half-even, in a private
  decimal context: your program's own `decimal` settings cannot change a result. Sums,
  differences and products are exact whenever they fit in 34 digits (every realistic figure);
  division and powers carry at most half a unit in the 34th digit.
- Storage keeps decimals as text, so nothing passes through a float on the way to or from disk.
- Use `to_dict()` for JSON. Round only when you display:

```python
from decimal import Decimal

from calcfinc import FinancialEngine

eng = FinancialEngine.from_records([
    {"entity": "A", "metric": "revenue", "period": "FY2026", "value": "3", "currency": "USD"},
    {"entity": "A", "metric": "net_profit", "period": "FY2026", "value": "1", "currency": "USD"}])
margin = eng.get_ratio("A", "net_profit_margin").value
margin.quantize(Decimal("0.01"))             # -> 33.33
```

## 13. Source adapters: SEC and Indian filings

Adapters read one source's conventions and produce facts. The core never imports an adapter.
Full details, including what each does and does not do, are in [adapters.md](adapters.md); the
essentials follow.

**SEC `companyfacts` (US-GAAP filers, and IFRS filers of 20-F and 40-F).** Download once, keep the file, load it:

```python skip
from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import sec_companyfacts as sec

raw = sec.fetch_companyfacts(320193, "Your Name your.name@example.com")   # the only network call
open("CIK0000320193.json", "wb").write(raw)

repos = SqliteRepositories(":memory:")
sec.load_companyfacts(repos, sec.read_companyfacts("CIK0000320193.json"), ticker="AAPL")
eng = FinancialEngine(repos)
eng.get_ratio("AAPL", "roe", period="FY2025")
```

- The SEC's fair-access guidance asks for a declared User-Agent with a **real contact** (there is no
  default), at most 10 requests per second (the helper keeps to 5 and never retries), and downloading once.
- Periods are matched on exact start and end dates; the filing's own `fy` and `fp` labels are never
  trusted. The fiscal year end is inferred from the 10-K year ends.
- The SEC reports no stand-alone fourth quarter, so it is derived (year less nine months), and
  year-to-date cash flows become single quarters. Derived facts are marked as such.
- Restatements are kept as versions dated by their filing.
- Trailing-twelve-month figures in 10-Qs are not mistaken for fiscal years.
- IFRS filers (`ifrs-full`) load in their own currency; their quarters, where they report them, come
  from 6-Ks. An IFRS bank is declared a bank (its `bank.*` lines are not mapped); an IFRS 17 insurer
  is named in a note and not mapped.

**Indian exchange XBRL filings.** One `.xbrl` file, or many:

```python skip
from calcfinc import FinancialEngine, SqliteRepositories
from calcfinc.adapters import ind_as_xbrl

repos = SqliteRepositories(":memory:")
ind_as_xbrl.load_xbrl_files(repos, ["30-Jun-2025_Original_Consolidated.xbrl",
                                    "30-Jun-2025_Revision_Consolidated.xbrl"], entity="ACME")
eng = FinancialEngine(repos)
eng.get_ratio("ACME", "india.roe", period="latest_annual")
```

- April-March year, INR, base units. The basis comes from the file name or `basis=`.
- `load_xbrl_files` loads each "Revision" after its "Original", so the correction wins.
- Zeros that mean "not applicable" (a consolidated bank's NPA block) are not loaded as zeros.
- `india.*` ratios give the Schedule III / ICAI forms where they differ from the generic ones;
  each one's meaning is in [ratios.md](ratios.md).

## 14. Running it for real

**Persistence.** Use a `SqliteRepositories` file (section 5). Apart from turning foreign keys on,
SQLite's defaults are left alone. For several readers, open one connection per thread or process.

**Threads.** An engine and its repositories belong to the thread that created them (SQLite's rule).
Give each thread its own `SqliteRepositories` on the same database file. Registries are shared
process-wide and are safe to read concurrently; register everything before you start threads.

**Performance.** About 20,000 rows per second to load; 91,000 facts (50 companies, 26 years of
quarters, 14 metrics) load in about four seconds and use under 100 MB. After the first question about
an entity (which builds its period records, about 0.1 s for 26 years of quarters), further ratios
cost well under a millisecond each. Everything is in memory unless you use a file database.

**Logging.** calcfinc logs through the standard `logging` module under the name `calcfinc` and
adds no handlers. It warns when loading a fact overwrites a different value for the same key (for
example a corrected filing); enable it with `logging.basicConfig(level=logging.WARNING)`.

**Security.**
- Formulas are parsed with Python's `ast` and evaluated by a small interpreter of the grammar in
  section 11. Nothing is ever passed to `eval`. Hostile input (deep nesting, huge exponents, attribute
  access) is refused with a `CalcError`.
- All SQL uses bound parameters.
- Indian XBRL is parsed with the standard library's XML parser, which does not fetch external
  entities. For a file you do not trust, parse it yourself with a hardened parser and pass the rows
  to `map_facts`.
- The only code that can use the network is `sec_companyfacts.fetch_companyfacts`; a test fails
  if anything else imports a networking module.

**Reproducibility.** The same facts always give the same answer, on any machine and Python version,
and a result names the definition version it used. Pin `calcfinc` in your own requirements and read
the changelog before upgrading: a definition change bumps `definition_version`.

**Stability.** This is version 0.1, beta. The names in `calcfinc.__all__` and the methods of
`FinancialEngine` are the public API; within 0.x a change to them is announced in
[CHANGELOG.md](../CHANGELOG.md). Ratio *definitions* may be corrected between releases when a
regulator's definition is clarified; they are versioned.

## 15. What has and has not been verified

The library is covered by about 300 tests with hand-computed expected values (not read back from
the code), plus a test that fails if a ratio gives a number instead of a reason on empty or zero
data. Beyond that, the adapters were run on real filings kept outside the repository:

- **Indian XBRL:** 2,938 raw filings of 50 companies parsed; the output of the earlier pipeline
  this was extracted from matched on 138,313 fields, and facts matched its database on 22,293
  overlaps. Twenty companies (five banks, two insurers, two finance companies) were then run end
  to end.
- **SEC:** 19 filers (Apple, Microsoft, JPMorgan, Wells Fargo, Citigroup, Goldman Sachs, MetLife,
  Walmart, Costco, Amazon, NVIDIA, Alphabet, Exxon, Johnson & Johnson, Caterpillar, Duke, Prologis,
  Coca-Cola, AT&T). Revenue and net income matched the published figures for every one checked.
  Later runs added four US insurers (Progressive, Chubb, Travelers, Allstate) and five IFRS filers
  of 20-F and 40-F (Infosys, Novo Nordisk, SAP, Shell, Royal Bank of Canada).
- **Point in time:** on 14 real restated annual figures (Boeing, JPMorgan, Progressive, Chubb, Allstate,
  Royal Bank of Canada, Wells Fargo, Johnson & Johnson, AT&T, Citigroup, MetLife, Duke and others), a
  view the day before the restating filing gave the old figure and the filing's day gave the new one.

That testing found and fixed a long list of real-world defects (documented in
[adapters.md](adapters.md)), which is the reason to trust the pattern more than the count.

**Not verified or not covered:** IFRS 17 insurers, IFRS bank lines (`bank.*`) and IFRS filings read
from XBRL files rather than the SEC feed; filers that report half-years only; SEC insurers' underwriting
expense net of interest and policyholder items; REITs and utilities beyond one example each; banks other than the ones above (US bank
concepts were checked on one bank); the Python 3.11 and 3.13 interpreters locally (CI runs them). Unknown
concepts in a filing are left unmapped, never guessed, so a new filer may show missing metrics.
**Restatement vintages:** when a company recasts only some figures, a period can combine figures
from different filings; the result says so, `check_periods()` finds it, and `as_of` shows what was
known on a date.

## 16. Troubleshooting

**`value` is `None` and I don't know why.** Read `result.limitations[0]`. It names the missing
input and the period, for example `net_profit not reported [FY2026 Q4]`.

**`latest` gives `None` but last year works.** The newest period lacks an input. Ask for the year
you want (`period="FY2025"`) or use `fallback=True`.

**"unknown metric 'x'".** The name is not registered. Check [ratios.md](ratios.md), or
`register_metric` it (section 11). Suggestions for near misses are included in the message.

**`LoadError: nothing was loaded`.** One or more rows are bad; `e.errors` lists each with its row and
column. Fix them all and reload.

**A float was refused.** Write the number as a string (`"12.50"`) or `Decimal`. For DataFrames pass
`float_policy="repr"` if the cells are already floats and you accept their shortest text form.

**An amount was refused for lack of a currency.** Give the fact a `currency`, or set the entity's
default with `currency=` when loading.

**A ratio is `None` for a bank or an insurer with "does not apply".** It is held back on purpose
(section 10). Use the `bank.*` ratios, or declare `sector="corporate"` if the entity is not a
financial company.

**Identity checks fail on a real company.** See section 9; many real statements legitimately fail
one or two. Read which identity and compare with the filing.

**`ProgrammingError: SQLite objects created in a thread...`.** Open a repository per thread
(section 14).

**Results differ from a figure on the company's website.** Companies publish adjusted and
unadjusted numbers, and a restated figure replaces an original. Check `result.inputs[...]
.reported_at` and the `limitations` for a vintage note.

## 17. Reference

**Top level (`import calcfinc`)**: `FinancialEngine`, `EngineResult`, `FactRef`, `CheckResult`,
`EngineError`, `Entity`, `FinancialFact`, `Segment`, `SegmentFact`, `SharePrice`, `Source`, `Basis`,
`StatementType`, `MappingConfidence`, `PeriodWindows`, `RatioSpec`, `register_metric`,
`register_ratio`, `SqliteRepositories`.

**`FinancialEngine`**

```text
FinancialEngine(repos, windows=PeriodWindows(), as_of=None)
FinancialEngine.from_csv(path, **options)        FinancialEngine.from_records(rows, **options)
FinancialEngine.from_dataframe(df, layout="long", float_policy="refuse", **options)
  options: entity, currency, basis, fiscal_year_end_month, sector, windows, entity_kind
.get_metric(entity, metric, basis=, period="latest", fallback=False)
.get_ratio(entity, ratio, basis=, period="latest", fallback=False)
.get_valuation(entity, kind, basis=, period="latest_annual", fallback=False)
.get_growth(entity, metric, kind="yoy", basis=)      .get_cagr(entity, metric, basis=, years=None)
.compare_periods(entity, metrics, basis=, a=, b=)     .compare_companies(metric, entities, basis=, period=)
.decompose_metric(entity, metric, basis=, period=)    .calculate(expr, **vars)
.check(entity, basis=, period=None)                   .check_periods(entity, basis=)
.get_segment_data(entity, basis=, period=)            .segment_growth(entity, basis=, kind="yoy")
.periods(entity, basis=)   .available_metrics(entity, basis=)   .refresh()   .repos
.as_of(date_or_iso_text)       a view of the data as known on that date (a new engine)
```

**Errors.** `EngineError` (a `ValueError`): unknown entity, unrecognised period, unusable argument.
`LoadError` (a `ValueError`): bad rows, with `.errors`. `CalcError` (a `ValueError`): a bad
formula. `ValueError`/`TypeError`: a bad value (a float, a NaN, too many digits). A figure that cannot
be computed is never an exception; it is `value=None`.

**Where to look next.** [ratios.md](ratios.md) lists every ratio and metric with its formula;
[fact-schema.md](fact-schema.md) the data format; [adapters.md](adapters.md) the SEC and Indian
adapters and the real-data results; [../examples](../examples) seven runnable scripts.

*Results are calculations, not investment advice.*
