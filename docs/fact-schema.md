# Fact schema

A *fact* is one reported figure for one entity, metric, period and basis. Everything calcfinc
computes is derived from facts, and every result lists the facts it used.

## Rules that apply everywhere

- **Numbers are exact.** Pass `int`, `str` (`"12.50"`) or `Decimal`. A `float` is refused,
  because `0.1` as a float is not 0.1. Values may have at most 34 significant digits.
- **Base units only.** Give 1200000, not "1.2 million". Scale in your loader or adapter, where it
  can be done exactly.
- **Missing is missing.** An empty value is stored as "not reported". It is never 0, and a ratio
  whose input is missing returns `None` with the reason.
- **Currency is on the fact** (ISO 4217, e.g. `USD`) for amounts and per-share figures. Ratios,
  percentages and share counts have none. A missing currency is filled from the entity's default;
  an amount with neither is rejected.
- **Consolidated and standalone are separate bases** and are never substituted for each other.
- **Restatements are kept.** Two facts for the same period that differ only in `reported_at` are
  both stored; the engine uses the latest-reported one.

## Fields

| Field | Meaning |
|---|---|
| `entity` | Name, alias or identifier value (ticker, ISIN, CIK, LEI...) of the entity. |
| `metric` | A registered metric: the generic core, `bank.*`, `insurance.*`, or your own via `register_metric`. A typo is an error, not a silent miss. |
| `value` | The figure (see above). |
| `period` | `FY2026`, `FY2026Q1`, `2026-03` (a month), `2026-01-01..2026-12-31`, or `2026-12-31` (a single date, for balance-sheet items). Fiscal labels follow the entity's year end; `FY2026` is the year *ending* in 2026. |
| `period_start`, `period_end` | Alternative to `period`: explicit ISO dates. `period_start` is needed for flow metrics (income statement, cash flow) and ignored for balance-sheet items. Both ends are included, so a calendar year is `01-01` to `12-31`. |
| `currency` | ISO code. Optional if the entity has a default. |
| `basis` | `consolidated` (default) or `standalone`. |
| `reported_at` | ISO date the figure was published. Optional. |
| `source` | Free text naming where the figure came from (a filing, a report). Optional; a CSV file is also recorded automatically by its content hash. |
| `mapping_reason` | Why a value is missing or was mapped unusually. Shown as a review limitation. |

**Inferred unless you override.** `statement_type` and whether a metric is a balance-sheet
instant come from the metric registry. `financial_year`, `quarter` and `is_annual` come from the
dates and the entity's fiscal year end. Provide the column to override any of them.

## CSV layouts

**Long**: one row per fact.

```
entity,metric,period,value,currency
Acme,revenue,FY2026,1200,USD
Acme,net_profit,FY2026,150,USD
```

**Wide**: one row per metric, one column per period (the entity and currency come from the
call, or from an `entity` column).

```
metric,FY2025,FY2026
revenue,1000,1200
net_profit,100,150
```

An empty cell in a wide file means "no data" and creates nothing; an empty `value` in a long file
is an explicit "not reported" fact. The layout is detected from the header, and a file with any
bad row loads nothing: every problem is reported with its line and column.

```python
from calcfinc import FinancialEngine

eng = FinancialEngine.from_csv("acme.csv", entity="Acme", currency="USD")
eng.get_ratio("Acme", "roe")
```

## Other sources

- `FinancialEngine.from_records(rows, ...)` takes dicts with the long-layout keys.
- `FinancialEngine.from_dataframe(df, layout="long" | "wide", ...)` takes a pandas frame. Float
  cells are refused unless you pass `float_policy="repr"`, which converts each through its
  shortest text form and records how many were converted.
- For your own storage, implement the protocols in `calcfinc.store.base` and pass them to
  `FinancialEngine(repos)`.

## Results

Every call returns an `EngineResult`: `value` (a `Decimal` or `None`), `unit`, `currency`,
`formula` (the formula that was actually used), `inputs` (each fact with its period, source and
currency), `limitations` (substitutions made and reasons for `None`), and `definition_version`.
`result.to_dict()` gives a JSON-safe form in which numbers are exact strings.

*These are calculations, not investment advice.*
