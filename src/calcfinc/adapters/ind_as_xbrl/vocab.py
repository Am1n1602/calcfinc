"""Ind-AS (India) vocabulary and the Indian counterparts of ratios whose Indian definition
differs from the generic one. Everything India-specific lives here, never in the core.

Call `register()` once (the loaders do it for you) to make the extra metrics and `india.*`
ratios known to the registry.

Where the Indian practice (ICAI teaching material, the Schedule III ratio disclosures, SEBI's
suggested coverage formulas) matches the generic ratio, there is no `india.*` twin: current
ratio, net profit ratio, interest coverage (EBIT / interest) and the RBI-form NPA and provision
coverage ratios are the generic ones. `roa_avg` is already the RBI basis for banks. Schedule III
leaves the exact formulas to each company, so these are the forms ICAI uses in its material;
each ratio's `label` states the form it follows.
"""
from __future__ import annotations

from decimal import Decimal

from calcfinc.fact import StatementType
from calcfinc.num import div
from calcfinc.registry.metrics import register_metric
from calcfinc.registry.ratios import BANK_WHY, INSURER_WHY, RatioSpec, register_ratio, restrict

# Ind-AS / source tag names that differ from the generic core vocabulary.
RENAMES = {"pat_continuing_ops": "profit_continuing_ops"}

PL, BS, CF, OTHER = (StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET,
                     StatementType.CASH_FLOW, StatementType.OTHER)


def _metrics() -> None:
    register_metric("paid_up_equity_capital", "currency", BS, point_in_time=True, label="Paid-up equity share capital")
    register_metric("face_value_per_share", "per_share", BS, point_in_time=True, label="Face value per share")
    register_metric("debt_equity_ratio_reported", "x", OTHER, label="Debt/Equity ratio (as reported, SEBI)")
    register_metric("debt_service_coverage_ratio_reported", "x", OTHER,
                    label="Debt service coverage ratio (as reported, SEBI)")
    register_metric("interest_service_coverage_ratio_reported", "x", OTHER,
                    label="Interest service coverage ratio (as reported, SEBI)")
    register_metric("india.return_on_assets_reported", "x", OTHER, label="Return on assets (as reported, bank)")
    # inputs the Indian-form ratios need beyond the generic vocabulary
    register_metric("india.net_credit_sales", "currency", PL, label="Net credit sales")
    register_metric("india.net_credit_purchases", "currency", PL, label="Net credit purchases")
    register_metric("india.preference_dividend", "currency", PL, label="Preference dividend")
    register_metric("india.intangible_assets", "currency", BS, point_in_time=True, label="Intangible assets")
    register_metric("india.deferred_tax_liabilities", "currency", BS, point_in_time=True,
                    label="Deferred tax liabilities")
    register_metric("india.prepaid_expenses", "currency", BS, point_in_time=True, label="Prepaid expenses")
    register_metric("india.scheduled_principal_repayment", "currency", CF,
                    label="Scheduled principal repayment of long-term borrowings")
    register_metric("india.lease_payments", "currency", CF, label="Lease payments")
    register_metric("india.other_noncash_adjustments", "currency", PL,
                    label="Other non-cash adjustments (e.g. loss on sale of fixed assets)")


def _r(name: str, unit: str, formula: str, label: str, **kw: object) -> None:
    register_ratio(RatioSpec(name, unit, formula, label=label, **kw))  # type: ignore[arg-type]


