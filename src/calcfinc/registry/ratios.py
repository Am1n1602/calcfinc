"""Open registry of derived quantities and ratios, each defined by a formula string.

The formula is the single source of truth: it is what the engine evaluates and what the
generated definitions page shows, so the two cannot drift. Inputs may be reported metrics,
other registered formulas, `share_price` (valuation) or `prior(x)` (x one comparable period
earlier, for growth-style and average-balance definitions).

A missing input yields None with a reason, never zero -- except the inputs a spec lists in
`optional`, which count as 0 and are announced in the result's limitations.
`fallbacks` are (formula, note) pairs tried in order when the primary formula cannot be
evaluated; the note is added to the result so a substitution is never silent.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from calcfinc.formula import WINDOWED, CalcError, names_in
from calcfinc.registry import metrics

PRICE = "share_price"
PERIOD_DAYS = "period_days"       # days in the record's period, both end dates included
UNITS = frozenset({"pct", "x", "currency", "per_share", "shares", "days"})


@dataclass(frozen=True, slots=True)
class RatioSpec:
    name: str
    unit: str
    formula: str
    optional: tuple[str, ...] = ()
    fallbacks: tuple[tuple[str, str], ...] = ()
    requires_positive: tuple[str, ...] = ()
    label: str = ""
    version: int = 1                       # bump when the definition changes
    inputs: tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "inputs", names_in(self.formula))
        except CalcError as e:
            raise ValueError(f"{self.name}: bad formula: {e}") from e
        if not metrics.NAME_RE.fullmatch(self.name):
            raise ValueError(f"ratio name {self.name!r} must be lower_snake_case, optionally 'namespace.name'")
        if self.unit not in UNITS:
            raise ValueError(f"{self.name}: unknown unit {self.unit!r}; use one of {sorted(UNITS)}")
        for f, _note in self.fallbacks:
            try:
                names_in(f)
            except CalcError as e:
                raise ValueError(f"{self.name}: bad fallback formula {f!r}: {e}") from e
        if not set(self.optional) <= set(self.all_inputs):
            raise ValueError(f"{self.name}: optional inputs must appear in a formula")
        if not set(self.requires_positive) <= set(self.all_inputs):
            raise ValueError(f"{self.name}: requires_positive inputs must appear in a formula")

    @property
    def all_inputs(self) -> tuple[str, ...]:
        seen: dict[str, None] = dict.fromkeys(self.inputs)
        for f, _ in self.fallbacks:
            seen.update(dict.fromkeys(names_in(f)))
        return tuple(seen)

    @property
    def formulas(self) -> tuple[tuple[str, str | None], ...]:
        """(formula, note) attempts in priority order; the primary has no note."""
        return ((self.formula, None), *self.fallbacks)


FORMULAS: dict[str, RatioSpec] = {}
ALIASES: dict[str, str] = {}
NOT_FOR: dict[str, dict[str, str]] = {}      # ratio -> sector -> why it does not apply there


def restrict(names: Iterable[str], sector: str, why: str) -> None:
    """Mark ratios as meaningless for a sector. For that sector they return None with `why`, and so
    does every ratio built on them (a ratio with a fallback formula still tries the fallback)."""
    for n in names:
        if n not in FORMULAS:
            raise ValueError(f"cannot restrict {n!r}: not a registered ratio")
        NOT_FOR.setdefault(n, {})[sector] = why


def split_windowed(name: str) -> tuple[str | None, str]:
    """'ttm(net_profit)' -> ('ttm', 'net_profit'); a plain name -> (None, name)."""
    for fn in WINDOWED:
        if name.startswith(fn + "(") and name.endswith(")"):
            return fn, name[len(fn) + 1:-1]
    return None, name


def _known(name: str) -> bool:
    return name in (PRICE, PERIOD_DAYS) or name in FORMULAS or metrics.is_known(name)


def register_ratio(spec: RatioSpec, *, aliases: tuple[str, ...] = ()) -> RatioSpec:
    """Add a derived quantity or ratio. Every input must already be a registered metric or
    formula, so typos fail here instead of silently yielding None later."""
    existing = FORMULAS.get(spec.name)
    if existing is not None and existing != spec:
        raise ValueError(f"{spec.name!r} is already registered differently")
    if metrics.is_known(spec.name):
        raise ValueError(f"{spec.name!r} is already a reported metric name")
    for n in spec.all_inputs:
        fn, base = split_windowed(n)
        if base != spec.name and not _known(base):
            raise ValueError(f"{spec.name}: unknown input {base!r}; register_metric() it first")
        if base == spec.name and fn is None:
            raise ValueError(f"{spec.name}: a formula cannot use itself as input")
        reported = metrics.get(base)
        if fn == "ttm" and reported is not None and reported.is_point_in_time:
            raise ValueError(f"{spec.name}: ttm({base}) sums a balance-sheet item, which is meaningless; "
                             "use the period-end value")
    FORMULAS[spec.name] = spec
    for a in aliases:
        ALIASES[a.strip().lower()] = spec.name
    return spec


def resolve(name: str) -> str | None:
    key = (name or "").strip().lower()
    if key in FORMULAS:
        return key
    return ALIASES.get(key)


def get_spec(name: str) -> RatioSpec | None:
    key = resolve(name)
    return FORMULAS.get(key) if key else None


def known() -> list[str]:
    return sorted(FORMULAS)


def needs_price(name: str, _seen: frozenset[str] = frozenset()) -> bool:
    """True when the formula (directly or through other formulas) uses share_price."""
    spec = FORMULAS.get(name)
    if spec is None or name in _seen:
        return False
    for n in spec.all_inputs:
        if n == PRICE or needs_price(split_windowed(n)[1], _seen | {name}):
            return True
    return False


def uses_ttm(name: str, _seen: frozenset[str] = frozenset()) -> bool:
    """True when the formula (directly or through other formulas) uses ttm(...)."""
    spec = FORMULAS.get(name)
    if spec is None or name in _seen:
        return False
    for n in spec.all_inputs:
        fn, base = split_windowed(n)
        if fn == "ttm" or uses_ttm(base, _seen | {name}):
            return True
    return False


def valuation_names() -> list[str]:
    return sorted(n for n in FORMULAS if needs_price(n))


def _r(name: str, unit: str, formula: str, label: str, *, aliases: tuple[str, ...] = (),
       **kw: object) -> None:
    register_ratio(RatioSpec(name, unit, formula, label=label, **kw), aliases=aliases)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# derived quantities
# --------------------------------------------------------------------------- #
_r("top_line", "currency", "revenue", "Revenue, or total income for banks / insurers",
   fallbacks=(("total_income",
               "revenue not reported; total_income used as the top line (bank / insurer format)"),))
_r("ebit", "currency", "pbt_before_exceptional + finance_costs", "EBIT",
   optional=("finance_costs",))
_r("ebitda", "currency",
   "pbt_before_exceptional + depreciation + finance_costs - other_income", "EBITDA",
   optional=("finance_costs",))
_r("operating_ebit", "currency", "revenue - employee_expense - depreciation - other_expenses",
   "Operating EBIT (excludes other income)")
_r("total_debt", "currency",
   "borrowings_current + borrowings_noncurrent + debt_securities + deposits_debt", "Total debt",
   optional=("borrowings_current", "borrowings_noncurrent", "debt_securities", "deposits_debt"))
_r("net_debt", "currency", "total_debt - cash_and_equivalents", "Net debt")
_r("capex", "currency", "abs(capex_ppe) + abs(capex_intangibles)",
   "Capital expenditure (a positive amount, whichever sign the source uses)",
   fallbacks=(("abs(capex_ppe)", "capex_intangibles not reported; capex is PP&E only"),
              ("abs(capex_intangibles)", "capex_ppe not reported; capex is intangibles only")))
_r("free_cash_flow", "currency", "operating_cash_flow - capex", "Free cash flow")
_r("working_capital", "currency", "current_assets - current_liabilities", "Working capital")
_r("nopat", "currency", "ebit * (1 - tax_expense / pbt)",
   "Net operating profit after tax (EBIT x (1 - effective tax rate))",
   requires_positive=("pbt",))
_r("invested_capital", "currency", "total_debt + total_equity - cash_and_equivalents",
   "Invested capital (debt + equity - cash)")
_r("eps", "per_share", "eps_basic", "Earnings per share",
   fallbacks=(("eps_diluted", "basic EPS not reported; diluted EPS used"),
              ("net_profit_owners / shares_outstanding",
               "EPS derived as net_profit_owners / shares (no reported EPS)"),
              ("net_profit / shares_outstanding",
               "EPS derived as net_profit / shares (no reported EPS)")))
_r("book_value_per_share", "per_share", "total_equity / shares_outstanding", "Book value per share")
_r("bank.net_interest_income", "currency", "bank.interest_earned - bank.interest_expended",
   "Net interest income (bank)")
_r("bank.operating_expenses", "currency", "bank.employee_cost + bank.other_operating_expenses",
   "Operating expenses (bank)")
_r("bank.operating_income", "currency", "bank.operating_profit + bank.operating_expenses",
   "Operating income before provisions (bank)")

# --------------------------------------------------------------------------- #
# valuation (use share_price at the period end)
# --------------------------------------------------------------------------- #
_r("market_cap", "currency", "share_price * shares_outstanding", "Market capitalisation",
   aliases=("mcap", "marketcap", "market_capitalisation", "market_capitalization"))
_r("enterprise_value", "currency", "market_cap + net_debt + minority_interest + preferred_equity",
   "Enterprise value (market cap + net debt + minority interest + preferred equity)",
   optional=("minority_interest", "preferred_equity"), aliases=("ev",))
_r("pe", "x", "share_price / eps", "Price / earnings", requires_positive=("eps",),
   aliases=("p/e", "pe_ratio", "price_to_earnings", "price_earnings"))
_r("pb", "x", "market_cap / total_equity", "Price / book", requires_positive=("total_equity",),
   aliases=("p/b", "pb_ratio", "price_to_book", "price_book"))
_r("ev_ebitda", "x", "enterprise_value / ebitda", "EV / EBITDA",
   requires_positive=("ebitda", "bank.operating_profit"),
   fallbacks=(("market_cap / bank.operating_profit",
               "EBITDA proxied by bank pre-provision operating profit (PPOP); EV is not "
               "meaningful for a bank, so this is market cap / PPOP"),),
   aliases=("ev/ebitda", "enterprise_value_to_ebitda"))
_r("ev_ebit", "x", "enterprise_value / ebit", "EV / EBIT", requires_positive=("ebit",))
_r("ev_sales", "x", "enterprise_value / top_line", "EV / sales", requires_positive=("top_line",))
_r("price_to_sales", "x", "market_cap / top_line", "Price / sales",
   requires_positive=("top_line",), aliases=("p/s", "ps"))
_r("earnings_yield", "pct", "100 * eps / share_price", "Earnings yield")
_r("dividend_yield", "pct", "100 * (abs(dividends) / shares_outstanding) / share_price",
   "Dividend yield", aliases=("div_yield",))
_r("fcf_yield", "pct", "100 * free_cash_flow / market_cap", "Free cash flow yield",
   requires_positive=("market_cap",))

# --------------------------------------------------------------------------- #
# returns, margins, efficiency
# --------------------------------------------------------------------------- #
_r("roe", "pct", "100 * net_profit / total_equity", "Return on equity (period-end equity)",
   aliases=("return_on_equity", "roe_pct"))
_r("roa", "pct", "100 * net_profit / total_assets", "Return on assets (period-end assets)",
   aliases=("return_on_assets", "roa_pct"))
_r("roe_avg", "pct", "100 * net_profit / ((total_equity + prior(total_equity)) / 2)",
   "Return on average equity")
_r("roa_avg", "pct", "100 * net_profit / ((total_assets + prior(total_assets)) / 2)",
   "Return on average assets (the basis banking regulators use for banks)")
_r("roce", "pct", "100 * ebit / (total_assets - current_liabilities)",
   "Return on capital employed", aliases=("return_on_capital_employed", "roce_pct"))
_r("roic", "pct", "100 * nopat / invested_capital", "Return on invested capital",
   requires_positive=("invested_capital",))
_r("ebitda_margin", "pct", "100 * ebitda / revenue", "EBITDA margin", aliases=("ebitda_margin_pct",))
_r("ebit_margin", "pct", "100 * ebit / revenue", "EBIT margin", aliases=("ebit_margin_pct",))
_r("net_profit_margin", "pct", "100 * net_profit / top_line", "Net profit margin",
   aliases=("npm", "net_margin", "npm_pct"))
_r("pbt_margin", "pct", "100 * pbt / revenue", "Profit-before-tax margin")
_r("effective_tax_rate", "pct", "100 * tax_expense / pbt", "Effective tax rate")
_r("asset_turnover", "x", "top_line / total_assets", "Asset turnover")
_r("equity_multiplier", "x", "total_assets / total_equity", "Equity multiplier")
_r("incremental_net_margin", "pct",
   "100 * (net_profit - prior(net_profit)) / (top_line - prior(top_line))",
   "Change in net profit per unit of change in top line")
_r("operating_leverage", "x",
   "(ebit - prior(ebit)) * prior(top_line) / (prior(ebit) * (top_line - prior(top_line)))",
   "Degree of operating leverage (% change in EBIT / % change in top line)",
   requires_positive=("prior(ebit)",))
_r("payout_ratio", "pct", "100 * abs(dividends) / net_profit", "Dividend payout ratio")
_r("retention_ratio", "pct", "100 - payout_ratio", "Earnings retention ratio")
_r("sustainable_growth", "pct", "roe * retention_ratio / 100",
   "Sustainable growth rate (ROE x retention)")

# --------------------------------------------------------------------------- #
# working capital efficiency (period-end balances; days use the real length of the period)
# --------------------------------------------------------------------------- #
_r("gross_margin", "pct", "100 * gross_profit / revenue", "Gross margin",
   fallbacks=(("100 * (revenue - cost_of_revenue) / revenue",
               "gross profit not reported; derived as revenue - cost_of_revenue"),))
_r("quick_ratio", "x", "(current_assets - inventory) / current_liabilities",
   "Quick ratio ((current assets - inventory) / current liabilities)")
_r("inventory_turnover", "x", "cost_of_revenue / inventory", "Inventory turnover")
_r("receivables_turnover", "x", "revenue / trade_receivables", "Receivables turnover")
_r("payables_turnover", "x", "cost_of_revenue / trade_payables", "Payables turnover")
_r("dso", "days", "period_days * trade_receivables / revenue", "Days sales outstanding",
   aliases=("days_sales_outstanding",))
_r("dio", "days", "period_days * inventory / cost_of_revenue", "Days inventory outstanding",
   aliases=("days_inventory_outstanding",))
_r("dpo", "days", "period_days * trade_payables / cost_of_revenue", "Days payables outstanding",
   aliases=("days_payables_outstanding",))
_r("cash_conversion_cycle", "days", "dso + dio - dpo", "Cash conversion cycle (DSO + DIO - DPO)",
   aliases=("ccc",))

# --------------------------------------------------------------------------- #
# liquidity, leverage, cash flow
# --------------------------------------------------------------------------- #
_r("current_ratio", "x", "current_assets / current_liabilities", "Current ratio")
_r("cash_ratio", "x", "cash_and_equivalents / current_liabilities", "Cash ratio")
_r("debt_to_equity", "x", "total_debt / total_equity", "Debt / equity",
   aliases=("de", "d/e", "leverage"))
_r("debt_to_assets", "x", "total_debt / total_assets", "Debt / assets")
_r("debt_to_capital", "x", "total_debt / (total_debt + total_equity)", "Debt / (debt + equity)")
_r("net_debt_to_equity", "x", "net_debt / total_equity", "Net debt / equity")
_r("net_debt_to_ebitda", "x", "net_debt / ebitda", "Net debt / EBITDA",
   requires_positive=("ebitda",))
_r("debt_to_ebitda", "x", "total_debt / ebitda", "Debt / EBITDA", requires_positive=("ebitda",))
_r("equity_to_assets", "pct", "100 * total_equity / total_assets", "Equity / assets")
_r("equity_to_liabilities", "x", "total_equity / total_liabilities", "Equity / liabilities")
_r("interest_coverage", "x", "ebit / finance_costs", "Interest coverage (EBIT / finance costs)",
   aliases=("interest_coverage_ratio",))
_r("ocf_margin", "pct", "100 * operating_cash_flow / top_line", "Operating cash flow margin")
_r("fcf_margin", "pct", "100 * free_cash_flow / top_line", "Free cash flow margin")
_r("cash_conversion", "x", "operating_cash_flow / net_profit",
   "Operating cash flow / net profit", requires_positive=("net_profit",))
_r("capex_to_revenue", "pct", "100 * capex / top_line", "Capex / top line")
_r("capex_to_depreciation", "x", "capex / depreciation", "Capex / depreciation")
_r("cash_flow_to_debt", "x", "operating_cash_flow / total_debt", "Operating cash flow / debt")
# --- trailing twelve months: the latest adjacent periods that make a year (4 quarters, 12 months).
# None, with a reason, if any of them is missing. Balances stay period-end; flows are summed. ---
_r("revenue_ttm", "currency", "ttm(revenue)", "Revenue, trailing twelve months")
_r("net_profit_ttm", "currency", "ttm(net_profit)", "Net profit, trailing twelve months")
_r("ebit_ttm", "currency", "ttm(ebit)", "EBIT, trailing twelve months")
_r("ebitda_ttm", "currency", "ttm(ebitda)", "EBITDA, trailing twelve months")
_r("free_cash_flow_ttm", "currency", "ttm(free_cash_flow)", "Free cash flow, trailing twelve months")
_r("eps_ttm", "per_share", "ttm(eps)", "EPS, trailing twelve months (the sum of each period's EPS)")
_r("roe_ttm", "pct", "100 * ttm(net_profit) / total_equity", "Return on equity on trailing-twelve-month profit")
_r("roa_ttm", "pct", "100 * ttm(net_profit) / total_assets", "Return on assets on trailing-twelve-month profit")
_r("roce_ttm", "pct", "100 * ttm(ebit) / (total_assets - current_liabilities)",
   "Return on capital employed on trailing-twelve-month EBIT")
_r("net_profit_margin_ttm", "pct", "100 * ttm(net_profit) / ttm(top_line)",
   "Net profit margin, trailing twelve months")
_r("ebitda_margin_ttm", "pct", "100 * ttm(ebitda) / ttm(revenue)", "EBITDA margin, trailing twelve months")
_r("interest_coverage_ttm", "x", "ttm(ebit) / ttm(finance_costs)",
   "Interest coverage (EBIT / finance costs), trailing twelve months")
_r("pe_ttm", "x", "share_price / eps_ttm", "Price / trailing-twelve-month earnings",
   requires_positive=("eps_ttm",))
_r("ev_ebitda_ttm", "x", "enterprise_value / ebitda_ttm", "EV / trailing-twelve-month EBITDA",
   requires_positive=("ebitda_ttm",))
_r("dividend_yield_ttm", "pct", "100 * abs(ttm(dividends)) / shares_outstanding / share_price",
   "Dividend yield on trailing-twelve-month dividends")
_r("graham_number", "per_share", "sqrt(22.5 * eps * book_value_per_share)",
   "Graham number (22.5 = 15 x 1.5, the classic P/E and P/B ceilings)",
   requires_positive=("eps", "book_value_per_share"))

# --------------------------------------------------------------------------- #
# bank.*
# --------------------------------------------------------------------------- #
_r("bank.net_interest_margin", "pct",
   "100 * bank.net_interest_income / ((bank.earning_assets + prior(bank.earning_assets)) / 2)",
   "Net interest margin on average interest-earning assets",
   fallbacks=(("100 * bank.net_interest_income / bank.earning_assets",
               "no earlier comparable period; period-end interest-earning assets used instead of the average"),
              ("100 * bank.net_interest_income / total_assets",
               "interest-earning assets not reported; total assets used as the denominator "
               "(understates the margin)")),
   aliases=("nim", "net_interest_margin"))
_r("bank.net_interest_margin_avg_assets", "pct",
   "100 * bank.net_interest_income / ((total_assets + prior(total_assets)) / 2)",
   "Net interest margin on average total assets (not annualised)")
_r("bank.credit_cost", "pct", "100 * bank.provisions / bank.advances",
   "Credit cost (provisions / period-end advances)", aliases=("credit_cost",),
   fallbacks=(("100 * bank.provisions / bank.gross_advances",
               "net advances not reported; gross advances used (understates the ratio slightly)"),))
_r("bank.cost_to_income", "pct", "100 * bank.operating_expenses / bank.operating_income",
   "Cost to income", requires_positive=("bank.operating_income",))
_r("bank.loan_to_deposit", "pct", "100 * bank.advances / bank.deposits", "Loan to deposit",
   fallbacks=(("100 * bank.gross_advances / bank.deposits",
               "net advances not reported; gross advances used (overstates the ratio slightly)"),))
_r("bank.casa_ratio", "pct", "100 * bank.casa_deposits / bank.deposits", "CASA ratio")
_r("bank.provision_coverage", "pct", "100 * bank.npa_provisions / bank.gross_npa",
   "Provision coverage (provisions held against NPAs / gross NPAs)",
   fallbacks=(("100 * (bank.gross_npa - bank.net_npa) / bank.gross_npa",
               "provisions against NPAs not reported; estimated as gross NPA - net NPA, which also counts "
               "interest suspense and part payments and so may overstate coverage"),))
_r("bank.gross_npa_to_advances", "pct", "100 * bank.gross_npa / bank.gross_advances",
   "Gross NPA / gross advances",
   fallbacks=(("100 * bank.gross_npa / bank.advances",
               "gross advances not reported; balance-sheet advances used (overstates the ratio when "
               "provisions are large)"),))
_r("bank.net_npa_to_advances", "pct", "100 * bank.net_npa / bank.advances",
   "Net NPA / net (balance-sheet) advances")

# --------------------------------------------------------------------------- #
# insurance.*  (ratios on an earned-premium basis)
# --------------------------------------------------------------------------- #
_r("insurance.loss_ratio", "pct",
   "100 * insurance.claims_incurred / insurance.net_earned_premium", "Loss ratio")
_r("insurance.expense_ratio", "pct",
   "100 * insurance.underwriting_expenses / insurance.net_earned_premium",
   "Expense ratio (earned-premium basis)")
_r("insurance.combined_ratio", "pct", "insurance.loss_ratio + insurance.expense_ratio",
   "Combined ratio (below 100 = underwriting profit)")
_r("insurance.investment_income_ratio", "pct",
   "100 * insurance.net_investment_income / insurance.net_earned_premium",
   "Net investment income / earned premium")
_r("insurance.operating_ratio", "pct",
   "insurance.combined_ratio - insurance.investment_income_ratio", "Operating ratio")

# --------------------------------------------------------------------------- #
# ratios that do not describe a bank (see bank.* above, or net_profit based ones, instead)
# --------------------------------------------------------------------------- #
BANK_WHY = {
    "interest": "interest is a bank's operating cost, so profit before interest is not an operating result",
    "debt": "a bank is funded by deposits and borrowing is part of its business, so debt ratios say little "
            "about its leverage (see equity_multiplier and the capital ratios)",
    "current": "a bank's balance sheet is not split into current and non-current",
    "trade": "a bank has no inventory, trade receivables or cost of goods",
    "cash_flow": "a bank's operating cash flow is dominated by deposit and loan movements",
}
restrict(("ebit", "ebitda", "operating_ebit", "interest_coverage"), "bank", BANK_WHY["interest"])
restrict(("total_debt",), "bank", BANK_WHY["debt"])
restrict(("working_capital", "current_ratio", "quick_ratio", "cash_ratio"), "bank", BANK_WHY["current"])
restrict(("gross_margin", "inventory_turnover", "receivables_turnover", "payables_turnover",
          "dso", "dio", "dpo"), "bank", BANK_WHY["trade"])
restrict(("free_cash_flow", "ocf_margin", "cash_conversion", "capex_to_revenue", "capex_to_depreciation"),
         "bank", BANK_WHY["cash_flow"])
