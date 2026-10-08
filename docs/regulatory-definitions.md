# Ratio definitions by ACCA, FTC/QFR, MCA/ICAI, RBI and SEBI

Research notes, dated 2026-10-08. Purpose: decide which definition calcfinc uses where the bodies
differ. Nothing here changes the code until a definition is chosen.

**Reading "FTC" as the US Federal Trade Commission's Quarterly Financial Report (QFR)**, which the
FTC ran until 1982 and the Census Bureau runs today.

## How reliable each source is

| Body | What I could read | Quality |
|---|---|---|
| ACCA | The ACCA technical article "Ratio analysis" | Primary. It does not say whether balances are averages or closing. |
| FTC / Census QFR | The QFR definitions page | Primary. Five ratios only. |
| MCA (Schedule III, G.S.R. 207(E), 24 Mar 2021) | Secondary summaries only | The notification lists 11 ratios and requires each company to *explain the numerator and denominator it used* and any change over 25%. It appears **not to prescribe formulas**. I could not read the gazette text itself. |
| ICAI | ICAI Board of Studies lecture slides (Financial Management, 2021) | Primary ICAI *teaching* material, not a binding standard. The Division II guidance note found is the 2019 edition and has no ratio section. |
| SEBI (LODR Reg. 52(4)) | Issuer disclosures and one older SEBI listing document | The regulation lists the ratios. The only SEBI wording for formulas is an old suggestion for interest and debt service coverage, itself telling issuers to disclose the formula they used. Issuer practice varies. |
| RBI | RBI glossary and Financial Stability Report footnotes (via search), and the IRAC master circular (via search) | Partly primary. Net interest margin, GNPA, NNPA and PCR found. Cost-to-income, CASA and credit-deposit ratio not found in RBI text. |

IRDAI (insurance) was not in the requested set and is not covered.

## Where the bodies agree (no decision needed)

- Current ratio = current assets / current liabilities (ACCA, ICAI, QFR, SEBI issuers, Schedule III).
- Gross margin = gross profit / revenue (ACCA).
- Quick ratio = (current assets - inventory) / current liabilities (ACCA). ICAI also removes prepaid expenses. QFR's nearest ratio is a stricter cash-and-securities ratio.

## Where they differ

| Ratio | ACCA | FTC / QFR | MCA / ICAI | SEBI | RBI | calcfinc today |
|---|---|---|---|---|---|---|
| **ROE** | Profit after interest and tax / total equity (balance basis unstated) | Quarterly income after tax x 4 / equity at quarter end | (Profit after tax - preference dividend) / equity. Schedule III summaries say *average* equity. | not defined | n/a | Net profit / period-end equity; `roe_avg` for average |
| **ROA** | Not defined | Income x 4 / total assets at quarter end | ICAI slides: EBIT x (1 - tax) or (profit + interest), over *average* total assets | n/a | Banks: net profit / *average working funds* (average total assets) | Net profit / period-end assets |
| **ROCE** | PBIT / (total assets - current liabilities), or / (non-current liabilities + equity) | n/a | EBIT / capital employed. Capital employed is **not** fixed: total assets - current liabilities in some summaries, tangible net worth + debt + deferred tax liability in rating-agency practice | issuer practice varies | n/a | EBIT (before exceptional items) / (total assets - current liabilities) |
| **Debt-equity** | Non-current liabilities / ordinary shareholders' funds, or / (funds + non-current liabilities) | Reported inverted: equity / total debt (short-term loans + current instalments + long-term debt) | Total debt / shareholders' equity | No SEBI formula. Issuers: borrowings / total equity, or / net worth | n/a | Borrowings (current + non-current + debt securities + deposits) / total equity |
| **Interest cover** | Operating profit / finance costs | n/a | EBIT / interest | Old SEBI suggestion: EBIT / interest. Issuer practice: (PBT + exceptional + depreciation + net finance charges) / net finance charges | n/a | EBIT / finance costs |
| **DSCR** | n/a | n/a | Earnings available for debt service (profit after tax + non-cash charges + interest + other adjustments) / (interest + instalments). Some summaries add lease payments. | Old suggestion: EBIT / (interest + principal). Issuer practice: EBITDA-like numerator / (net finance charges + scheduled principal) | n/a | Not built in (a user registers their own) |
| **Receivable days** | Receivables / credit sales x 365 | n/a | Net credit sales / *average* receivables as a turnover; ICAI slides convert with 360 days | formula not found | n/a | Period days x closing receivables / revenue |
| **Inventory and payable days** | Inventory / cost of sales x 365; payables / credit purchases (or cost of sales) x 365 | n/a | COGS / *average* inventory; credit purchases / *average* payables | formula not found | n/a | Period days x closing balance / cost of revenue |
| **Asset turnover** | Revenue / **capital employed** | n/a | Sales / total assets (ICAI); net capital turnover = net sales / working capital (Schedule III) | n/a | n/a | Revenue / period-end total assets |
| **Net interest margin** | n/a | n/a | n/a | n/a | RBI glossary: net interest income / *average interest-earning assets*. A 2019 RBI report footnote: annualised net interest income / *average total assets*. | Net interest income / period-end earning assets (falls back to total assets) |
| **Gross / net NPA ratio** | n/a | n/a | n/a | n/a | Gross NPAs / *gross* advances; net NPAs / *net* advances, both after removing technical write-offs and interest suspense | NPAs / balance-sheet advances for both |
| **Provision coverage** | n/a | n/a | n/a | n/a | Provisions held against NPAs / gross NPAs (a "without write-off adjustment" variant exists) | (Gross NPA - net NPA) / gross NPA, which also counts interest suspense and part payments |

