# Source adapters

An adapter reads one source's tags and conventions and produces calcfinc facts. The core never
imports an adapter, and an adapter never changes how a ratio is computed.

| Adapter | Source | Notes |
|---|---|---|
| `calcfinc.adapters.ind_as_xbrl` | Indian exchange XBRL filings (.xbrl file, raw fact rows, or canonical records) | April-March year, INR, `india.*` ratios |
| `calcfinc.adapters.sec_companyfacts` | The SEC's public `companyfacts` JSON | US-GAAP filers, US insurers, and IFRS filers of 20-F and 40-F |

## Ind-AS XBRL

```python
from calcfinc.adapters import ind_as_xbrl
ind_as_xbrl.load_xbrl_file(repos, "results_consolidated.xbrl", entity="ACME")
```

- Three entry points, one per stage: `load_xbrl_file` (a filing), `load_raw_facts` (rows from
  `parse_xbrl_file`), `load_canonical` / `load_canonical_file` (records already mapped to names).
- The file's basis comes from its name (`consolidated` or `standalone`), or pass `basis=`.
- Only whole-company contexts are read (`OneD`, `OneI`, `PY_D`...). Segment and note breakdowns
  are ignored. Filings that tag the older `in-bse-fin:` prefix are matched by local concept name.
- Some filers declare their reporting period as plain facts and leave the context without one;
  those are recovered. Banks that omit a start date get it worked out from the financial year and
  the quarter label, and only when that agrees with the declared end.
- Numbers are parsed from the filing's text straight to `Decimal`. Indian formatting, accounting
  negatives and a `sign="-"` attribute are handled.
- Bank totals (equity, cash, liabilities) are built from their parts only when every part is
  present; a reported total always wins.
- **A record whose own arithmetic fails still loads**, but each of its facts carries a review
  reason (`source record failed arithmetic checks: ...`) and the report lists the period.
- **Zeros that mean "not applicable" are not loaded.** Real filings report an exact 0 where a
  figure does not apply: a consolidated bank filing gives 0 for its whole NPA block (gross and net
  NPA, both ratios, ROA, CET1, AT1); paid-up capital, face value and CET1 are never genuinely 0;
  a coverage ratio of exactly 0 is a placeholder. Stored as numbers they would give a 0% NPA ratio
  instead of "not reported". The block rule needs all four NPA figures to be zero together, so a
  real zero (no exceptional items, no borrowings, no minority interest) is kept. Dropped names are
  listed in `report.skipped`; pass `placeholder_zeros=False` to keep every zero.
- **Two contexts that contradict each other.** A cumulative context can carry the quarter's own
  dates with different values, and a context can carry a stale prior-year balance. The current
  period's context (`OneD`/`OneI`, then `TwoD`..., then `PY_`) wins, the winner's fact is flagged
  with what the other context said, and `report.conflicts` lists each one. The store never
  decides by load order.
- `paid_up_equity_capital / face_value_per_share` becomes a `shares_outstanding` fact marked as
  derived, so valuation works.
- The XML is read with the standard library, which does not fetch external entities. For a file
  you do not trust, parse it with a hardened parser and use `map_facts`.
- Pass `reported_at=` (the filing date) so a later revised filing is kept beside the original
  instead of overwriting it.
