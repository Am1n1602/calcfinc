# Changelog

All notable changes are listed here. The project follows [semantic versioning](https://semver.org/);
while the version is 0.x, a minor release may change the public API, and any such change is listed
under "Changed". A change to a built-in ratio definition raises its `definition_version`.

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