## Decisions (all the recommended options)

| Ratio | Final definition |
|---|---|
| ROE, ROA | Net profit / period-end equity or assets. `roe_avg` and `roa_avg` are the average-balance versions (`roa_avg` is the RBI basis for banks). |
| ROCE | EBIT / (total assets - current liabilities), the ACCA form. |
| Debt-equity | Borrowings (current, non-current, debt securities, deposits) / total equity. |
| Working-capital days and turnovers | Closing balances and the real number of days in the period. |
| Interest cover | EBIT / finance costs. |
| DSCR | Not built in to the generic set; register your own, or use the Indian forms below. |
| Asset turnover | Revenue / total assets. |
| Quick ratio | (Current assets - inventory) / current liabilities. |
| Net interest margin | Average interest-earning assets; period-end if there is no prior period, total assets if earning assets are missing. Each fallback says so. |
| Gross NPA ratio | Gross NPAs / gross advances, falling back to balance-sheet advances with a note. Net NPA ratio is on net (balance-sheet) advances. |
| Provision coverage | Provisions held against NPAs / gross NPAs, falling back to (gross - net NPA) with a note that it may overstate. |

## Ratios held back for banks

Several generic ratios describe an operating business and mislead for a bank (a large US bank
showed interest cover 1.76, EBIT margin 39.8% and debt/equity 0.18, none of which means what it
means for a manufacturer). For an entity whose sector is `bank` they return None with the reason,
and so does everything built on them.

An entity is a bank if it was declared one (`Entity.sector`, or `sector=` when loading), or, when no
sector is declared, if it reports `bank.interest_earned` and `bank.interest_expended` together with
`bank.deposits`, `bank.advances` or `bank.gross_advances`. Interest lines alone, or deposits and
loans alone, are not enough (an insurer files deposits and mortgage loans). Declaring any other
sector (for example `"corporate"`) switches the inference off. Insurers are not yet handled this way.

| Held back | Why |
|---|---|
| `ebit`, `ebitda`, `operating_ebit`, `interest_coverage` and what rests on them (margins, ROCE, ROIC, `india.roce`, `india.dscr_sebi`, TTM forms) | Interest is a bank's operating cost |
| `total_debt` and what rests on it (debt/equity, net debt, enterprise value, `india.capital_employed`) | Deposits are the funding; borrowing is part of the business. `ev_ebitda` still has its labelled market cap / PPOP fallback |
| `working_capital`, current, quick and cash ratios, `india.quick_ratio`, `india.net_capital_turnover` | No current / non-current split |
| gross margin, inventory / receivable / payable turnovers and days, `india.*` turnovers and days | No inventory, trade receivables or cost of goods |
| free cash flow, operating cash flow margin, cash conversion, capex ratios | Cash flow is dominated by deposit and loan movements |
| `india.roa` | Adds back interest; use `roa_avg` or the reported ROA |

Not held back: ROE, ROA, `roa_avg`, equity multiplier, DuPont, payout, per-share and valuation
ratios, and everything under `bank.*`. `calculate()` still evaluates any formula by hand.

