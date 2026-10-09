# Changelog

All notable changes are listed here. The project follows [semantic versioning](https://semver.org/);
while the version is 0.x, a minor release may change the public API, and any such change is listed
under "Changed". A change to a built-in ratio definition raises its `definition_version`.

## 0.1.2 - 2026-10-09

Makes the project easier to try: a result's audit trail as a DataFrame, a tour notebook for Colab with a real
Apple and a real TCS example, and a README built around them. No change to any calculation.

### Added

- `EngineResult.to_frame()`: the facts behind a result as a pandas DataFrame, one row per fact, with
  values kept as exact `Decimal`s (needs the `pandas` extra).
- A tour notebook, `examples/calcfinc_tour.ipynb` (with an "Open in Colab" badge), that runs on built-in
  sample data, including five made-up Indian exchange filings, an optional live Apple download, and a real
  Indian company: two unmodified public TCS result filings in `examples/data/tcs` (GitHub only; neither the
  wheel nor the source distribution carries them). The test suite runs everything except the live Apple cells.

### Changed

- The release workflow now goes build, TestPyPI, an install check from TestPyPI, a manual approval, and
  then PyPI.
- README reworked around a real Apple example and a real TCS example, each with its audit trail.
- The SEC download guidance in the docs now says what the SEC actually says (it asks automated clients to declare
  a real contact and "manages" those that do not), not that requests are refused.
- Ruff checks notebooks too; the source distribution leaves out the third-party TCS sample filings.

## 0.1.1 - 2026-10-09

Fixes found by a live provenance test, three rounds of code review, and live runs on six more real
companies (Apple, Microsoft, JPMorgan, TCS, Infosys and Reliance again; Tesla, Boeing, HCLTech and
Titan new). If you save data in a database file, note the schema version under "Changed".

### Fixed

- `get_growth`, `get_cagr` and `compare_periods` now return the facts they were computed from, each
  with its own source, filing date and currency. Before, `get_growth` and `get_cagr` listed their two
  inputs with `source_id=None` and no report date, and `compare_periods` listed no inputs at all.
  For a ratio (growth of a margin, say) the inputs are the underlying facts of each period, not a
  stand-in named after the ratio. A mixed-vintage warning and any source review flags now appear in
  `limitations` for these results too. A metric or period that does not exist still gives `None`
  with its old reason and no invented inputs.

- `get_cagr` explains a `None` caused by a non-positive end value or span.
- `get_growth`, `segment_growth` and the net-margin bridge refuse to compare periods that are not
  consecutive, instead of reporting a multi-year change as year-on-year; the bridge also says when
  it cannot be built, and `compare_companies` says when entities are ranked on different periods.
- Loading SEC data into an entity that already exists now applies the fiscal year end found in the
  filings (or the one you pass) instead of keeping a constructor default of 12; a wrong explicit
  year end no longer crashes the parser.
- `sector=` now applies to an entity that already exists.
- A not-reported fact can no longer erase a stored value at the same key.
- Loading facts no longer runs one extra query per fact (it reads only the metrics a batch touches,
  so many small batches stay fast), and period lookups no longer compare records field by field.
- The net-margin bridge no longer reports a revenue effect when revenue did not move: the revenue
  effect holds every cost, tax and other item at its prior amount.
- SEC loading keeps an existing entity's fiscal year end when the filings have no full-year figures
  (nothing could be inferred).
- Indian XBRL numbers: free text such as "Rs 500 crore" is no longer read as 500, and a value the
  library cannot hold is skipped instead of aborting the whole filing.
- Review flags and derivation notes are matched to the period each input fact belongs to, so a flag
  on an earlier period's input (through `prior()` or `ttm()`) is no longer missed or misattributed.
- `segment_growth` rejects an unknown `kind`, and `"yoy"` no longer silently means quarter on quarter.
- The SEC parser reads the currency a concept is reported in most often, not USD whenever present.
- `roe`, `roe_avg`, `roe_ttm`, `india.roe`, `debt_to_equity`, `debt_to_capital`, `net_debt_to_equity`
  and `equity_multiplier` return `None` with a reason when equity is not positive, instead of a
  confidently signed but meaningless number (a loss over negative equity read as a positive return).
  Their `definition_version` is now 2.
- The SEC parser reads one currency for all of a filer's metrics (the one it reports most in overall),
  so cross-metric ratios are not blocked by a concept that also carries a few translated figures.
- A saved database now records its schema version: a file made by an earlier release is upgraded when
  opened (it gains the `sector` column), and a file from a newer release is refused with a clear message.
- `fetch_companyfacts` keeps its request spacing correct when called from several threads.
- Indian XBRL: profit to owners and to minorities both reported as exactly 0 beside a non-zero profit
  (arithmetically impossible, seen in 125 records of 20 companies) are treated as not reported, so a
  filing's annual figure is no longer 0 where its quarters are not.
- Review flags are checked on every record sharing a period label, so two periods with the same label
  cannot hide each other's flags.

### Changed

- Definition versions: `roe`, `roe_avg`, `roe_ttm`, `india.roe`, `debt_to_equity`, `debt_to_capital`,
  `net_debt_to_equity` and `equity_multiplier` are now version 2 (they refuse non-positive equity).
- A database file now carries a schema version (`PRAGMA user_version = 1`). Files from 0.1.0 open
  and are upgraded in place; a file written by a newer release is refused with a clear message.
- `segment_growth(kind="yoy")` uses annual data only; the old quarterly fallback is gone.
- `compare_periods` results have `inputs` (all facts used) and, for each metric,
  `components[metric]["inputs"]`. Existing keys are unchanged.

## 0.1.0 - first release

### What it is

An exact-decimal engine that turns periodic statements into ratios, growth, CAGR, valuation,
DuPont, trailing twelve months and segment attribution, with the formula, the input facts and the
limitations on every result. No runtime dependencies; Python 3.11 to 3.13.

### Added

- `FinancialEngine` with `get_metric`, `get_ratio`, `get_valuation`, `get_growth`, `get_cagr`,
  `compare_periods`, `compare_companies`, `decompose_metric`, `calculate`, `check`, `check_periods`,
  segment queries, and loaders for CSV (long and wide), records and pandas DataFrames.
- More than a hundred ratios and derived quantities as formula strings in an open registry
  (`register_metric`, `register_ratio`); trailing-twelve-month forms through `ttm(x)`; average
  balances through `prior(x)`; a restricted Decimal formula language.
- Definitions reconciled across ACCA, the FTC Quarterly Financial Report, MCA/ICAI, RBI and SEBI,
  with the Indian forms as `india.*` and RBI-form bank ratios (`bank.*`).
- Sector handling: ratios that do not describe a bank or an insurer return `None` with the reason;
  sector is declared or inferred from the facts.
- Source adapters: SEC `companyfacts` (exact periods, restatement versions, derived fourth
  quarters, US bank lines, a polite download helper) and Indian exchange XBRL (Ind-AS), tested on
  19 US and 20 Indian companies' real filings.
- Restatements kept as versions by `reported_at`; each input of a result carries it; a result warns
  when one period's inputs come from filings far apart.
- A SQLite store that keeps every value as exact decimal text.
- A manual whose examples are run by the test suite, and a ratio reference generated from the code.

### Changed

Nothing: this is the first release.

### Known limitations

- Point-in-time views (`as_of`) for restated data are not implemented.
- IFRS filers, SEC insurers and 20-F/40-F filers are not mapped.
- EBIT is `profit before exceptional items + finance costs`, so it includes non-operating gains.
- LLM function-calling schemas and an MCP server are planned for a later release.