def _ratios() -> None:
    _r("india.roe", "pct",
       "100 * (net_profit - india.preference_dividend) / ((total_equity + prior(total_equity)) / 2)",
       "Return on equity, Schedule III form: (profit after tax - preference dividend) / average equity",
       optional=("india.preference_dividend",), requires_positive=("total_equity", "prior(total_equity)"),
       version=2)
    _r("india.roa", "pct", "100 * (net_profit + finance_costs) / ((total_assets + prior(total_assets)) / 2)",
       "Return on assets, ICAI form for assets financed partly by lenders: (profit + interest) / average assets")
    _r("india.capital_employed", "currency",
       "(total_equity - india.intangible_assets) + total_debt + india.deferred_tax_liabilities",
       "Capital employed = tangible net worth + total debt + deferred tax liabilities (Indian rating-agency "
       "practice; not confirmed as an MCA or ICAI rule)",
       optional=("india.intangible_assets", "india.deferred_tax_liabilities"))
    _r("india.roce", "pct", "100 * ebit / india.capital_employed",
       "Return on capital employed on the tangible-net-worth + debt + deferred tax basis",
       requires_positive=("india.capital_employed",))
    _r("india.quick_ratio", "x", "(current_assets - inventory - india.prepaid_expenses) / current_liabilities",
       "Quick ratio, ICAI form: excludes inventories and prepaid expenses",
       optional=("india.prepaid_expenses",))
    _r("india.net_capital_turnover", "x", "top_line / working_capital",
       "Net capital turnover: net sales / working capital (current assets - current liabilities)",
       requires_positive=("working_capital",))
    _r("india.inventory_turnover", "x", "cost_of_revenue / ((inventory + prior(inventory)) / 2)",
       "Inventory turnover on average inventory")
    _r("india.trade_receivables_turnover", "x",
       "india.net_credit_sales / ((trade_receivables + prior(trade_receivables)) / 2)",
       "Trade receivables turnover: net credit sales / average trade receivables",
       fallbacks=(("revenue / ((trade_receivables + prior(trade_receivables)) / 2)",
                   "net credit sales not reported; revenue used"),))
    _r("india.trade_payables_turnover", "x",
       "india.net_credit_purchases / ((trade_payables + prior(trade_payables)) / 2)",
       "Trade payables turnover: net credit purchases / average trade payables",
       fallbacks=(("cost_of_revenue / ((trade_payables + prior(trade_payables)) / 2)",
                   "net credit purchases not reported; cost of revenue used"),))
    _r("india.trade_receivables_days", "days", "period_days / india.trade_receivables_turnover",
       "Collection period on average receivables, using the real days in the period "
       "(ICAI's slides use a 360-day year)")
    _r("india.dscr", "x",
       "(net_profit + depreciation + finance_costs + india.other_noncash_adjustments) "
       "/ (finance_costs + india.lease_payments + india.scheduled_principal_repayment)",
       "Debt service coverage, ICAI form: earnings available for debt service / (interest + lease "
       "payments + scheduled principal)",
       optional=("india.other_noncash_adjustments", "india.lease_payments"))
    _r("india.dscr_sebi", "x", "ebit / (finance_costs + india.scheduled_principal_repayment)",
       "Debt service coverage, SEBI's suggested form: EBIT / (interest + principal repayment)")


def _restrictions() -> None:
    # The rest (capital employed, ROCE, DSCR on EBIT, net capital turnover, receivable days) rest on
    # EBIT, debt or working capital, which are already held back for banks.
    restrict(("india.roa",), "bank", BANK_WHY["interest"] + "; use roa_avg or the reported ROA")
    restrict(("india.quick_ratio",), "bank", BANK_WHY["current"])
    restrict(("india.inventory_turnover", "india.trade_receivables_turnover",
              "india.trade_payables_turnover"), "bank", BANK_WHY["trade"])
    restrict(("india.dscr",), "bank", BANK_WHY["debt"])
    restrict(("india.quick_ratio",), "insurer", INSURER_WHY["current"])
    restrict(("india.inventory_turnover", "india.trade_receivables_turnover",
              "india.trade_payables_turnover"), "insurer", INSURER_WHY["trade"])


def register() -> None:
    """Register the Ind-AS metrics and the `india.*` ratios (idempotent)."""
    _metrics()
    _ratios()
    _restrictions()


def shares_outstanding(paid_up_equity_capital: Decimal, face_value_per_share: Decimal) -> Decimal | None:
    """Indian filings give share capital and face value, not a share count. The adapter
    derives the count at ingestion so the core only ever sees `shares_outstanding`."""
    if not face_value_per_share:
        return None
    return div(paid_up_equity_capital, face_value_per_share)