## Indian counterparts (`india.*`, registered by `calcfinc.adapters.ind_as_xbrl.register()`)

Added only where the Indian form differs from the generic one above. Ratios where Indian practice
matches the generic definition have no twin: current ratio, net profit ratio, interest cover
(EBIT / interest, ICAI and SEBI's suggestion), the RBI-form NPA and provision coverage ratios, and
the RBI average-assets return on assets (`roa_avg`).

| Function | Definition | Evidence |
|---|---|---|
| `india.roe` | (Net profit - preference dividend) / average equity | Schedule III summaries; ICAI slides |
| `india.roa` | (Net profit + finance costs) / average total assets | ICAI slides |
| `india.capital_employed`, `india.roce` | EBIT / (tangible net worth + total debt + deferred tax liabilities) | Indian rating-agency practice; **not confirmed as an MCA or ICAI rule** |
| `india.quick_ratio` | (Current assets - inventory - prepaid expenses) / current liabilities | ICAI slides |
| `india.net_capital_turnover` | Revenue / (current assets - current liabilities) | Schedule III summaries |
| `india.inventory_turnover` | Cost of revenue / average inventory | ICAI slides; Schedule III summaries |
| `india.trade_receivables_turnover` | Net credit sales / average receivables (revenue if credit sales are missing) | same |
| `india.trade_payables_turnover` | Net credit purchases / average payables (cost of revenue if missing) | same |
| `india.trade_receivables_days` | Real days in the period / receivables turnover | ICAI uses a 360-day year; real days avoid a wrong answer for partial periods |
| `india.dscr` | (Net profit + depreciation + finance costs + other non-cash items) / (finance costs + lease payments + scheduled principal) | ICAI slides; the lease element comes from secondary sources |
| `india.dscr_sebi` | EBIT / (finance costs + scheduled principal) | SEBI's old suggested form |

Average-based functions return `None` with a reason when there is no earlier comparable period.
They do not fall back to closing balances, so a disclosure never mixes bases silently.

**Not added because no source fixes a form:** SEBI's operating margin, net profit margin and
debtors turnover (formulas not found); Schedule III's return on investment; the cost-to-income,
CASA and credit-deposit ratios (not found in RBI text); the SEBI issuer-style interest cover and
debt-equity on Companies Act net worth (issuer practice, not a rule).

## Points that are naming problems, not definition conflicts

- ACCA's article calls PBIT / revenue both "operating profit margin" and "net profit margin". calcfinc keeps them separate: `ebit_margin` and `net_profit_margin`.
- ICAI's `Dividend payout = DPS / EPS` equals calcfinc's `dividends / net profit` unless preference dividends or unusual share structures are involved.
- QFR annualises quarterly figures by multiplying by four; calcfinc deliberately does not annualise and warns instead.

## Sources

- ACCA: [Ratio analysis](https://www.accaglobal.com/gb/en/student/exam-support-resources/fundamentals-exams-study-resources/f2/technical-articles/ratio-analysis.html)
- FTC / Census Bureau: [QFR definitions](https://www.census.gov/econ/qfr/definitions.html)
- ICAI Board of Studies: [Ratio analysis slides (Financial Management, 2021)](https://live.icai.org/bos/vcc-2nd-batch-recorded-lectures/pdf/Ratios%20ICAI%20Format.pdf)
- MCA / Schedule III summaries (secondary): [TaxRoutine](https://taxroutine.com/financial-ratios-schedule-iii-companies-act/), [DPNC](https://www.dpncindia.com/amendment-in-schedule-iii-of-the-companies-act-2013-applicable-w-e-f-01-04-2021)
- SEBI: issuer Regulation 52(4) disclosures, e.g. [NABARD](https://nabard.org/hindi/pdf/regulation52-4-financial-ratios-sep-2022.pdf), and the [SEBI listing document for debt securities](https://www.sebi.gov.in/sebi_data/attachdocs/1288602869837.pdf)
- RBI: [Glossary](https://rbi.org.in/scripts/glossary.aspx), [Financial Stability Report, June 2019](https://rbidocs.rbi.org.in/rdocs/PublicationReport/Pdfs/FSRJUNE2019E5ECDDAD7E514756AFEF1E71CB2ADA2B.PDF), [IRAC master circular, April 2025](https://rbidocs.rbi.org.in/rdocs/notification/PDFs/13MC01042025792E33CF094B46F2B838E6409777438D.PDF)
