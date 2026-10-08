"""Open registry of input metrics: a small generic core plus namespaced extensions.

Extensions use a dotted namespace (`bank.advances`, `insurance.claims_incurred`) and are
registered with `register_metric`. Kinds describe what a number is, never a currency:
  currency   an amount; the currency (ISO 4217) travels on each fact
  per_share  an amount per share; also carries a currency
  shares     a share count
  x          a plain dimensionless number as reported
  pct        a percentage as reported
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from calcfinc.fact import StatementType

KINDS = frozenset({"currency", "per_share", "shares", "x", "pct"})
CURRENCY_KINDS = frozenset({"currency", "per_share"})
NAME_RE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)?")

PL = StatementType.PROFIT_AND_LOSS
BS = StatementType.BALANCE_SHEET
CF = StatementType.CASH_FLOW
OTHER = StatementType.OTHER


@dataclass(frozen=True, slots=True)
class MetricSpec:
    kind: str
    statement_type: StatementType
    is_point_in_time: bool          # True -> balance-sheet snapshot (no period_start)
    label: str


REGISTRY: dict[str, MetricSpec] = {}


def register_metric(name: str, kind: str, statement_type: StatementType, *,
                    point_in_time: bool = False, label: str = "") -> MetricSpec:
    """Add an input metric. Re-registering an identical spec is a no-op; a different spec
    under an existing name raises."""
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"metric name {name!r} must be lower_snake_case, optionally 'namespace.name'")
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; use one of {sorted(KINDS)}")
    spec = MetricSpec(kind, StatementType(statement_type), point_in_time, label or name)
    existing = REGISTRY.get(name)
    if existing is not None and existing != spec:
        raise ValueError(f"metric {name!r} is already registered differently")
    REGISTRY[name] = spec
    return spec


def get(name: str) -> MetricSpec | None:
    return REGISTRY.get(name)


def is_known(name: str) -> bool:
    return name in REGISTRY


def canonical_names() -> list[str]:
    return list(REGISTRY)


def _pl(name: str, label: str, kind: str = "currency") -> None:
    register_metric(name, kind, PL, label=label)


def _bs(name: str, label: str, kind: str = "currency") -> None:
    register_metric(name, kind, BS, point_in_time=True, label=label)


def _cf(name: str, label: str) -> None:
    register_metric(name, "currency", CF, label=label)


# --- core: income statement (duration) ---
_pl("revenue", "Revenue from operations")
_pl("other_income", "Other income")
_pl("total_income", "Total income")
_pl("employee_expense", "Employee benefit expense")
_pl("depreciation", "Depreciation and amortisation")
_pl("other_expenses", "Other expenses")
_pl("finance_costs", "Finance costs")
_pl("total_expenses", "Total expenses")
_pl("pbt_before_exceptional", "Profit before exceptional items and tax")
_pl("exceptional_items", "Exceptional items (before tax)")
_pl("equity_method_income", "Share of profit of equity-method investees (when reported after pre-tax profit)")
_pl("pbt", "Profit before tax")
_pl("current_tax", "Current tax")
_pl("deferred_tax", "Deferred tax")
_pl("tax_expense", "Total tax expense")
_pl("profit_continuing_ops", "Profit for the period from continuing operations")
_pl("net_profit", "Profit for the period")
_pl("oci", "Other comprehensive income (net of tax)")
_pl("total_comprehensive_income", "Total comprehensive income")
_pl("net_profit_owners", "Profit attributable to owners of the parent")
_pl("net_profit_nci", "Profit attributable to non-controlling interests")
_pl("cost_of_revenue", "Cost of revenue (cost of goods sold)")
_pl("gross_profit", "Gross profit")
_pl("eps_basic", "Basic EPS", "per_share")
_pl("eps_diluted", "Diluted EPS", "per_share")

# --- core: balance sheet (instant) ---
_bs("total_assets", "Total assets")
_bs("total_liabilities", "Total liabilities")
_bs("total_equity", "Total equity")
_bs("current_assets", "Current assets")
_bs("noncurrent_assets", "Non-current assets")
_bs("current_liabilities", "Current liabilities")
_bs("noncurrent_liabilities", "Non-current liabilities")
_bs("borrowings_current", "Current borrowings")
_bs("borrowings_noncurrent", "Non-current borrowings")
_bs("cash_and_equivalents", "Cash and cash equivalents")
_bs("debt_securities", "Debt securities issued")
_bs("deposits_debt", "Deposits treated as debt")
_bs("shares_outstanding", "Shares outstanding", "shares")
_bs("minority_interest", "Non-controlling (minority) interest")
_bs("preferred_equity", "Preferred equity")
_bs("inventory", "Inventories")
_bs("trade_receivables", "Trade receivables")
_bs("trade_payables", "Trade payables")

# --- core: cash flow (duration) ---
_cf("operating_cash_flow", "Cash flow from operating activities")
_cf("investing_cash_flow", "Cash flow from investing activities")
_cf("financing_cash_flow", "Cash flow from financing activities")
_cf("dividends", "Dividends paid (financing; either sign accepted, used as an outflow amount)")
_cf("capex_ppe", "Purchase of property, plant and equipment (either sign accepted)")
_cf("capex_intangibles", "Purchase of intangible assets (either sign accepted)")

# --- bank.* ---
_pl("bank.interest_earned", "Interest earned (bank)")
_pl("bank.interest_expended", "Interest expended (bank)")
_pl("bank.operating_profit", "Operating profit before provisions and contingencies (bank)")
_pl("bank.provisions", "Provisions other than tax and contingencies (bank)")
_pl("bank.employee_cost", "Employee cost (bank)")
_pl("bank.other_operating_expenses", "Other operating expenses (bank)")
_bs("bank.advances", "Advances (bank), net as on the balance sheet")
_bs("bank.gross_advances", "Gross advances (bank), before provisions and suspense")
_bs("bank.npa_provisions", "Provisions held against non-performing assets (bank)")
_bs("bank.deposits", "Deposits (bank)")
_bs("bank.casa_deposits", "Current and savings account deposits (bank)")
_bs("bank.earning_assets", "Interest-earning assets (bank)")
_bs("bank.gross_npa", "Gross non-performing assets (bank)")
_bs("bank.net_npa", "Net non-performing assets (bank)")
register_metric("bank.gross_npa_ratio", "x", OTHER, label="Gross NPA ratio (as reported, bank)")
register_metric("bank.net_npa_ratio", "x", OTHER, label="Net NPA ratio (as reported, bank)")
register_metric("bank.cet1_ratio", "x", OTHER, label="CET1 capital ratio (as reported, bank)")
register_metric("bank.additional_tier1_ratio", "x", OTHER,
                label="Additional Tier 1 ratio (as reported, bank)")

# --- insurance.* ---
_pl("insurance.net_earned_premium", "Net earned premium")
_pl("insurance.claims_incurred", "Net claims incurred (incl. loss adjustment expenses)")
_pl("insurance.underwriting_expenses", "Underwriting expenses (commission and operating)")
_pl("insurance.net_investment_income", "Net investment income")