- **Original and Revision filings** carry the same board-meeting date and no filing date, so the
  file cannot say which is later. Without `reported_at` a later load overwrites an earlier one for
  the same period. `load_xbrl_files(repos, paths, entity=...)` loads every "Revision" after its
  "Original" whatever order you give, so the correction wins. (19 revisions exist in the
  author's 2,960 files; most have no original beside them.)

## SEC companyfacts

```python
from calcfinc.adapters import sec_companyfacts as sec
data = sec.read_companyfacts("CIK0000320193.json")      # a file you downloaded once
sec.load_companyfacts(repos, data, ticker="AAPL")
```

- **Periods are matched on exact start and end dates.** The `fy` and `fp` fields in the JSON
  describe the filing, not the period a figure covers, so they are never used to place a number.
- **Tag choice is per period.** For each metric, the first concept in `tags.CANDIDATES` that the
  filer reported for that exact period wins, and a lower-priority concept is flagged
  `alternate_tag` in the fact's mapping reason. Filers change concepts over time, so the choice is
  never made once for a whole history.
- **Restatements are kept.** A figure that changes in a later filing becomes a second version with
  `reported_at` set to that filing's date; the engine uses the latest, and `engine.as_of(date)` the
  one known on a date. A later filing that merely repeats a comparative figure adds nothing.
- **The fourth quarter is derived.** The SEC reports no stand-alone Q4, so it is the year less the
  nine-month figure (or less the three reported quarters). Cash-flow statements, which are
  reported year-to-date only, become single quarters the same way. Derived facts are marked
  `derived` with the arithmetic in the reason. This is what makes trailing-twelve-month ratios
  work for SEC filers. A derived quarter has one version for each filing that changed its inputs
  (a year restated in a later 10-K gives a second Q4), so a view as of a date between the two still has
  the quarter; a quarter that a later recast filing reported itself is also derived for the dates before it.
- **Only currency amounts are derived.** Per-share figures are not additive, so a Q4 EPS is never
  invented.
- **Every fact points to its filing.** Each accession number becomes a source with the form and
  the filing URL, so `result.inputs[...].source_id` leads back to the document.
- The fiscal year end is inferred from the full-year figures (a 52/53-week year ending on 1 Feb is
  a January year end). Pass `fiscal_year_end_month=` to override.
- Facts carrying a dimension are ignored; amounts are already in base units; only 10-K, 10-Q, 20-F,
  40-F and 6-K family filings are read (`forms=` to change). 8-Ks are ignored.
- **Neither US GAAP nor IFRS has an exceptional-items line**, so `pbt_before_exceptional` is set equal
  to pre-tax income, marked `derived`, so EBIT-based ratios work.
- **IFRS filers (`ifrs-full`).** The IFRS concepts follow the US ones in each metric's candidate list.
  A 20-F or 40-F filer gives annual statements in its own currency, and quarters from its 6-Ks where it
  tags them (Shell and Royal Bank of Canada do; SAP, Infosys and Novo Nordisk give years only, and a
  trailing twelve months is then the latest year). Only clean concepts are read: trade *and other*
  receivables and payables are not trade receivables and payables, lease liabilities are not debt,
  and the combined purchase of PP&E and intangibles is not capex. Earnings per share is the filer's total EPS concept only: continuing-operations EPS is not taken for it,
  so a filer without total EPS gets EPS derived from profit over shares, with a note. A filer that tags `DepositsFromBanks` or
  `DepositsFromCustomers` is declared a bank (generic ratios withheld, interest expense not read as a finance
  cost, `bank.*` not mapped). A filer that tags `InsuranceRevenue` is named an IFRS 17 insurer in a
  note: insurance revenue is not earned premium, so `insurance.*` is not mapped.
- **US insurers.** `PremiumsEarnedNet` (or its property and casualty form), policyholder benefits
  and claims incurred (or incurred claims of a property and casualty insurer) and net investment income
  are mapped, only for a filer that reports premiums earned, is not a bank (large banks tag premiums
  too) and earns at least half its revenue from them (a manufacturer with a captive insurer tags them on a
  few percent of sales; funds tag `NetInvestmentIncome`). No concept is the total underwriting expense
  (acquisition cost amortization and other underwriting expense are tagged apart), so it is
  `BenefitsLossesAndExpenses` less claims incurred, for each period and each version of it, marked
  `derived`. It also holds interest expense, interest credited to policyholders and policyholder
  dividends, so it overstates the expense of a life insurer badly (MetLife) and a multi-line insurer
  somewhat (Chubb). Some insurers tag
  their claims with a company-specific concept that the SEC feed does not carry (Allstate since 2024),
  so their loss ratio is `None` for those years.

### Downloading, politely

`fetch_companyfacts` is the only function in calcfinc that can use the network, and nothing else
calls it. The SEC's [fair access guidance](https://www.sec.gov/os/accessing-edgar-data) asks for, and says
it will "manage" automated clients that ignore:

- a declared User-Agent that identifies you with a real contact (there is deliberately no default, and
  calcfinc will not invent an identity for you; use your own, or a mailbox you create for the project);
- at most 10 requests per second (the helper keeps to 5 and never retries by itself);
- downloading once and keeping the file; the data changes only when a company files.

```python
raw = sec.fetch_companyfacts(320193, "Jane Doe jane@example.com")
open("CIK0000320193.json", "wb").write(raw)
```

## What is and is not verified

- Tests use synthetic data written for the test, and no test uses the network. The one exception is
  `examples/data/tcs`: two unmodified public TCS result filings, used by the tour notebook and by one test
  that checks the figures against the filings. They are not part of the installed package.
- **Ind-AS, checked on real filings outside the repository** (the installed wheel, in a separate
  environment, reading the author's earlier extraction output read-only): 2,938 raw `.xbrl`
  filings were parsed and mapped, and compared with the earlier pipeline's output for the same
  filing: 138,313 fields, all identical. Facts from the canonical files were compared with the
  earlier database for eight companies: all 22,293 overlapping facts matched exactly. The
  comparison is what found the placeholder zeros and the contradicting contexts above. It also
  showed that the earlier database stored a 6-month cash-flow figure under the 3-month quarter
  for one filing; this adapter does not.
- **SEC, checked live** (the installed wheel, in a separate environment, downloading with
  `fetch_companyfacts`): Apple, Microsoft and JPMorgan companyfacts, 3.8-8.0 MB each, loaded in
  about 0.2 s each.
  - The fiscal year end was inferred correctly for all three (Apple's 52/53-week September year,
    Microsoft's June, JPMorgan's December).
  - Revenue and net income matched published figures to the dollar for all seven company-years
    checked (reference values written from memory, so a mismatch would have been investigated, not
    trusted).
  - The four quarters, with Q4 derived, added up to the reported year in 65 of 68 tests; the three
    that did not are restatement-vintage cases (below).
  - That run found and fixed: a quarter whose start date differed by a day between a filing and its
    recast (a duplicate period); a bank's quarterly revenue concept missing from the list; a safety
    rule that wrongly blocked deriving Q4 for a bank that reports one quantity under two concepts;
    and an "alternate concept" flag that fired on filers that only ever use the second-choice
    concept.
- **A second, broader run** (19 US filers: Apple, Microsoft, JPMorgan, Wells Fargo, Citigroup,
  Goldman Sachs, MetLife, Walmart, Costco, Amazon, NVIDIA, Alphabet, Exxon, Johnson & Johnson,
  Caterpillar, Duke, Prologis, Coca-Cola, AT&T; and 20 Indian companies, 5 of them banks, with
  about 600 consolidated filings) found and fixed: `latest` landing on an SEC cover-page date;
  Amazon's trailing-twelve-month 10-Q figures counted as fiscal years; Costco's 52/53-week years
  labelled a year late; MetLife and other non-banks receiving `bank.*` lines; Indian banks not
  recognised as banks; `paid_up_equity_capital` stored as a flow; and one filing whose declared
  reporting period had day and month swapped. After the fixes, revenue and net income matched
  published figures for all nine companies checked (written from memory; one differs by a
  minority-interest amount), every company loaded in about 1 s, and the quarters add up to the year
  for FY2019 onwards except where a company restated (ITC and Hindustan Unilever after demergers;
  HDFC Bank after its merger).
- Identity checks still fail on some real statements for real reasons: regulatory deferral balances
  (NTPC), redeemable minority interests and other temporary equity, minorities inside continuing
  profit (Citigroup, AT&T), and utilities' deferred-tax presentation (Duke). They report; they
  never correct.
- The candidate-concept list uses standard `us-gaap` names and has now met nineteen real filers, but
  not hundreds. Expect other filers to use concepts that are not in the list; those metrics are
  simply absent (never guessed), and the list is meant to be extended.
- **US banks.** Seven `bank.*` lines are mapped (interest income and expense, provisions, employee
  cost, deposits, gross loans, and net loans where tagged), and only for a filer that reports both
  `NoninterestExpense` and `Deposits`: insurers and industrials file `Deposits` and `InterestExpense`
  too, where they do not mean what `bank.*` means. Interest income less interest expense
  matched reported net interest income for every year checked on one large US bank (2010-2023). Not
  mapped, so their ratios return None with a reason: non-performing assets (the US "nonaccrual" is a
  different definition from the RBI's), CASA and interest-earning assets (not tagged), and "loans net
  of allowance" (that bank's value exceeded its own gross loans, so it cannot be trusted). Loan to
  deposit and credit cost therefore use gross loans, with a note; net interest margin uses total assets,
  with a note. Only one bank has been checked.
- **Restatement vintages.** The engine uses the latest-reported figure for each metric and period.
  When a company recasts only some figures (Microsoft's ASC 606 recast changed 2016 annual revenue
  and equity but not the 2016 quarters or total assets), a period can combine figures from
  different filings, and the four quarters need not add up to the year. The accounting-identity
  check (`engine.check()`) flags the balance-sheet cases; 6-8 periods per company were flagged in
  the live run and every one examined was this effect. Three aids exist: every input in a result
  carries `reported_at`; a result says so in `limitations` when inputs for one period were first
  reported more than 120 days apart; and `engine.check_periods()` tests, per year, whether the
  four quarters add up to the year. `engine.as_of(date)` shows what was known on a date, so a figure
  can be seen before and after the restating filing.
- Debt lines use only the first available concept, never a sum, so a filer that reports several
  overlapping debt concepts may show a partial figure.
- **Later runs (0.1.3).** Four US insurers (Progressive, Chubb, Travelers, Allstate; MetLife was in the
  earlier run) and five IFRS filers (Infosys, Novo Nordisk, SAP and Shell on 20-F, Royal Bank of Canada on
  40-F) were downloaded once and run end to end. They found and fixed: IFRS "current tax" meaning only the
  current year's charge (Novo Nordisk), and Citigroup tagging premiums like an insurer. Identity checks still
  fail for restatement-vintage reasons (SAP 2017-18, Royal Bank of Canada 2017 and 2023 quarters) and for
  Shell's 2016-17 tax split. For the US filers run before, every latest figure was identical before and
  after the changes; only insurer lines and earlier quarter versions were added. Point in time was checked on 14 real restated annual figures.
- Not covered yet: IFRS 17 insurers, IFRS bank lines, IFRS filings read from XBRL files, an
  underwriting expense net of interest and policyholder items, filers that report half-years only, and the
  period-end details of 4-4-5 retail calendars beyond what the 52/53-week handling covers.
